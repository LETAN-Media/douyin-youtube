"""RapidAPI Douyin creator feed client (no Douyin cookie required).

Provider: DouYin API (tikhub-team) on RapidAPI Hub.
Endpoint (verified live 2026-09-24):
  GET {base}{path}?sec_user_id=...&max_cursor=...&count=...
  headers: x-rapidapi-key, x-rapidapi-host
Response envelope: {"code": 200, "data": {"aweme_list": [...], "has_more": 0/1,
  "max_cursor": ...}, ...} on success; {"code": 500, "message": ...} on
provider-side upstream block (e.g. Argus signature).

Only share_url/aweme_id are used downstream. This client NEVER downloads
media — download stays with existing Rcuts flow (download_video).
"""

import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("rapidapi-douyin-client")

RETRYABLE_STATUS = {429, 502, 503, 504}


class RapidApiError(RuntimeError):
    pass


class RapidApiAuthError(RapidApiError):
    pass


class RapidApiQuotaError(RapidApiError):
    pass


class RapidApiRateLimitError(RapidApiError):
    pass


def _config() -> tuple[str, str, str]:
    base = (settings.douyin_rapidapi_base_url or "").strip().rstrip("/")
    host = (settings.douyin_rapidapi_host or "").strip()
    path = (settings.douyin_rapidapi_user_posts_path or "").strip()
    if not base and host:
        base = f"https://{host}"
    return base, host, path or "/api/v1/douyin/app/v3/fetch_user_post_videos"


def fetch_user_posts(
    sec_user_id: str,
    cursor: str | None = None,
    count: int = 20,
) -> dict[str, Any]:
    """Fetch one page of creator posts. Returns normalized
    {items:[{aweme_id, caption, create_time, share_url, cover_url}],
     next_cursor, has_more}."""
    sec_user_id = (sec_user_id or "").strip()
    if not sec_user_id:
        raise RapidApiError("DOUYIN_SOURCE_INVALID: empty sec_user_id")

    key = (settings.rapidapi_key or "").strip()
    if not key:
        raise RapidApiAuthError("RAPIDAPI_KEY not configured")

    base, host, path = _config()
    if not base or not host:
        raise RapidApiError("DOUYIN_RAPIDAPI_HOST/BASE_URL not configured")

    url = base.rstrip("/") + "/" + path.lstrip("/")
    params: dict[str, Any] = {
        "sec_user_id": sec_user_id,
        "max_cursor": cursor or "0",
        "count": max(1, min(int(count or 20), 35)),
    }
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}

    last_exc: Exception | None = None
    for attempt, backoff in enumerate([0, 2, 5, 15]):
        if backoff:
            time.sleep(backoff)
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params, headers=headers)
        except Exception as exc:
            last_exc = RapidApiError(f"REVID_TIMEOUT: {exc}")
            if attempt < 3 and ("timeout" in str(exc).lower() or "connect" in str(exc).lower()):
                logger.warning("RapidAPI retry %s: %s", attempt + 1, exc)
                continue
            raise

        if resp.status_code in (401, 403):
            raise RapidApiAuthError(
                f"REVID_AUTH_ERROR: HTTP {resp.status_code} {resp.text[:300]}"
            )
        if resp.status_code == 429:
            last_exc = RapidApiRateLimitError(
                f"REVID_RATE_LIMIT: HTTP 429 {resp.text[:300]}"
            )
            if attempt < 3:
                logger.warning("RapidAPI 429, backoff %ss", backoff or 2)
                continue
            raise last_exc
        if resp.status_code in RETRYABLE_STATUS:
            last_exc = RapidApiError(
                f"RETRYABLE: HTTP {resp.status_code} {resp.text[:300]}"
            )
            if attempt < 3:
                continue
            raise last_exc
        if resp.status_code != 200:
            raise RapidApiError(f"HTTP {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
        except Exception as exc:
            raise RapidApiError(f"Invalid JSON: {exc} body={resp.text[:400]}") from exc

        # Envelope: {code, message, data: {aweme_list, has_more, max_cursor}}
        code = data.get("code")
        if code != 200:
            msg = str(data.get("message") or data.get("message_zh") or "")
            if "quota" in msg.lower() or "credit" in msg.lower() or "402" in msg:
                raise RapidApiQuotaError(f"REVID_NO_CREDITS: {msg[:500]}")
            raise RapidApiError(f"Provider error code={code}: {msg[:500]}")

        payload = data.get("data") or {}
        aweme_list = payload.get("aweme_list") or payload.get("awemeList") or []
        if not isinstance(aweme_list, list):
            aweme_list = []

        items: list[dict[str, Any]] = []
        for v in aweme_list:
            if not isinstance(v, dict):
                continue
            aweme_id = str(v.get("aweme_id") or v.get("awemeId") or "").strip()
            if not aweme_id:
                continue
            caption = str(v.get("desc") or v.get("description") or "").strip()
            share_url = str(v.get("share_url") or v.get("shareUrl") or "").strip()
            if not share_url:
                share_url = f"https://www.douyin.com/video/{aweme_id}"
            cover_url = ""
            video = v.get("video") or {}
            if isinstance(video, dict):
                cover = video.get("cover") or {}
                if isinstance(cover, dict):
                    urls = cover.get("url_list") or cover.get("urlList") or []
                    if isinstance(urls, list) and urls:
                        cover_url = str(urls[0])
            # create_time may be seconds or ms
            create_time = v.get("create_time", v.get("createTime", 0))
            try:
                ts = int(create_time or 0)
                if ts > 10_000_000_000:
                    ts //= 1000
            except (TypeError, ValueError):
                ts = 0
            items.append(
                {
                    "aweme_id": aweme_id,
                    "caption": caption,
                    "create_time": ts,
                    "share_url": share_url,
                    "cover_url": cover_url,
                }
            )

        try:
            has_more = int(payload.get("has_more", payload.get("hasMore", 0)) or 0) != 0
        except (TypeError, ValueError):
            has_more = False
        next_cursor = str(payload.get("max_cursor", payload.get("maxCursor", "")) or "")
        return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

    raise RapidApiError(f"RapidAPI fetch failed after retries: {last_exc}")
