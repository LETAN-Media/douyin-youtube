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
One page = one billed request. Each RapidAPI provider (key) has its own quota
record. This client never spends a request it has not been allowed to spend:
  * before every attempt it asks app.douyin_quota for permission,
  * every response is reconciled against RapidAPI's own rate-limit headers
    (falling back to local accounting when the headers are absent),
  * a 429 / code 303 is terminal — no retry, the provider's quota record is
    marked exhausted and the pool moves to the next provider.

No Douyin cookie, no browser, no yt-dlp. Media download stays with the
existing Rcuts flow (download_video) using share_url/aweme_id.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app import douyin_quota
from app.integrations.rapidapi.provider_config import (
    RapidApiProviderConfig,
    _primary_config,
)

logger = logging.getLogger("justone-douyin-client")

RETRYABLE_BUSINESS = {301, 302, 500, 503}
RETRYABLE_STATUS = {500, 502, 503, 504}

#: Bounded retry ladder (seconds). Each attempt is a billed request, so the
#: ladder is short and stops immediately when the provider's quota floor is
#: reached. Providers can lower this with `..._MAX_RETRIES`.
RETRY_BACKOFF_SECONDS = (0, 2, 4, 6, 10)

# Rate-limit headers RapidAPI exposes on this API.
RATELIMIT_HEADERS = (
    "x-ratelimit-requests-limit",
    "x-ratelimit-requests-remaining",
    "x-ratelimit-requests-reset",
)


class JustOneError(RuntimeError):
    kind = "provider"
    retryable = False


class JustOneAuthError(JustOneError):
    kind = "auth"


class JustOneQuotaError(JustOneError):
    kind = "quota"


class JustOneRateLimitError(JustOneError):
    kind = "rate_limit"
    retryable = True


class JustOneTimeoutError(JustOneError):
    kind = "timeout"
    retryable = True


class JustOneUnavailableError(JustOneError):
    kind = "unavailable"
    retryable = True


class JustOneSchemaError(JustOneError):
    kind = "schema"


class JustOneInvalidRequestError(JustOneError):
    kind = "invalid_request"


def _config_or_default(
    config: RapidApiProviderConfig | None,
) -> RapidApiProviderConfig:
    return config if config is not None else _primary_config()


def get_last_rate_limit(
    provider_id: str = douyin_quota.DEFAULT_PROVIDER_ID,
) -> dict[str, Any] | None:
    """Last observed quota snapshot for one provider (no secrets)."""
    try:
        return douyin_quota.snapshot(provider_id)
    except Exception:  # pragma: no cover - quota must never crash a scan
        return None


def _record_quota(
    headers: Any,
    config: RapidApiProviderConfig,
) -> None:
    """Reconcile one response against this provider's quota record.

    Headers are authoritative when RapidAPI sends them. When it does not, the
    request is still billed, so it is counted locally — under-counting is the
    one error that would let a scan walk past the limit.
    """
    try:
        default_limit = config.monthly_request_limit or None
        snap = douyin_quota.record_headers(
            headers,
            provider_id=config.provider_id,
            default_limit=default_limit,
        )
        if snap is None:
            douyin_quota.note_local_spend(
                1,
                provider_id=config.provider_id,
                default_limit=default_limit,
            )
    except Exception:  # pragma: no cover - never break a scan over bookkeeping
        logger.warning("Quota bookkeeping failed for provider %s", config.provider_id)


def _can_spend(config: RapidApiProviderConfig) -> bool:
    return douyin_quota.can_spend(
        1,
        provider_id=config.provider_id,
        default_limit=config.monthly_request_limit or None,
    )


