"""RevidAPI Douyin creator feed client (no Douyin cookie required)."""

import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("revid-douyin-client")

# Docs: POST https://revidapi.com/v1/douyin/user/download?sec_user_id=...&max_cursor=...
# Task spec: POST https://api.revidapi.com/paid/douyin/user/download (support both via base_url)

RETRYABLE = {429, 502, 503, 504}


class RevidError(RuntimeError):
    pass


class RevidAuthError(RevidError):
    pass


class RevidNoCreditsError(RevidError):
    pass


class RevidRateLimitError(RevidError):
    pass


def _base_url() -> str:
    raw = (settings.revid_api_base_url or "https://revidapi.com").strip().rstrip("/")
    # Normalize: if task's api.revidapi.com/paid is used, keep as is
    return raw


def _build_url(base: str, sec_user_id: str, max_cursor: str | None) -> str:
    base = base.rstrip("/")
    # If base already contains /v1 or /paid, append user/download correctly
    if base.endswith("/v1"):
        base = base + "/douyin/user/download"
    elif base.endswith("/paid"):
        base = base + "/douyin/user/download"
    elif "/douyin/user/download" not in base:
        # Default to docs path
        if "api.revidapi.com" in base:
            base = base.rstrip("/") + "/paid/douyin/user/download"
        else:
            base = base.rstrip("/") + "/v1/douyin/user/download"
    # sec_user_id as query param, max_cursor optional
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}sec_user_id={sec_user_id}"
    if max_cursor and max_cursor != "0":
        url += f"&max_cursor={max_cursor}"
    elif max_cursor == "0" or max_cursor is None:
        # First page: max_cursor=0 or omit
        if "max_cursor" not in url:
            url += "&max_cursor=0"
    return url


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    key = (settings.revid_api_key or "").strip()
    if key:
        h["x-api-key"] = key
    return h


def _error_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 401 or resp.status_code == 403:
        raise RevidAuthError(f"REVID_AUTH_ERROR: HTTP {resp.status_code} {resp.text[:500]}")
    if resp.status_code == 402:
        raise RevidNoCreditsError(f"REVID_NO_CREDITS: HTTP {resp.status_code} {resp.text[:500]}")
    if resp.status_code == 429:
        raise RevidRateLimitError(f"REVID_RATE_LIMIT: HTTP {resp.status_code} {resp.text[:500]}")
    if resp.status_code in RETRYABLE:
        raise RevidError(f"REVID_RETRYABLE: HTTP {resp.status_code} {resp.text[:500]}")
    if resp.status_code != 200:
        # Try to parse detail
        try:
            j = resp.json()
            detail = j.get("detail") or j.get("msg") or resp.text
        except Exception:
            detail = resp.text
        raise RevidError(f"HTTP {resp.status_code}: {detail[:800]}")


class RevidDouyinClient:
    def fetch_user_videos(
        self,
        sec_user_id: str,
        max_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one page of Douyin user videos via RevidAPI.

        Returns normalized: {items, has_more, next_cursor, raw}
        Raises RevidError subclasses on auth/credits/rate limit.
        """
        sec_user_id = (sec_user_id or "").strip()
        if not sec_user_id:
            raise RevidError("sec_user_id is empty")

        base = _base_url()
        url = _build_url(base, sec_user_id, max_cursor or "0")
        headers = _headers()

        if not headers.get("x-api-key"):
            raise RevidAuthError("REVID_AUTH_ERROR: REVID_API_KEY not configured")

        # Retry for 429/502/503/504 with backoff 2s/5s/15s
        last_exc: Exception | None = None
        for attempt, backoff in enumerate([0, 2, 5, 15]):
            if backoff:
                time.sleep(backoff)
            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.post(url, headers=headers)
                if resp.status_code in RETRYABLE or resp.status_code == 429:
                    _error_for_status(resp)
                _error_for_status(resp)
                try:
                    data = resp.json()
                except Exception as exc:
                    raise RevidError(f"Invalid JSON from RevidAPI: {exc} body={resp.text[:800]}") from exc

                # Normalize per docs: {sec_user_id, videos: [{aweme_id, description, video_url, share_url}], max_cursor, has_more, total_fetched}
                videos = data.get("videos") or data.get("aweme_list") or data.get("items") or []
                if not isinstance(videos, list):
                    videos = []
                items: list[dict[str, Any]] = []
                for v in videos:
                    if not isinstance(v, dict):
                        continue
                    aweme_id = str(v.get("aweme_id") or v.get("id") or "").strip()
                    if not aweme_id:
                        continue
                    caption = str(v.get("description") or v.get("desc") or "").strip()
                    share_url = str(v.get("share_url") or v.get("shareUrl") or "").strip()
                    if not share_url and aweme_id:
                        share_url = f"https://www.douyin.com/video/{aweme_id}"
                    cover_url = str(v.get("cover_url") or v.get("cover") or "").strip()
                    # Revid's video_url is direct file URL, but we prefer share_url for Rcuts
                    raw_item = v
                    items.append(
                        {
                            "aweme_id": aweme_id,
                            "caption": caption,
                            "create_time": v.get("create_time") or v.get("createTime"),
                            "share_url": share_url,
                            "cover_url": cover_url,
                            "video_url": v.get("video_url"),
                            "raw": raw_item,
                        }
                    )
                has_more = bool(data.get("has_more", data.get("hasMore", False)))
                next_cursor = str(data.get("max_cursor", data.get("maxCursor", "")) or "")
                return {
                    "items": items,
                    "has_more": has_more,
                    "next_cursor": next_cursor,
                    "raw": data,
                    "total_fetched": data.get("total_fetched", len(items)),
                }
            except (RevidRateLimitError, RevidError) as exc:
                last_exc = exc
                # Only retry for retryable
                if isinstance(exc, (RevidRateLimitError,)) or "REVID_RETRYABLE" in str(exc) or "429" in str(exc) or "502" in str(exc):
                    if attempt < 3:
                        logger.warning("Revid retry %s/%s after %s: %s", attempt + 1, 3, backoff, exc)
                        continue
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < 3 and ("timeout" in str(exc).lower() or "502" in str(exc) or "503" in str(exc)):
                    logger.warning("Revid retry %s after %s: %s", attempt + 1, backoff, exc)
                    continue
                raise
        raise RevidError(f"Revid fetch failed after retries: {last_exc}")

