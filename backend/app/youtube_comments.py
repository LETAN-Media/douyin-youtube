"""YouTube comment fetch + reply (commentThreads.list / comments.insert).

This module is the ONLY place that talks to YouTube's comment endpoints. It is
deliberately independent of the publishing path in app.youtube: reading
comments and posting replies uses a per-destination OAuth token that must
carry the ``youtube.force-ssl`` scope.

Every failure is normalised into a stable code so the worker and the
dashboard can react without parsing Google's error text.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterator

from googleapiclient.errors import HttpError

logger = logging.getLogger("douyin-youtube-youtube-comments")


#: Stable error codes surfaced to the API/UI.
YOUTUBE_REAUTH_REQUIRED = "YOUTUBE_REAUTH_REQUIRED"
YOUTUBE_SCOPE_MISSING = "YOUTUBE_SCOPE_MISSING"
YOUTUBE_QUOTA_EXCEEDED = "YOUTUBE_QUOTA_EXCEEDED"
COMMENTS_DISABLED = "COMMENTS_DISABLED"
COMMENT_NOT_FOUND = "COMMENT_NOT_FOUND"
COMMENT_REPLY_FAILED = "COMMENT_REPLY_FAILED"


class CommentServiceError(RuntimeError):
    """A YouTube comment operation failed with a known code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _error_reasons(exc: HttpError) -> list[str]:
    """All Google error 'reason' strings on an HttpError."""
    reasons: list[str] = []
    try:
        payload = json.loads(exc.content.decode("utf-8"))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error") or {}
        for item in error.get("errors") or []:
            reason = item.get("reason")
            if reason:
                reasons.append(str(reason))
        if error.get("status"):
            reasons.append(str(error["status"]))
    try:
        for detail in exc.error_details or []:
            reason = detail.get("reason")
            if reason:
                reasons.append(str(reason))
    except Exception:
        pass
    return reasons


def raise_for_http_error(exc: HttpError) -> None:
    """Translate a Google HttpError into a CommentServiceError."""
    status = exc.resp.status if exc.resp is not None else 0
    reasons = [r.lower() for r in _error_reasons(exc)]
    joined = " ".join(reasons)

    if "commentsdisabled" in joined.replace("_", ""):
        raise CommentServiceError(
            COMMENTS_DISABLED, "Video này đã tắt bình luận"
        ) from exc
    if "quotaexceeded" in joined.replace("_", "") or status == 429:
        raise CommentServiceError(
            YOUTUBE_QUOTA_EXCEEDED, "Đã hết quota YouTube API"
        ) from exc
    if "insufficientpermissions" in joined.replace("_", ""):
        raise CommentServiceError(
            YOUTUBE_SCOPE_MISSING,
            "Token thiếu scope youtube.force-ssl — cần Reconnect",
        ) from exc
    if status == 404:
        raise CommentServiceError(
            COMMENT_NOT_FOUND, "Không tìm thấy bình luận trên YouTube"
        ) from exc
    if status in (401,):
        raise CommentServiceError(
            YOUTUBE_REAUTH_REQUIRED, "Token YouTube hết hiệu lực — cần Reconnect"
        ) from exc
    if status == 403:
        # Ambiguous 403: most often a missing scope on an old token.
        raise CommentServiceError(
            YOUTUBE_SCOPE_MISSING,
            "YouTube từ chối (403) — kiểm tra lại scope force-ssl",
        ) from exc
    raise CommentServiceError(
        COMMENT_REPLY_FAILED, f"YouTube API error {status}: {exc}"
    ) from exc


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_comment(
    item: dict[str, Any],
    *,
    video_id: str,
    parent_comment_id: str | None,
) -> dict[str, Any]:
    snippet = item.get("snippet") or {}
    author_channel = snippet.get("authorChannelId") or {}
    return {
        "youtube_comment_id": str(item.get("id") or ""),
        "parent_comment_id": parent_comment_id,
        "video_id": video_id,
        "author_channel_id": author_channel.get("value"),
        "author_name": snippet.get("authorDisplayName"),
        "text_original": str(snippet.get("textOriginal") or "").strip(),
        "published_at": _parse_datetime(snippet.get("publishedAt")),
        "updated_at": _parse_datetime(snippet.get("updatedAt")),
        "like_count": int(snippet.get("likeCount") or 0),
        "total_reply_count": int(snippet.get("totalReplyCount") or 0),
        "can_reply": bool(snippet.get("canReply", True)),
    }


