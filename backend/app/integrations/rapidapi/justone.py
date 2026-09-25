"""JustOneAPI (via RapidAPI gateway) Douyin user video list client.

Provider: "Douyin/China Tiktok All API" by justoneapi on RapidAPI.
Live-verified 2026-09-24 on host douyin-china-tiktok-all-api.p.rapidapi.com:
  GET {base}/api/douyin/get-user-video-list/v3?secUid=...[&maxCursor=...]
  headers: x-rapidapi-key, x-rapidapi-host
  success: HTTP 200 {"code": 0, "data": {"aweme_list": [...],
    "has_more": 0/1, "max_cursor": ms-epoch, "min_cursor": 0}}
  transient: HTTP 503 {"code": 301, "message":
    "COLLECT FAILED, SEND REQUEST AGAIN"} — common on cold cache; the
    SAME request usually succeeds within a few short retries (verified
    live: 8 consecutive 301s once, then code=0 on the next attempt).
Business codes: 0 ok | 100 token | 301 retry | 302 rate limit |
303 quota exceeded | 400 params | 500/503 | 600/601/602 perms/balance.

Pagination cursor: response max_cursor is ms-epoch (e.g. 1788168600000);
send it back as maxCursor for the next page. First page: omit maxCursor
(docs default 0).

QUOTA
-----
One page = one billed request. The BASIC plan is ~20 requests a month, so
this client never spends a request it has not been allowed to spend:
  * before every attempt it asks app.douyin_quota for permission,
  * every response is reconciled against RapidAPI's own rate-limit headers
    (falling back to local accounting when the headers are absent),
  * a 429 / code 303 is terminal — no retry, the quota record is marked
    exhausted and a plain request gets one bounded retry ladder.

No Douyin cookie, no browser, no yt-dlp. Media download stays with the
existing Rcuts flow (download_video) using share_url/aweme_id.
"""

import logging
import time
from typing import Any

import httpx

from app import douyin_quota
from app.config import settings

logger = logging.getLogger("justone-douyin-client")

RETRYABLE_BUSINESS = {301, 302, 500, 503}
RETRYABLE_STATUS = {500, 502, 503, 504}

#: Bounded retry ladder (seconds) used for the documented cold-cache 301.
#: Five attempts maximum: the endpoint's own message asks the caller to
#: re-send, but every attempt is a billed request, so the ladder is short
#: and stops immediately when the quota floor is reached.
RETRY_BACKOFF_SECONDS = (0, 2, 4, 6, 10)

# Rate-limit headers RapidAPI exposes on this API.
RATELIMIT_HEADERS = (
    "x-ratelimit-requests-limit",
    "x-ratelimit-requests-remaining",
    "x-ratelimit-requests-reset",
)


def get_last_rate_limit() -> dict[str, Any] | None:
    """Last observed RapidAPI quota snapshot (single source of truth)."""
    try:
        return douyin_quota.snapshot()
    except Exception:  # pragma: no cover - defensive, quota must never crash a scan
        return None


class JustOneError(RuntimeError):
    pass


class JustOneAuthError(JustOneError):
    pass


class JustOneQuotaError(JustOneError):
    pass


class JustOneRateLimitError(JustOneError):
    pass


def _config() -> tuple[str, str]:
    base = (settings.douyin_rapidapi_base_url or "").strip().rstrip("/")
    host = (settings.douyin_rapidapi_host or "").strip()
    if not base and host:
        base = f"https://{host}"
    return base, host


def _user_posts_path() -> str:
    path = (getattr(settings, "douyin_rapidapi_user_posts_path", "") or "").strip()
    return path or "/api/douyin/get-user-video-list/v3"


def _record_quota(headers: Any) -> None:
    """Reconcile one response against the quota record.

    Headers are authoritative when RapidAPI sends them. When it does not, the
    request is still billed, so it is counted locally — under-counting is the
    one error that would let a scan walk past the limit.
    """
    try:
        snap = douyin_quota.record_headers(headers)
        if snap is None:
            douyin_quota.note_local_spend(1)
    except Exception:  # pragma: no cover - never break a scan over bookkeeping
        logger.warning("Quota bookkeeping failed for a RapidAPI response")


