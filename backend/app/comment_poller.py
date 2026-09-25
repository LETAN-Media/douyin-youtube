"""AI comment reply worker — a subsystem independent of publishing.

Separate loop, separate interval: this never runs inside the publish worker,
so comment polling cannot block a video upload. It only ever touches
``youtube_comments`` and the comment_* columns of ``destinations``.

Flow per channel:
    enabled channel -> recent published videos -> commentThreads.list
    -> dedupe on youtube_comment_id -> classify/draft (REVIEW) or reply (AUTO)

Everything here goes through a per-destination OAuth token that must carry
``youtube.force-ssl``; channels authorised earlier are skipped with
YOUTUBE_SCOPE_MISSING until they reconnect.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Sentiment routing lives in ai_comment_reply; `is_emoji_only` is re-exported
# from there so the poller keeps a single source of truth for the check.
from app.ai_comment_reply import (
    EMOJI_ONLY,
    EXCITED,
    FUNNY,
    HOLD_CLASSIFICATIONS,
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    QUESTION,
    build_reply_for_classification,
    classify_comment,
    is_emoji_only,
    normalize_label,
)
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Destination,
    Publication,
    YouTubeComment,
)
from app.youtube import (
    build_destination_client,
    destination_comment_scope_status,
)
from app.youtube_comments import (
    COMMENTS_DISABLED,
    COMMENT_NOT_FOUND,
    CommentServiceError,
    fetch_video_comments,
    fetch_video_titles,
    insert_comment_reply,
)

logger = logging.getLogger("douyin-youtube-comment-worker")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

#: Which channel toggle governs each sentiment label, and its default when a
#: channel has never been configured. Praise and questions are answered by
#: default; every other category is opt-in.
_REPLY_TOGGLES: dict[str, tuple[str, bool]] = {
    POSITIVE: ("comment_reply_to_positive", True),
    QUESTION: ("comment_reply_to_questions", True),
    NEUTRAL: ("comment_reply_to_neutral", False),
    NEGATIVE: ("comment_reply_to_negative", False),
    FUNNY: ("comment_reply_to_funny", False),
    EXCITED: ("comment_reply_to_excited", False),
    EMOJI_ONLY: ("comment_reply_to_emoji_only", False),
}


def eligibility_reason(
    classification: str,
    destination: Destination,
) -> tuple[bool, str]:
    """Can this classified comment be replied to for this channel?

    Returns (eligible, reason). One toggle per sentiment label; a disabled
    category is held WITHOUT any further model call (the reply for everything
    but `positive` is a backend emoji map anyway).
    """
    label = normalize_label(classification)
    if label is None:
        return False, f"no policy for classification={classification or 'UNKNOWN'}"

    if label in HOLD_CLASSIFICATIONS:
        return False, f"held: classification={label}"

    flag, default = _REPLY_TOGGLES[label]
    allowed = bool(getattr(destination, flag, default))
    return (allowed, "ok" if allowed else f"{label} replies disabled")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def replies_today(db: Session, destination_id: str) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.execute(
            select(func.count(YouTubeComment.id))
            .where(YouTubeComment.destination_id == destination_id)
            .where(YouTubeComment.status == "replied")
            .where(YouTubeComment.replied_at >= start)
        ).scalar()
        or 0
    )


def last_reply_at(db: Session, destination_id: str) -> datetime | None:
    return db.execute(
        select(func.max(YouTubeComment.replied_at))
        .where(YouTubeComment.destination_id == destination_id)
    ).scalar()


def can_reply_now(
    db: Session,
    destination: Destination,
) -> tuple[bool, str | None]:
    """Daily limit + minimum interval gate for one channel."""
    limit = int(getattr(destination, "comment_reply_daily_limit", 20) or 0)
    if limit <= 0:
        return False, "daily reply limit is 0"

    used = replies_today(db, destination.id)
    if used >= limit:
        return False, f"daily reply limit reached ({used}/{limit})"

    interval = int(
        getattr(destination, "comment_reply_min_interval_seconds", 180) or 0
    )
    if interval > 0:
        previous = last_reply_at(db, destination.id)
        if previous is not None:
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            next_allowed = previous + timedelta(seconds=interval)
            if utcnow() < next_allowed:
                return False, (
                    "min interval not elapsed "
                    f"(next at {next_allowed.isoformat()})"
                )
    return True, None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _apply_status(comment: YouTubeComment, status: str) -> None:
    """Keep `status` and its fetch/dedupe mirror `reply_status` in sync."""
    comment.status = status
    comment.reply_status = status


def _recent_published_video_ids(
    db: Session,
    destination_id: str,
    limit: int,
) -> list[str]:
    rows = db.execute(
        select(Publication.external_post_id, Publication.published_at)
        .where(Publication.destination_id == destination_id)
        .where(Publication.status == "published")
        .where(Publication.external_post_id.isnot(None))
        .order_by(Publication.published_at.desc().nullslast())
        .limit(max(1, limit))
    ).all()
    ids: list[str] = []
    for external_post_id, _published_at in rows:
        value = str(external_post_id or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _upsert_comment(
    db: Session,
    destination: Destination,
    video_id: str,
    video_title: str | None,
    payload: dict[str, Any],
) -> tuple[YouTubeComment, bool]:
    """Insert or update one comment. Returns (comment, is_new)."""
    comment_id = payload["youtube_comment_id"]
    existing = db.execute(
        select(YouTubeComment)
        .where(YouTubeComment.youtube_comment_id == comment_id)
        .limit(1)
    ).scalar_one_or_none()

    if existing is not None:
        # Refresh mutable fields only; never touch reply state.
        existing.like_count = payload.get("like_count") or 0
        existing.text_original = payload.get("text_original") or ""
        existing.comment_text = existing.text_original
        if video_title and not existing.video_title:
            existing.video_title = video_title[:400]
        return existing, False

    comment = YouTubeComment(
        destination_id=destination.id,
        video_id=video_id,
        video_title=(video_title or None),
        youtube_comment_id=comment_id,
        parent_comment_id=payload.get("parent_comment_id"),
        author_channel_id=payload.get("author_channel_id"),
        author_name=payload.get("author_name"),
        text_original=payload.get("text_original") or "",
        comment_text=payload.get("text_original") or "",
        published_at=payload.get("published_at"),
        like_count=payload.get("like_count") or 0,
        status="new",
        reply_status="new",
    )
    db.add(comment)
    return comment, True


def _reconcile_replying(
    db: Session,
    destination: Destination,
    fetched: list[dict[str, Any]],
) -> int:
    """Resolve comments stuck in `replying` after a crash.

    If YouTube already shows a reply from this channel under the comment, the
    local row was never committed past the API call: mark it replied instead
    of posting a duplicate.
    """
    channel_id = (destination.external_account_id or "").strip()
    if not channel_id:
        return 0

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in fetched:
        parent = item.get("parent_comment_id")
        if parent:
            by_parent.setdefault(str(parent), []).append(item)

    stuck = db.execute(
        select(YouTubeComment)
        .where(YouTubeComment.destination_id == destination.id)
        .where(YouTubeComment.status == "replying")
    ).scalars().all()

    resolved = 0
    for comment in stuck:
        for reply in by_parent.get(comment.youtube_comment_id, []):
            if str(reply.get("author_channel_id") or "") != channel_id:
                continue
            comment.youtube_reply_id = reply.get("youtube_comment_id")
            comment.reply_text = reply.get("text_original")
            comment.replied_at = reply.get("published_at") or utcnow()
            _apply_status(comment, "replied")
            comment.error = None
            resolved += 1
            logger.info(
                "Reconciled already-posted reply for comment=%s",
                comment.youtube_comment_id,
            )
            break
        else:
            # No visible reply: safe to retry with a fresh draft.
            _apply_status(comment, "ready_to_reply")
    return resolved


# ---------------------------------------------------------------------------
# Reply posting
# ---------------------------------------------------------------------------

def post_reply(
    db: Session,
    comment: YouTubeComment,
    destination: Destination,
    text: str,
    *,
    youtube: Any | None = None,
) -> YouTubeComment:
    """Send one reply to YouTube and persist the result.

    Never posts twice: a comment that already has youtube_reply_id is returned
    untouched.
    """
    if comment.youtube_reply_id:
        return comment

    text = (text or "").strip()
    if not text:
        comment.error = "empty reply text"
        _apply_status(comment, "failed")
        db.commit()
        return comment

    ok, reason = destination_comment_scope_status(destination)
    if not ok:
        comment.error = reason
        _apply_status(comment, "failed")
        db.commit()
        return comment

    if youtube is None:
        _credentials, youtube = build_destination_client(db, destination.id)

    # Mark intent first so a crash between the API call and the commit is
    # recoverable (see _reconcile_replying).
    _apply_status(comment, "replying")
    comment.reply_text = text
    db.commit()

    try:
        reply_id = insert_comment_reply(
            youtube,
            parent_comment_id=comment.youtube_comment_id,
            text=text,
        )
    except CommentServiceError as exc:
        comment.error = f"{exc.code}: {exc.message}"
        # Comments disabled is terminal: never retry forever.
        if exc.code in (COMMENTS_DISABLED, COMMENT_NOT_FOUND):
            _apply_status(comment, "skipped")
        else:
            _apply_status(comment, "failed")
        db.commit()
        logger.warning("Reply failed comment=%s: %s", comment.youtube_comment_id, exc)
        return comment
    except Exception as exc:  # pragma: no cover - defensive
        comment.error = f"COMMENT_REPLY_FAILED: {exc}"
        _apply_status(comment, "failed")
        db.commit()
        logger.exception("Reply crashed comment=%s", comment.youtube_comment_id)
        return comment

    comment.youtube_reply_id = reply_id
    comment.replied_at = utcnow()
    comment.ai_reply = text
    comment.reply_text = text
    comment.error = None
    _apply_status(comment, "replied")
    db.commit()
    logger.info(
        "Replied to comment=%s (reply=%s) channel=%s",
        comment.youtube_comment_id,
        reply_id,
        destination.id,
    )
    return comment


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def draft_for_comment(
    comment: YouTubeComment,
    destination: Destination,
    video_title: str | None,
) -> YouTubeComment:
    """Classify one comment and build its reply.

    Cost shape (one model call per comment, two only for praise):
        1. classify  -> ALWAYS one call, unless the comment is emoji-only
                        (detected locally, no call).
        2. route     -> `positive` spends ONE generation call; every other
                        label is answered from the backend emoji map.
        3. filter    -> a category disabled on the channel is held BEFORE any
                        generation call is spent.

    A failure (AI off, both models down, reply rejected by the hard rules)
    leaves the exact error on the row and never writes random text.
    """
    classification = classify_comment(
        comment.text_original,
        destination=destination,
        video_title=video_title,
    )
    comment.detected_language = classification["language"]

    if not classification["ok"]:
        comment.ai_reason = "classification failed"
        comment.error = classification.get("error") or "AI_CLASSIFICATION_FAILED"
        _apply_status(comment, "failed")
        return comment

    label = classification["classification"]
    comment.ai_classification = label
    comment.ai_confidence = classification["confidence"]
    comment.ai_reason = classification["reason"]
    comment.error = None

    # A previous draft is stale the moment the comment is re-classified.
    comment.ai_reply = None
    comment.reply_text = None

    eligible, reason = eligibility_reason(label, destination)
    if not eligible:
        comment.ai_reason = reason
        _apply_status(comment, "held")
        return comment

    built = build_reply_for_classification(
        label,
        comment.text_original,
        destination=destination,
        video_title=video_title,
        reply_language=classification["language"],
        detected_language=classification["detected_language"],
    )
    if not built["ok"]:
        comment.error = built.get("error") or "AI_REPLY_FAILED"
        comment.ai_reason = f"reply build failed for {label}"
        _apply_status(comment, "failed")
        return comment

    reply = built["reply"]
    if not built["should_reply"] or not reply:
        comment.ai_reason = reason or "empty reply"
        _apply_status(comment, "held")
        return comment

    comment.ai_reply = reply
    comment.reply_text = reply
    _apply_status(comment, "ready_to_reply")
    return comment


def scan_destination(db: Session, destination: Destination) -> dict[str, Any]:
    """One scan pass for a single channel."""
    summary = {
        "destination_id": destination.id,
        "fetched": 0,
        "new": 0,
        "drafted": 0,
        "replied": 0,
        "held": 0,
        "error": None,
    }

    mode = (destination.comment_reply_mode or "off").lower()
    summary["mode"] = mode

    # Ingesting comments (commentThreads.list -> youtube_comments) is
    # INDEPENDENT of the AI-reply switch. An admin pressing "Quét bình luận"
    # must always fetch and store what is on YouTube; the mode only decides
    # whether the comments below are classified, drafted or replied to.
    reply_enabled = bool(destination.comment_reply_enabled) and mode in (
        "review",
        "auto",
    )

    ok, reason = destination_comment_scope_status(destination)
    if not ok:
        summary["error"] = reason
        logger.info(
            "Channel %s cannot use comment replies yet: %s",
            destination.id,
            reason,
        )
        return summary

    try:
        _credentials, youtube = build_destination_client(db, destination.id)
    except Exception as exc:
        summary["error"] = f"YOUTUBE_REAUTH_REQUIRED: {exc}"
        logger.warning("Cannot build client for channel %s: %s", destination.id, exc)
        return summary

    video_ids = _recent_published_video_ids(
        db,
        destination.id,
        int(getattr(settings, "comment_scan_videos_per_channel", 5) or 5),
    )
    if not video_ids:
        destination.last_comment_scan_at = utcnow()
        db.commit()
        return summary

    titles = fetch_video_titles(youtube, video_ids)

    # First pass: fetch everything so we can also reconcile stale rows.
    fetched_by_video: dict[str, list[dict[str, Any]]] = {}
    skipped_videos: set[str] = set()
    for video_id in video_ids:
        try:
            comments, _next = fetch_video_comments(
                youtube,
                video_id,
                max_pages=int(getattr(settings, "comment_threads_max_pages", 2) or 2),
            )
        except CommentServiceError as exc:
            if exc.code in (COMMENTS_DISABLED, COMMENT_NOT_FOUND):
                skipped_videos.add(video_id)
                logger.info("Skipping video %s: %s", video_id, exc.code)
                continue
            summary["error"] = f"{exc.code}: {exc.message}"
            logger.warning("Comment fetch failed video=%s: %s", video_id, exc)
            continue
        fetched_by_video[video_id] = comments
        summary["fetched"] += len(comments)

    all_fetched = [c for items in fetched_by_video.values() for c in items]
    if all_fetched:
        _reconcile_replying(db, destination, all_fetched)

    is_first_scan = destination.last_comment_scan_at is None
    cutoff = destination.last_comment_scan_at
    if cutoff is not None and cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    new_only = bool(getattr(destination, "comment_reply_new_only", True))

    created: list[YouTubeComment] = []
    for video_id, comments in fetched_by_video.items():
        video_title = titles.get(video_id)
        for payload in comments:
            if not payload.get("youtube_comment_id"):
                continue
            is_top_level = not payload.get("parent_comment_id")
            comment, is_new = _upsert_comment(
                db, destination, video_id, video_title, payload
            )
            if is_new:
                summary["new"] += 1
                created.append(comment)

            # Only top-level comments are reply candidates.
            if not is_new or not is_top_level:
                continue
            if not payload.get("can_reply", True):
                _apply_status(comment, "skipped")
                comment.ai_reason = "comment rejects replies"
                continue
            if new_only and cutoff is not None:
                published = payload.get("published_at")
                if published is not None and published <= cutoff:
                    _apply_status(comment, "ignored")
                    comment.ai_reason = "older than last scan (new_only)"
                    continue
            if reply_enabled and is_first_scan and mode == "auto":
                # Never blast a backlog of old comments on the first pass.
                _apply_status(comment, "ignored")
                comment.ai_reason = "first scan (backfill): no auto reply"
                continue

    db.commit()

    # Drafting / replying happens after the ingest commit so a crash mid-AI
    # never loses the fetched comments.
    #
    # REVIEW also picks up comments that were ingested while the assistant was
    # OFF (they are still `new`): drafting never writes to YouTube, so nothing
    # unsafe happens. AUTO stays restricted to the comments discovered by THIS
    # scan so enabling it can never reply to an existing backlog.
    pending: list[YouTubeComment] = []
    if reply_enabled:
        # Newly discovered comments keep their discovery order.
        pending = [c for c in created if c.status == "new"]
        if mode != "auto":
            seen = {c.id for c in pending}
            stored = db.execute(
                select(YouTubeComment)
                .where(YouTubeComment.destination_id == destination.id)
                .where(YouTubeComment.status == "new")
                .order_by(YouTubeComment.created_at.asc())
            ).scalars().all()
            pending += [c for c in stored if c.id not in seen]

    for comment in pending:
        _apply_status(comment, "analyzing")
        db.commit()

        draft_for_comment(comment, destination, comment.video_title)
        db.commit()

        if comment.status == "ready_to_reply":
            summary["drafted"] += 1

        if comment.status == "ready_to_reply" and mode == "auto":
            allowed, reason = can_reply_now(db, destination)
            if not allowed:
                comment.ai_reason = f"rate limited: {reason}"
                _apply_status(comment, "queued")
                db.commit()
                continue
            post_reply(db, comment, destination, comment.ai_reply or "", youtube=youtube)
            if comment.status == "replied":
                summary["replied"] += 1

        if comment.status == "held":
            summary["held"] += 1

    destination.last_comment_scan_at = utcnow()
    db.commit()
    return summary


def run_comment_scan_once() -> dict[str, Any]:
    """Scan every channel that has comment replies enabled."""
    result = {"channels": 0, "scanned": 0, "fetched": 0, "replied": 0, "errors": []}

    if not getattr(settings, "comment_reply_enabled", True):
        return result
    if not getattr(settings, "comment_scan_enabled", True):
        return result

    with SessionLocal() as db:
        destinations = db.execute(
            select(Destination)
            .where(Destination.platform == "youtube")
            .where(Destination.comment_reply_enabled == True)  # noqa: E712
            .where(Destination.comment_reply_mode.in_(["review", "auto"]))
        ).scalars().all()
        result["channels"] = len(destinations)

        for destination in destinations:
            try:
                summary = scan_destination(db, destination)
            except Exception as exc:  # one channel must never kill the cycle
                logger.exception("Comment scan failed for %s", destination.id)
                result["errors"].append(f"{destination.id}: {exc}")
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            result["scanned"] += 1
            result["fetched"] += summary["fetched"]
            result["replied"] += summary["replied"]
            if summary["error"]:
                result["errors"].append(f"{destination.id}: {summary['error']}")

    return result


async def comment_worker_loop() -> None:
    """Independent loop; never shares a task with the publish worker."""
    if not getattr(settings, "comment_reply_enabled", True):
        logger.info("Comment reply worker disabled via COMMENT_REPLY_ENABLED=false")
        return

    delay = int(getattr(settings, "comment_worker_startup_delay_seconds", 15) or 15)
    interval_seconds = max(
        60, int(getattr(settings, "comment_scan_minutes", 10) or 10) * 60
    )

    logger.info(
        "Comment reply worker started (interval=%ss, startup delay=%ss)",
        interval_seconds,
        delay,
    )
    await asyncio.sleep(delay)

    while True:
        try:
            summary = await asyncio.to_thread(run_comment_scan_once)
            logger.info("Comment scan finished: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Comment worker loop error")

        await asyncio.sleep(interval_seconds)


__all__ = [
    "can_reply_now",
    "comment_worker_loop",
    "draft_for_comment",
    "eligibility_reason",
    "is_emoji_only",
    "post_reply",
    "replies_today",
    "run_comment_scan_once",
    "scan_destination",
    "utcnow",
]