def _raise_for_code(
    code: Any,
    message: Any,
    *,
    config: RapidApiProviderConfig,
    attempt: int,
    attempts: int,
) -> None:
    text = str(message or "")
    if code in (100, 101, 202):
        raise JustOneAuthError(
            f"RAPIDAPI_AUTH_ERROR: code={code} {text[:300]}"
        )
    if code == 303:
        quota_message = f"RAPIDAPI_QUOTA_EXCEEDED: {text[:300]}"
        douyin_quota.mark_exhausted(
            quota_message,
            provider_id=config.provider_id,
            default_limit=config.monthly_request_limit or None,
        )
        raise JustOneQuotaError(quota_message)
    if code == 302:
        raise JustOneRateLimitError(
            f"RAPIDAPI_RATE_LIMIT: {text[:300]}"
        )
    if code == 301:
        if attempt < attempts - 1 and _can_spend(config):
            return
        raise JustOneUnavailableError(
            f"RAPIDAPI_UNAVAILABLE: code=301 {text[:300]}"
        )
    if code == 400:
        raise JustOneInvalidRequestError(
            f"DOUYIN_SOURCE_INVALID: {text[:300]}"
        )
    if code in (600, 601):
        raise JustOneAuthError(
            f"RAPIDAPI_AUTH_ERROR: code={code} {text[:300]}"
        )
    if code == 602:
        quota_message = f"RAPIDAPI_QUOTA_EXCEEDED: {text[:300]}"
        douyin_quota.mark_exhausted(
            quota_message,
            provider_id=config.provider_id,
            default_limit=config.monthly_request_limit or None,
        )
        raise JustOneQuotaError(quota_message)
    if code not in (0, None):
        raise JustOneError(f"code={code}: {text[:400]}")


