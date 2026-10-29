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
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("douyin-youtube-self-hosted")

VIDEO_ID_REGEX = re.compile(r"/video/(\d+)")
DIGITS_REGEX = re.compile(r"^(\d{15,25})$")


def shorten_provider_error(err: str | None) -> str:
    """Convert raw technical error strings into concise, user-friendly labels."""
    if not err:
        return ""
    text = str(err)
    if "502" in text or "Bad Gateway" in text:
        return "Lỗi cổng API (HTTP 502)"
    if "503" in text or "Service Unavailable" in text:
        return "Dịch vụ tạm thời quá tải (HTTP 503)"
    if "500" in text or "Internal Server Error" in text:
        return "Lỗi máy chủ nội bộ (HTTP 500)"
    if "429" in text or "Rate" in text:
        return "Giới hạn tần suất (HTTP 429)"
    if "TIMEOUT" in text.upper() or "timed out" in text.lower():
        return "Hết thời gian chờ (Timeout)"
    if "OFFLINE" in text.upper() or "ConnectError" in text or "connection refused" in text.lower():
        return "Máy chủ ngoại tuyến (Offline)"
    if "AUTH" in text.upper() or "401" in text or "403" in text:
        return "Lỗi xác thực API"
    if "QUOTA" in text.upper():
        return "Hết hạn mức API"
    # Clean prefix
    cleaned = text
    for prefix in ("PROVIDER_ERROR:", "All self-hosted Douyin API endpoints failed:"):
        if prefix in cleaned:
            cleaned = cleaned.replace(prefix, "").strip()
    cleaned = cleaned.split("\n")[0].strip()
    return cleaned[:80] if len(cleaned) > 80 else cleaned


class DouyinSelfHostedError(Exception):
    """Typed error for Douyin self-hosted API. Never carries the API key."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        provider_url: str | None = None,
        short_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.provider_url = provider_url
        self.short_message = short_message or shorten_provider_error(message)


@dataclass
class CircuitState:
    failures: int = 0
    last_failure_at: float = 0.0
    is_open: bool = False


class EndpointCircuitBreaker:
    """In-process circuit breaker for self-hosted endpoints.

    Prevents hammering failing servers and avoids unnecessary timeout delays.
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 180.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, CircuitState] = {}

    def is_available(self, base_url: str) -> bool:
        norm = base_url.rstrip("/")
        state = self._states.get(norm)
        if not state or not state.is_open:
            return True
        now = time.time()
        if (now - state.last_failure_at) >= self.cooldown_seconds:
            # Half-open: allow a trial probe
            return True
        return False

    def record_success(self, base_url: str) -> None:
        norm = base_url.rstrip("/")
        self._states[norm] = CircuitState(failures=0, last_failure_at=0.0, is_open=False)

    def record_failure(self, base_url: str) -> None:
        norm = base_url.rstrip("/")
        state = self._states.setdefault(norm, CircuitState())
        state.failures += 1
        state.last_failure_at = time.time()
        if state.failures >= self.failure_threshold:
            state.is_open = True
            logger.warning(
                "Circuit breaker OPEN for %s (%d consecutive failures, cooldown=%.0fs)",
                norm,
                state.failures,
                self.cooldown_seconds,
            )

    def reset(self) -> None:
        self._states.clear()


circuit_breaker = EndpointCircuitBreaker()


