"""Douyin self-hosted API client for fallback profile scanning.

Endpoints:
  Primary: VPS http://162.4.177.109:8088/api/douyin/video/urls
  Fallback: Render https://douyin-api-8xzt.onrender.com/api/douyin/video/urls
Payload:
  POST {"url": <profile_url_or_sec_uid>, "max_count": <count>}
Headers:
  X-API-Key: <api_key>
  Content-Type: application/json
Response:
  {"success": bool, "total": int, "sec_user_id": str, "video_urls": list[str]}

No cookies required, no RapidAPI quota consumed.
The API key is never logged or exposed in errors.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("douyin-youtube-self-hosted")

VIDEO_ID_REGEX = re.compile(r"/video/(\d+)")
DIGITS_REGEX = re.compile(r"^(\d{15,25})$")


class DouyinSelfHostedError(Exception):
    """Typed error for Douyin self-hosted API. Never carries the API key."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class DouyinSelfHostedConfig:
    api_key: str
    base_url: str = "http://162.4.177.109:8088"
    fallback_url: str = "https://douyin-api-8xzt.onrender.com"
    endpoint_path: str = "/api/douyin/video/urls"
    timeout_seconds: float = 120.0
    max_count: int = 200
    enabled: bool = True


def extract_video_id(url_or_id: str) -> str | None:
    """Extract a Douyin video ID from a URL or raw ID string."""
    text = (url_or_id or "").strip()
    if not text:
        return None
    m_digits = DIGITS_REGEX.match(text)
    if m_digits:
        return m_digits.group(1)
    m_url = VIDEO_ID_REGEX.search(text)
    if m_url:
        return m_url.group(1)
    cleaned = text.rstrip("/").split("/")[-1].split("?")[0]
    if DIGITS_REGEX.match(cleaned):
        return cleaned
    return None


class DouyinSelfHostedClient:
    """Client for the self-hosted Douyin video URL extraction API."""

    def __init__(self, config: DouyinSelfHostedConfig | None = None) -> None:
        if config is None:
            self.config = DouyinSelfHostedConfig(
                api_key=(getattr(settings, "douyin_self_hosted_api_key", "") or "").strip() or "api_key_0905132580",
                base_url=(getattr(settings, "douyin_self_hosted_api_base_url", "") or "").strip().rstrip("/") or "http://162.4.177.109:8088",
                fallback_url=(getattr(settings, "douyin_self_hosted_api_fallback_url", "") or "").strip().rstrip("/") or "https://douyin-api-8xzt.onrender.com",
                timeout_seconds=float(getattr(settings, "douyin_self_hosted_timeout_seconds", 120.0) or 120.0),
                max_count=max(1, int(getattr(settings, "douyin_self_hosted_max_count", 200) or 200)),
                enabled=bool(getattr(settings, "douyin_self_hosted_enabled", True)),
            )
        else:
            self.config = config

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
        }

    def _call_service(
        self,
        base_url: str,
        target_url: str,
        max_count: int,
    ) -> dict[str, Any]:
        """Make a single POST request to the designated service endpoint."""
        url = base_url.rstrip("/") + self.config.endpoint_path
        payload = {"url": target_url, "max_count": max_count}

        logger.info(
            "Calling self-hosted Douyin API at %s (timeout=%.1fs, max_count=%d)",
            base_url,
            self.config.timeout_seconds,
            max_count,
        )

        with httpx.Client(timeout=float(self.config.timeout_seconds)) as client:
            resp = client.post(url, json=payload, headers=self._headers())

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception as exc:
                raise DouyinSelfHostedError(
                    "INVALID_JSON",
                    f"Provider {base_url} returned invalid JSON: {exc}",
                    retryable=False,
                ) from exc

            if not isinstance(data, dict):
                raise DouyinSelfHostedError(
                    "INVALID_RESPONSE",
                    f"Provider {base_url} response is not a JSON object",
                    retryable=False,
                )

            if not data.get("success", False):
                err_msg = data.get("message") or data.get("error") or "success is False"
                raise DouyinSelfHostedError(
                    "API_UNSUCCESSFUL",
                    f"Provider {base_url} reported failure: {err_msg}",
                    retryable=True,
                )

            return data

        snippet = (resp.text or "")[:300]
        if resp.status_code in (401, 403):
            raise DouyinSelfHostedError(
                "AUTH_FAILED",
                f"Provider {base_url} auth failed (HTTP {resp.status_code})",
                retryable=False,
            )
        if 500 <= resp.status_code <= 599:
            raise DouyinSelfHostedError(
                "SERVER_ERROR",
                f"Provider {base_url} error (HTTP {resp.status_code}): {snippet}",
                retryable=True,
            )
        raise DouyinSelfHostedError(
            "HTTP_ERROR",
            f"Provider {base_url} request failed (HTTP {resp.status_code}): {snippet}",
            retryable=False,
        )

    def fetch_video_items(
        self,
        target_url: str,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch video URLs from self-hosted API and convert them to normalized video dicts.

        Tries primary base_url first; falls over to fallback_url on retryable error.
        """
        if not self.config.enabled:
            raise DouyinSelfHostedError("DISABLED", "Self-hosted Douyin API is disabled")
        if not self.config.api_key:
            raise DouyinSelfHostedError("NO_KEY", "Self-hosted Douyin API key is not configured")

        count = max_count if max_count is not None else self.config.max_count
        urls_to_try = [self.config.base_url]
        if self.config.fallback_url and self.config.fallback_url != self.config.base_url:
            urls_to_try.append(self.config.fallback_url)

        last_error: Exception | None = None
        data: dict[str, Any] | None = None

        for base in urls_to_try:
            try:
                data = self._call_service(base, target_url, count)
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Self-hosted Douyin API at %s failed: %s; trying next if available",
                    base,
                    str(exc)[:200],
                )

        if data is None:
            if isinstance(last_error, DouyinSelfHostedError):
                raise last_error
            raise DouyinSelfHostedError(
                "ALL_ENDPOINTS_FAILED",
                f"All self-hosted Douyin API endpoints failed: {last_error}",
            ) from last_error

        raw_urls = data.get("video_urls") or []
        if not isinstance(raw_urls, list):
            raw_urls = []

        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for raw_url in raw_urls:
            url_str = str(raw_url).strip()
            if not url_str:
                continue
            vid = extract_video_id(url_str)
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            items.append(
                {
                    "video_id": vid,
                    "url": f"https://www.douyin.com/video/{vid}",
                    "title": "",
                    "description": "",
                    "douyin_created_at": None,
                    "thumbnail_url": None,
                    "duration": None,
                }
            )

        logger.info(
            "Self-hosted Douyin API returned %d video URLs (%d unique video IDs)",
            len(raw_urls),
            len(items),
        )
        return items
