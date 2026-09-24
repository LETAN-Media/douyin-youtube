"""HTTP client for the self-hosted Douyin Feed API (Evil0ctal dtk v5).

The feed service runs as a SEPARATE deployment (local: docker compose on
127.0.0.1:8010; production: Northflank). This client only speaks HTTP —
no Evil0ctal source code is imported or vendored here.

Service: https://github.com/Evil0ctal/Douyin_TikTok_Download_API (v5.1.1)
Endpoint used (verified live 2026-09-24):
  GET {base}/api/v1/douyin/user/posts?sec_user_id=...&count=..&cursor=..&wait=30
  header: X-API-Key: <service API key>
  success envelope: {"success": true, "data": {"items": [...], ...},
                     "meta": {"cursor": {"next": "...", "has_more": bool}}}
  item shape (service normalization): content_id, title, description,
  created_at (ISO-8601), web_url, kind, author{...}, media{covers,...}.
  Errors: {"success": false, "error": {"code": "IDENTITY_POOL_EXHAUSTED" |
  "UPSTREAM_RISK_CONTROL" | ...}} — surfaced verbatim, never guessed.

Risk-control reality (measured live on a guest-identity pool):
page 1 of a creator is cache-warm and cheap, but fetching page 2 with the
freshly returned cursor forces a live upstream call that the platform often
flags; the identity cools down exponentially (60s base). So the client:
  - keeps per-creator page memory and stops the moment a fetch fails,
    keeping the last good page for that creator (scans still return data);
  - treats page 1 as the primary AUTO scan path — new videos appear there.
Caches: repeat page-1 calls inside the 5-minute list TTL are answered from
the service cache and cost no identity.

Discovery only. Downloading stays with the existing Rcuts flow
(download_video) using https://www.douyin.com/video/{content_id}.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("douyin-feed-client")

RETRYABLE_STATUS = {429, 502, 503, 504}

# Error codes the service returns when it cannot serve right now. These are
# transient pool/upstream states, not client bugs.
TRANSIENT_POOL_CODES = {
    "IDENTITY_POOL_EXHAUSTED",
    "UPSTREAM_RISK_CONTROL",
    "RATE_LIMITED",
    "UPSTREAM_TIMEOUT",
}


class DouyinFeedError(RuntimeError):
    pass


class DouyinFeedAuthError(DouyinFeedError):
    pass


class DouyinFeedUnavailableError(DouyinFeedError):
    """Service reachable but cannot serve now (identity pool empty etc.)."""


class DouyinFeedPageLimitError(DouyinFeedError):
    """A deeper page hit upstream risk control mid-scan.

    The per-creator pages fetched before the failure are still valid; the
    caller (provider) keeps them instead of failing the whole scan.
    """


class DouyinFeedClient:
    """Thin HTTP client: creator sec_user_id -> normalized posts."""

    name = "douyin_feed"

    def __init__(self) -> None:
        # Per-creator memory of how far a scan got before a transient stop.
        # Keyed by sec_user_id; value = last cursor that failed (skipped on
        # the next scan so a known-hot cursor does not burn an identity).
        self._stalled_cursors: dict[str, set[str]] = {}

    def _base_url(self) -> str:
        base = (settings.douyin_feed_api_base_url or "").strip().rstrip("/")
        if not base:
            raise DouyinFeedError(
                "DOUYIN_FEED_API_BASE_URL is not configured"
            )
        return base

    def _headers(self) -> dict[str, str]:
        key = (settings.douyin_feed_api_key or "").strip()
        if not key:
            raise DouyinFeedAuthError(
                "DOUYIN_FEED_API_KEY is not configured"
            )
        return {"X-API-Key": key}

    # -- raw HTTP ----------------------------------------------------------

    def _request(
        self,
        params: dict[str, Any],
        *,
        attempts: int = 3,
        retry_sleep: int = 10,
    ) -> dict[str, Any]:
        base = self._base_url()
        last_exc: Exception | None = None
        for attempt in range(attempts):
            if attempt:
                # Identity pool recovers in ~10s steps; short waits only.
                time.sleep(retry_sleep)
            try:
                with httpx.Client(timeout=max(60, int(params.get("wait", 30)) + 30)) as client:
                    resp = client.get(
                        f"{base}/api/v1/douyin/user/posts",
                        params=params,
                        headers=self._headers(),
                    )
            except Exception as exc:
                last_exc = DouyinFeedError(f"DOUYIN_FEED_UNREACHABLE: {exc}")
                logger.warning("douyin_feed request failed: %s", exc)
                continue

            if resp.status_code in (401, 403):
                raise DouyinFeedAuthError(
                    f"DOUYIN_FEED_AUTH_ERROR: HTTP {resp.status_code} "
                    f"{resp.text[:200]}"
                )
            if resp.status_code == 429:
                last_exc = DouyinFeedError(
                    f"DOUYIN_FEED_RATE_LIMIT: {resp.text[:200]}"
                )
                continue
            if resp.status_code in RETRYABLE_STATUS:
                last_exc = DouyinFeedError(
                    f"DOUYIN_FEED_RETRYABLE HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
                continue
            if resp.status_code != 200:
                raise DouyinFeedError(
                    f"DOUYIN_FEED_HTTP {resp.status_code}: {resp.text[:300]}"
                )

            try:
                payload = resp.json()
            except Exception as exc:
                raise DouyinFeedError(
                    f"DOUYIN_FEED_BAD_JSON: {exc}"
                ) from exc

            if not payload.get("success"):
                error = payload.get("error") or {}
                code = str(error.get("code") or "UNKNOWN")
                message = str(error.get("message") or "")[:300]
                if code in TRANSIENT_POOL_CODES:
                    last_exc = DouyinFeedUnavailableError(
                        f"DOUYIN_FEED_TRANSIENT: {code} {message}"
                    )
                    continue
                if code in ("UNAUTHENTICATED", "FORBIDDEN", "INVALID_API_KEY"):
                    raise DouyinFeedAuthError(
                        f"DOUYIN_FEED_AUTH_ERROR: {code} {message}"
                    )
                raise DouyinFeedError(
                    f"DOUYIN_FEED_PROVIDER_ERROR: {code} {message}"
                )

            return payload

        raise last_exc or DouyinFeedError("douyin_feed request failed")

    # -- public API --------------------------------------------------------

    def fetch_user_posts(
        self,
        sec_user_id: str,
        cursor: str | None = None,
        count: int = 20,
        wait_seconds: int = 30,
    ) -> dict[str, Any]:
        """One page of a creator's posts.

        Returns normalized: {items, has_more, next_cursor} where items is
        {aweme_id, caption, create_time(int epoch s), share_url, cover_url}.
        Raises DouyinFeedPageLimitError when the page hit upstream risk
        control and the caller already holds earlier pages.
        """
        sec_user_id = (sec_user_id or "").strip()
        if not sec_user_id:
            raise DouyinFeedError("DOUYIN_SOURCE_INVALID: empty sec_user_id")

        params: dict[str, Any] = {
            "sec_user_id": sec_user_id,
            "count": max(1, min(int(count or 20), 50)),
            "wait": wait_seconds,
        }
        if cursor:
            params["cursor"] = cursor

        try:
            payload = self._request(params)
        except (
            DouyinFeedUnavailableError,
            DouyinFeedError,
        ) as exc:
            # ANY failure on a deeper page is a scan-stop, not a scan-fail:
            # the earlier pages the caller already collected remain valid.
            # Page-1 failures (no cursor) still raise to the caller.
            if cursor:
                raise DouyinFeedPageLimitError(str(exc)) from exc
            raise

        meta = payload.get("meta") or {}
        return self._normalize(payload.get("data") or {}, meta)

    def scan_creator_posts(
        self,
        sec_user_id: str,
        max_pages: int = 3,
        count: int = 20,
    ) -> list[dict[str, Any]]:
        """Multi-page creator scan with per-page risk-control tolerance.

        Page 1 is mandatory (its failure raises). Deeper pages stop the scan
        gracefully on transient upstream flags, keeping what was fetched.
        Returns a list of normalized inventory items (newest first).
        """
        sec_user_id = (sec_user_id or "").strip()
        stalled = self._stalled_cursors.setdefault(sec_user_id, set())

        collected: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        for page in range(max(1, min(max_pages, 3))):
            # Skip a cursor that burned an identity on a previous scan: the
            # platform is likely to flag that exact page again immediately.
            if cursor and cursor in stalled:
                logger.info(
                    "douyin_feed skipping stalled cursor for secUid=%s",
                    sec_user_id[:12],
                )
                break
            try:
                result = self.fetch_user_posts(
                    sec_user_id, cursor=cursor, count=count
                )
            except DouyinFeedPageLimitError as exc:
                if cursor:
                    stalled.add(cursor)
                logger.info(
                    "douyin_feed scan stopped after %s page(s) for secUid=%s: %s",
                    page,
                    sec_user_id[:12],
                    str(exc)[:120],
                )
                break

            for item in result.get("items", []):
                collected.setdefault(str(item["aweme_id"]), item)

            if not result.get("has_more"):
                break
            next_cursor = str(result.get("next_cursor") or "")
            if not next_cursor:
                break
            cursor = next_cursor

        ordered = list(collected.values())
        ordered.sort(key=lambda i: int(i.get("create_time") or 0), reverse=True)
        return ordered

    # -- normalization -----------------------------------------------------

    @staticmethod
    def _normalize(data: Any, meta: dict[str, Any]) -> dict[str, Any]:
        items_raw: list[Any] = []
        if isinstance(data, list):
            items_raw = data
        elif isinstance(data, dict):
            for key in ("items", "posts", "list", "aweme_list"):
                value = data.get(key)
                if isinstance(value, list):
                    items_raw = value
                    break

        items: list[dict[str, Any]] = []
        for entry in items_raw:
            if not isinstance(entry, dict):
                continue
            aweme_id = str(
                entry.get("content_id") or entry.get("aweme_id") or entry.get("id") or ""
            ).strip()
            if not aweme_id:
                continue
            caption = str(entry.get("title") or entry.get("description") or "").strip()

            created_at = entry.get("created_at")
            create_ts = iso_to_epoch(created_at)

            share_url = str(entry.get("web_url") or entry.get("share_url") or "").strip()
            if not share_url:
                share_url = f"https://www.douyin.com/video/{aweme_id}"

            cover_url = ""
            media = entry.get("media")
            if isinstance(media, dict):
                covers = media.get("covers")
                if isinstance(covers, list) and covers:
                    first = covers[0]
                    if isinstance(first, dict):
                        cover_url = str(first.get("url") or "")
                    else:
                        cover_url = str(first)

            items.append(
                {
                    "aweme_id": aweme_id,
                    "caption": caption,
                    "create_time": create_ts,
                    "share_url": share_url,
                    "cover_url": cover_url,
                }
            )

        has_more = False
        next_cursor = ""
        cursor = meta.get("cursor") if isinstance(meta, dict) else None
        if isinstance(cursor, dict):
            has_more = bool(cursor.get("has_more"))
            next_cursor = str(cursor.get("next") or "")
        elif isinstance(data, dict):
            has_more = bool(data.get("has_more"))
            next_cursor = str(data.get("max_cursor") or "")

        return {"items": items, "has_more": has_more, "next_cursor": next_cursor}


def iso_to_epoch(created_at: Any) -> int:
    """ISO-8601 / epoch-s / epoch-ms -> epoch seconds (0 when unknown)."""
    if isinstance(created_at, (int, float)):
        ts = int(created_at)
        return ts // 1000 if ts > 10_000_000_000 else ts
    if isinstance(created_at, str) and created_at:
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            return 0
    return 0