@dataclass(frozen=True)
class DouyinSelfHostedConfig:
    api_key: str
    base_url: str = "http://162.4.177.109:8088"
    fallback_url: str = "https://douyin-api-8xzt.onrender.com"
    endpoint_path: str = "/api/douyin/video/urls"
    timeout_seconds: float = 120.0
    max_count: int = 200
    enabled: bool = True
    max_endpoint_retries: int = 1
    retry_backoff_seconds: float = 1.0


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

    def _provider_label(self, base_url: str) -> str:
        if "162.4.177.109" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
            return "Primary VPS"
        if "onrender.com" in base_url or "render" in base_url.lower():
            return "Render Fallback"
        return "Self-Hosted API"

    def _call_service(
        self,
        base_url: str,
        target_url: str,
        max_count: int,
    ) -> dict[str, Any]:
        """Make a single POST request to the designated service endpoint."""
        url = base_url.rstrip("/") + self.config.endpoint_path
        payload = {"url": target_url, "max_count": max_count}
        label = self._provider_label(base_url)

        logger.info(
            "Calling self-hosted Douyin API at %s (timeout=%.1fs, max_count=%d)",
            base_url,
            self.config.timeout_seconds,
            max_count,
        )

        try:
            with httpx.Client(timeout=float(self.config.timeout_seconds)) as client:
                resp = client.post(url, json=payload, headers=self._headers())
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            raise DouyinSelfHostedError(
                "TIMEOUT",
                f"Provider {base_url} timed out after {self.config.timeout_seconds}s",
                retryable=True,
                status_code=408,
                provider_url=base_url,
                short_message=f"{label}: Hết thời gian chờ (Timeout)",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise DouyinSelfHostedError(
                "PROVIDER_OFFLINE",
                f"Provider {base_url} offline or connection refused: {exc}",
                retryable=True,
                status_code=503,
                provider_url=base_url,
                short_message=f"{label}: Ngoại tuyến (Offline)",
            ) from exc
        except httpx.HTTPError as exc:
            raise DouyinSelfHostedError(
                "NETWORK_ERROR",
                f"Provider {base_url} network error: {exc}",
                retryable=True,
                provider_url=base_url,
                short_message=f"{label}: Lỗi mạng",
            ) from exc

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception as exc:
                raise DouyinSelfHostedError(
                    "INVALID_JSON",
                    f"Provider {base_url} returned invalid JSON: {exc}",
                    retryable=False,
                    status_code=200,
                    provider_url=base_url,
                    short_message=f"{label}: Phản hồi JSON không hợp lệ",
                ) from exc

            if not isinstance(data, dict):
                raise DouyinSelfHostedError(
                    "INVALID_RESPONSE",
                    f"Provider {base_url} response is not a JSON object",
                    retryable=False,
                    status_code=200,
                    provider_url=base_url,
                    short_message=f"{label}: Phản hồi không phải JSON",
                )

            if not data.get("success", False):
                err_msg = str(data.get("message") or data.get("error") or "success is False")
                raise DouyinSelfHostedError(
                    "API_UNSUCCESSFUL",
                    f"Provider {base_url} reported failure: {err_msg}",
                    retryable=True,
                    status_code=200,
                    provider_url=base_url,
                    short_message=f"{label}: API báo lỗi ({err_msg[:60]})",
                )

            return data

        snippet = (resp.text or "")[:120].strip()
        if resp.status_code in (401, 403):
            raise DouyinSelfHostedError(
                "AUTH_FAILED",
                f"Provider {base_url} auth failed (HTTP {resp.status_code})",
                retryable=False,
                status_code=resp.status_code,
                provider_url=base_url,
                short_message=f"{label}: Lỗi xác thực (HTTP {resp.status_code})",
            )
        if resp.status_code == 429:
            raise DouyinSelfHostedError(
                "RATE_LIMITED",
                f"Provider {base_url} rate limited (HTTP 429): {snippet}",
                retryable=True,
                status_code=429,
                provider_url=base_url,
                short_message=f"{label}: Quá tải tần suất (HTTP 429)",
            )
        if resp.status_code in (502, 503, 504):
            code_name = "HTTP 502" if resp.status_code == 502 else f"HTTP {resp.status_code}"
            raise DouyinSelfHostedError(
                "BAD_GATEWAY" if resp.status_code == 502 else "SERVER_UNAVAILABLE",
                f"Provider {base_url} gateway error (HTTP {resp.status_code}): {snippet}",
                retryable=True,
                status_code=resp.status_code,
                provider_url=base_url,
                short_message=f"{label}: Lỗi cổng kết nối ({code_name})",
            )
        if 500 <= resp.status_code <= 599:
            raise DouyinSelfHostedError(
                "SERVER_ERROR",
                f"Provider {base_url} error (HTTP {resp.status_code}): {snippet}",
                retryable=True,
                status_code=resp.status_code,
                provider_url=base_url,
                short_message=f"{label}: Lỗi máy chủ (HTTP {resp.status_code})",
            )
        raise DouyinSelfHostedError(
            "HTTP_ERROR",
            f"Provider {base_url} request failed (HTTP {resp.status_code}): {snippet}",
            retryable=False,
            status_code=resp.status_code,
            provider_url=base_url,
            short_message=f"{label}: Lỗi HTTP {resp.status_code}",
        )

    def fetch_video_items(
        self,
        target_url: str,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch video URLs from self-hosted API and convert them to normalized video dicts.

        Tries primary base_url first with retry/backoff and circuit breaker;
        falls over to fallback_url on retryable error.
        """
        if not self.config.enabled:
            raise DouyinSelfHostedError("DISABLED", "Self-hosted Douyin API is disabled", short_message="Douyin API bị vô hiệu hóa")
        if not self.config.api_key:
            raise DouyinSelfHostedError("NO_KEY", "Self-hosted Douyin API key is not configured", short_message="Chưa cấu hình API key")

        count = max_count if max_count is not None else self.config.max_count
        urls_to_try = [self.config.base_url]
        if self.config.fallback_url and self.config.fallback_url != self.config.base_url:
            urls_to_try.append(self.config.fallback_url)

        last_error: Exception | None = None
        data: dict[str, Any] | None = None

        for idx, base in enumerate(urls_to_try):
            if not circuit_breaker.is_available(base):
                logger.warning("Skipping %s: circuit breaker is OPEN", base)
                continue

            # Fail over immediately to alternative endpoint if available to avoid overloading broken endpoint
            has_alternative = (idx < len(urls_to_try) - 1)
            max_retries = 0 if has_alternative else max(0, int(self.config.max_endpoint_retries))
            for attempt in range(max_retries + 1):
                try:
                    data = self._call_service(base, target_url, count)
                    circuit_breaker.record_success(base)
                    break
                except DouyinSelfHostedError as exc:
                    last_error = exc
                    if exc.retryable and attempt < max_retries:
                        delay = self.config.retry_backoff_seconds * (2 ** attempt)
                        logger.info("Retrying %s in %.1fs (attempt %d/%d)...", base, delay, attempt + 1, max_retries)
                        time.sleep(delay)
                        continue
                    circuit_breaker.record_failure(base)
                    logger.warning(
                        "Self-hosted Douyin API at %s failed: %s; trying next endpoint if available",
                        base,
                        exc.short_message,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    circuit_breaker.record_failure(base)
                    logger.warning(
                        "Self-hosted Douyin API at %s crashed: %s; trying next endpoint if available",
                        base,
                        str(exc)[:100],
                    )
                    break
            if data is not None:
                break

        if data is None:
            if isinstance(last_error, DouyinSelfHostedError):
                raise last_error
            raise DouyinSelfHostedError(
                "ALL_ENDPOINTS_FAILED",
                f"All self-hosted Douyin API endpoints failed: {last_error}",
                retryable=True,
                short_message="Các máy chủ Douyin API đều phản hồi lỗi",
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