def fetch_user_videos(
    sec_uid: str,
    max_cursor: str | None = None,
    count: int = 20,
) -> dict[str, Any]:
    """Fetch ONE page of creator videos.

    Returns normalized
    {items:[{aweme_id, caption, create_time, share_url, cover_url}],
     next_cursor, has_more, quota}.

    `count` is accepted for interface compat; the v3 endpoint does not take a
    count parameter (server returns a full page of ~20-23 items).

    Raises JustOneQuotaError without spending anything when the remaining
    quota is at the configured safety floor.
    """
    sec_uid = (sec_uid or "").strip()
    if not sec_uid:
        raise JustOneError("DOUYIN_SOURCE_INVALID: empty secUid")

    key = (settings.rapidapi_key or "").strip()
    if not key:
        raise JustOneAuthError("RAPIDAPI_KEY not configured")

    base, host = _config()
    if not base or not host:
        raise JustOneError("DOUYIN_RAPIDAPI_HOST/BASE_URL not configured")

    url = base.rstrip("/") + _user_posts_path()
    params: dict[str, Any] = {"secUid": sec_uid}
    if max_cursor not in (None, ""):
        params["maxCursor"] = max_cursor
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}

    last_exc: Exception | None = None
    for attempt, backoff in enumerate(RETRY_BACKOFF_SECONDS):
        if backoff:
            time.sleep(backoff)

        # Quota gate: refuse before spending, not after.
        try:
            douyin_quota.ensure_can_spend(1)
        except douyin_quota.QuotaExhausted as exc:
            raise JustOneQuotaError(str(exc)) from exc

        try:
            with httpx.Client(timeout=90) as client:
                resp = client.get(url, params=params, headers=headers)
        except Exception as exc:
            last_exc = JustOneError(f"JUSTONE_TIMEOUT: {exc}")
            if attempt < len(RETRY_BACKOFF_SECONDS) - 1 and (
                "timeout" in str(exc).lower() or "connect" in str(exc).lower()
            ):
                logger.warning("JustOne retry %s: %s", attempt + 1, exc)
                continue
            raise

        _record_quota(resp.headers)

        if resp.status_code in (401, 403):
            raise JustOneAuthError(
                f"RAPIDAPI_AUTH_ERROR: HTTP {resp.status_code} {resp.text[:300]}"
            )
        if resp.status_code == 429:
            # Terminal: this is the monthly subscription limit, not a blip.
            # Retrying only burns the window and hides the real state.
            message = f"RAPIDAPI_QUOTA_EXCEEDED: {resp.text[:300]}"
            douyin_quota.mark_exhausted(message)
            raise JustOneQuotaError(message)
        if resp.status_code in RETRYABLE_STATUS:
            last_exc = JustOneError(
                f"RETRYABLE HTTP {resp.status_code}: {resp.text[:300]}"
            )
            if attempt < len(RETRY_BACKOFF_SECONDS) - 1 and douyin_quota.can_spend(1):
                continue
            raise last_exc
        if resp.status_code != 200:
            raise JustOneError(f"HTTP {resp.status_code}: {resp.text[:400]}")

        try:
            data = resp.json()
        except Exception as exc:
            raise JustOneError(f"Invalid JSON: {exc} body={resp.text[:300]}") from exc

        code = data.get("code")
        if code in (100, 101, 202):
            raise JustOneAuthError(
                f"RAPIDAPI_AUTH_ERROR: code={code} {data.get('message')}"
            )
        if code == 303:
            message = f"RAPIDAPI_QUOTA_EXCEEDED: {data.get('message')}"
            douyin_quota.mark_exhausted(message)
            raise JustOneQuotaError(message)
        if code == 302:
            last_exc = JustOneRateLimitError(
                f"RAPIDAPI_RATE_LIMIT: {data.get('message')}"
            )
            if attempt < len(RETRY_BACKOFF_SECONDS) - 1 and douyin_quota.can_spend(1):
                continue
            raise last_exc
        if code == 301:
            last_exc = JustOneError(f"RETRYABLE code=301: {data.get('message')}")
            if attempt < len(RETRY_BACKOFF_SECONDS) - 1:
                if not douyin_quota.can_spend(1):
                    # Cold cache would need more attempts than the quota can
                    # afford; stop and report instead of draining the month.
                    douyin_quota.note_provider_error(
                        "RapidAPI 301 repeated and quota is at the safety floor"
                    )
                    raise JustOneQuotaError(
                        "RAPIDAPI_QUOTA_GUARD: cold-cache 301 retries stopped — "
                        "remaining quota is at the safety floor"
                    ) from None
                logger.warning(
                    "JustOne 301 (cold cache), retry %s/%s",
                    attempt + 1,
                    len(RETRY_BACKOFF_SECONDS),
                )
                continue
            raise last_exc
        if code == 400:
            raise JustOneError(f"DOUYIN_SOURCE_INVALID: {data.get('message')}")
        if code not in (0, None):
            raise JustOneError(f"code={code}: {str(data.get('message'))[:400]}")

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
        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "quota": get_last_rate_limit(),
        }

    raise JustOneError(f"JustOne fetch failed after retries: {last_exc}")


def fetch_user_posts(
    sec_user_id: str,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Task-spec entrypoint: fetch_user_posts(sec_user_id, cursor)."""
    return fetch_user_videos(sec_user_id, max_cursor=cursor)


__all__ = [
    "JustOneAuthError",
    "JustOneError",
    "JustOneQuotaError",
    "JustOneRateLimitError",
    "RATELIMIT_HEADERS",
    "RETRY_BACKOFF_SECONDS",
    "RETRYABLE_BUSINESS",
    "fetch_user_posts",
    "fetch_user_videos",
    "get_last_rate_limit",
]