def fetch_video_comments(
    youtube: Any,
    video_id: str,
    *,
    max_pages: int = 2,
    page_size: int = 100,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch comment threads for one video.

    Returns (comments, next_page_token). Top-level comments have
    ``parent_comment_id=None``; their replies carry the parent id. Only
    top-level comments are reply candidates.

    Raises CommentServiceError, including COMMENTS_DISABLED for videos with
    comments switched off (the caller must skip, never retry forever).
    """
    comments: list[dict[str, Any]] = []
    page_token: str | None = None
    pages = 0

    while pages < max(1, max_pages):
        request = youtube.commentThreads().list(
            part="snippet,replies",
            videoId=video_id,
            maxResults=max(1, min(100, page_size)),
            order="time",
            textFormat="plainText",
            pageToken=page_token,
        )
        try:
            response = request.execute()
        except HttpError as exc:
            raise_for_http_error(exc)

        for thread in response.get("items") or []:
            snippet = thread.get("snippet") or {}
            top = snippet.get("topLevelComment")
            if not top:
                continue
            comments.append(
                _normalize_comment(top, video_id=video_id, parent_comment_id=None)
            )
            for reply in (thread.get("replies") or {}).get("comments") or []:
                comments.append(
                    _normalize_comment(
                        reply,
                        video_id=video_id,
                        parent_comment_id=str(top.get("id") or ""),
                    )
                )

        page_token = response.get("nextPageToken")
        pages += 1
        if not page_token:
            break

    return comments, page_token


def insert_comment_reply(
    youtube: Any,
    parent_comment_id: str,
    text: str,
) -> str:
    """Post a reply to an existing comment via comments.insert.

    ``comments.insert`` with ``parentId`` is the correct reply primitive;
    commentThreads.insert must not be used for replies.
    """
    body = {
        "snippet": {
            "parentId": parent_comment_id,
            "textOriginal": text,
        }
    }
    try:
        response = (
            youtube.comments()
            .insert(part="snippet", body=body)
            .execute()
        )
    except HttpError as exc:
        raise_for_http_error(exc)

    reply_id = response.get("id")
    if not reply_id:
        raise CommentServiceError(
            COMMENT_REPLY_FAILED, "YouTube không trả về id cho reply"
        )
    return str(reply_id)


def fetch_video_titles(
    youtube: Any,
    video_ids: list[str],
) -> dict[str, str]:
    """Map video_id -> title for the given ids (best effort).

    Never raises: a title is cosmetic and must not abort a comment scan.
    """
    result: dict[str, str] = {}
    ids = [str(v) for v in video_ids if v]
    for start in range(0, len(ids), 50):
        chunk = ids[start:start + 50]
        if not chunk:
            continue
        try:
            response = (
                youtube.videos()
                .list(part="snippet", id=",".join(chunk))
                .execute()
            )
        except HttpError as exc:
            logger.info("Video title lookup failed: %s", exc)
            continue
        for item in response.get("items") or []:
            title = (item.get("snippet") or {}).get("title")
            if title:
                result[str(item.get("id"))] = str(title)
    return result


def iter_reply_candidates(
    comments: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Yield only top-level comments (the ones we are allowed to reply to)."""
    for comment in comments:
        if not comment.get("parent_comment_id"):
            yield comment


__all__ = [
    "COMMENTS_DISABLED",
    "COMMENT_NOT_FOUND",
    "COMMENT_REPLY_FAILED",
    "CommentServiceError",
    "YOUTUBE_QUOTA_EXCEEDED",
    "YOUTUBE_REAUTH_REQUIRED",
    "YOUTUBE_SCOPE_MISSING",
    "fetch_video_comments",
    "insert_comment_reply",
    "iter_reply_candidates",
    "raise_for_http_error",
    "fetch_video_titles",
]