def fetch_page(
    config: RapidApiProviderConfig,
    sec_uid: str,
    cursor: str | None = None,
    *,
    count: int = 20,
) -> dict[str, Any]:
    """Fetch ONE page using one explicitly configured provider.

    Returns normalized
    {items:[{aweme_id, caption, create_time, share_url, cover_url}],
     next_cursor, has_more, quota, provider_id}.

    `count` is accepted for interface compat; the v3 endpoint does not take a
    count parameter (server returns a full page of ~20-23 items).
    """
    sec_uid = (sec_uid or "").strip()
    if not sec_uid:
        raise JustOneInvalidRequestError("DOUYIN_SOURCE_INVALID: empty secUid")

    if not config.api_key:
        raise JustOneAuthError(
            f"RAPIDAPI_KEY not configured for {config.provider_id}"
        )
    if not config.base_url or not config.host:
        raise JustOneUnavailableError(
            f"RAPIDAPI_HOST/BASE_URL not configured for {config.provider_id}"
        )
    if not config.path:
        raise JustOneUnavailableError(
            f"RAPIDAPI endpoint path not configured for {config.provider_id}"
        )

    url = config.base_url.rstrip("/") + config.path
    params: dict[str, Any] = {"secUid": sec_uid}
    if cursor not in (None, ""):
        params["maxCursor"] = cursor
    headers = {
        "x-rapidapi-key": config.api_key,
        "x-rapidapi-host": config.host,
    }

    attempts = max(1, min(int(config.max_retries), 4) + 1)
    last_exc: Exception | None = None

    for attempt in range(attempts):
        backoff = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
        if backoff:
            time.sleep(backoff)

        # Quota gate: refuse before spending, not after.
        try:
            douyin_quota.ensure_can_spend(
                1,
                provider_id=config.provider_id,
                default_limit=config.monthly_request_limit or None,
            )
        except douyin_quota.QuotaExhausted as exc:
            raise JustOneQuotaError(str(exc)) from exc

        try:
            with httpx.Client(timeout=float(config.timeout_seconds)) as client:
                resp = client.get(url, params=params, headers=headers)
        except Exception as exc:
            text = str(exc)
            is_timeout = "timeout" in text.lower() or "timed out" in text.lower()
            last_exc = (
                JustOneTimeoutError(f"JUSTONE_TIMEOUT: {text[:300]}")
                if is_timeout
                else JustOneUnavailableError(f"JUSTONE_CONNECTION_ERROR: {text[:300]}")
            )
            if attempt < attempts - 1 and _can_spend(config):
                logger.warning(
                    "Provider %s attempt %s failed: %s",
                    config.provider_id,
                    attempt + 1,
                    text[:200],
                )
                continue
            raise last_exc

        _record_quota(resp.headers, config)

        if resp.status_code in (401, 403):
            raise JustOneAuthError(
                f"RAPIDAPI_AUTH_ERROR: HTTP {resp.status_code} {resp.text[:300]}"
            )
        if resp.status_code == 429:
            # Terminal for this provider: monthly subscription limit, not a
            # blip. The pool will move to the next provider.
            message = f"RAPIDAPI_QUOTA_EXCEEDED: {resp.text[:300]}"
            douyin_quota.mark_exhausted(
                message,
                provider_id=config.provider_id,
                default_limit=config.monthly_request_limit or None,
            )
            raise JustOneQuotaError(message)
        if resp.status_code in (400, 422):
            raise JustOneInvalidRequestError(
                f"DOUYIN_SOURCE_INVALID: HTTP {resp.status_code} {resp.text[:300]}"
            )
        if resp.status_code in RETRYABLE_STATUS:
            last_exc = JustOneUnavailableError(
                f"RETRYABLE HTTP {resp.status_code}: {resp.text[:300]}"
            )
            if attempt < attempts - 1 and _can_spend(config):
                continue
            raise last_exc
        if resp.status_code != 200:
            raise JustOneUnavailableError(
                f"HTTP {resp.status_code}: {resp.text[:400]}"
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise JustOneSchemaError(
                f"Invalid JSON: {exc} body={resp.text[:300]}"
            ) from exc

        if not isinstance(data, dict):
            raise JustOneSchemaError("Invalid schema: response is not an object")

        code = data.get("code")
        _raise_for_code(
            code,
            data.get("message"),
            config=config,
            attempt=attempt,
            attempts=attempts,
        )
        if code == 301 and attempt < attempts - 1:
            # _raise_for_code returns only when this attempt is retryable.
            logger.warning(
                "Provider %s cold-cache 301, retry %s/%s",
                config.provider_id,
                attempt + 1,
                attempts,
            )
            continue

        payload = data.get("data")
        if not isinstance(payload, dict):
            raise JustOneSchemaError("Invalid schema: missing data object")
        aweme_list = payload.get("aweme_list")
        if aweme_list is None:
            aweme_list = payload.get("awemeList")
        if not isinstance(aweme_list, list):
            raise JustOneSchemaError(
                "Invalid schema: data.aweme_list is not a list"
            )

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
        next_cursor = str(
            payload.get("max_cursor", payload.get("maxCursor", "")) or ""
        )
        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "quota": get_last_rate_limit(config.provider_id),
            "provider_id": config.provider_id,
        }

    raise JustOneError(f"JustOne fetch failed after retries: {last_exc}")


def fetch_user_videos(
    sec_uid: str,
    max_cursor: str | None = None,
    count: int = 20,
    *,
    config: RapidApiProviderConfig | None = None,
) -> dict[str, Any]:
    """Backward-compatible entrypoint for the primary/legacy config."""
    return fetch_page(
        _config_or_default(config),
        sec_uid,
        max_cursor,
        count=count,
    )


def fetch_user_posts(
    sec_user_id: str,
    cursor: str | None = None,
    *,
    config: RapidApiProviderConfig | None = None,
) -> dict[str, Any]:
    """Task-spec entrypoint: fetch_user_posts(sec_user_id, cursor)."""
    return fetch_user_videos(sec_user_id, max_cursor=cursor, config=config)


__all__ = [
    "JustOneAuthError",
    "JustOneError",
    "JustOneInvalidRequestError",
    "JustOneQuotaError",
    "JustOneRateLimitError",
    "JustOneSchemaError",
    "JustOneTimeoutError",
    "JustOneUnavailableError",
    "RATELIMIT_HEADERS",
    "RETRY_BACKOFF_SECONDS",
    "RETRYABLE_BUSINESS",
    "RETRYABLE_STATUS",
    "fetch_page",
    "fetch_user_posts",
    "fetch_user_videos",
    "get_last_rate_limit",
]
