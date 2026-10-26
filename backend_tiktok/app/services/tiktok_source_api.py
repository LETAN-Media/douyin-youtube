"""Concrete TikTok provider: Source API (tiktok-api-xzze.onrender.com).

Uses the self-hosted TikTok Source API for profile resolution, channel video
listing with metadata, and single-video info.  Pagination via ``cursor`` is
attempted; if the API returns identical results across pages the scan records
a partial-scan flag rather than looping forever.

The provider implements the ``TikTokProvider`` ABC so the Scheduler, Publisher,
and Manual Publish flow are completely decoupled from the concrete adapter.

API contract (verified live):
  POST /api/tiktok/channel/videos  — full metadata per video
    { "url": "<profile_url>", "max_count": N, "cursor": <cursor> }
    → { success, platform, username, author, total_collected,
        video_urls: [...], videos: [{video_id, url, title, cover_url,
        duration_seconds, created_at, likes, comments, shares, views,
        bookmarks}], has_more, next_cursor, error_code, message }

  POST /api/tiktok/video/urls       — URLs only (lighter, for fast listing)
    { "url": "<profile_url>", "max_count": N, "cursor": <cursor> }
    → { success, platform, username, total_collected,
        video_urls: [...], has_more, next_cursor, error_code, message }

  GET  /api/tiktok/video/info      — single-video metadata
    ?url=<TIKTOK_VIDEO_URL>
    → { success, platform, video: {video_id, url, title, cover_url,
        duration_seconds, created_at, likes, comments, shares, views,
        bookmarks}, error_code, message }

Error handling:
  401/403 → ProviderError("auth")
  429     → ProviderError("rate_limited")
  5xx     → ProviderError("upstream")
  timeout   → ProviderError("timeout")
"""

import logging
from typing import Any

import httpx

from ..config import settings
from .tiktok_provider import (
    ProfileNotFound,
    ProviderError,
    TikTokMedia,
    TikTokProfile,
    TikTokProvider,
    TikTokReel,
)

logger = logging.getLogger("backend-tiktok.providers.source_api")


def _base_url() -> str:
    return (settings.tiktok_source_api_base_url or "").rstrip("/")


def _headers() -> dict[str, str]:
    key = settings.tiktok_source_api_key
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        **({"X-API-Key": key} if key else {}),
    }


def _timeout() -> float:
    try:
        return float(settings.tiktok_source_timeout_seconds or 120)
    except (TypeError, ValueError):
        return 120.0


class TikTokSourceAPIProvider(TikTokProvider):
    """TikTok profile/reel scraper backed by the self-hosted Source API."""

    @property
    def name(self) -> str:
        return "source_api"

    def _headers(self) -> dict[str, str]:
        key = settings.tiktok_source_api_key
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **({"X-API-Key": key} if key else {}),
        }

    def _client(
        self, transport: httpx.AsyncBaseTransport | None = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            timeout=_timeout(),
            headers=self._headers(),
            follow_redirects=True,
        )

    def _error_for_status(self, status_code: int) -> ProviderError | None:
        if status_code in (401, 403):
            return ProviderError("Auth failed: invalid or missing API key")
        if status_code == 429:
            return ProviderError("Rate limited by Source API provider")
        if 500 <= status_code < 600:
            return ProviderError(f"Source API upstream error ({status_code})")
        return None

    async def resolve_profile(
        self, username: str, source_url: str | None = None
    ) -> TikTokProfile:
        """Resolve a TikTok username/profile URL to a TikTokProfile.

        The Source API doesn't have a dedicated /profile endpoint, so we
        call /channel/videos once and extract profile metadata from the
        response.  This is acceptable since profile resolution is called
        infrequently (once per source setup).
        """
        if not username and source_url:
            from .tiktok_url import extract_username

            username = extract_username(source_url) or ""

        if not username:
            raise ProfileNotFound("Empty username")

        url = source_url or f"https://www.tiktok.com/@{username}"
        try:
            async with self._client() as client:
                resp = await client.post(
                    f"{_base_url()}/api/tiktok/channel/videos",
                    json={"url": url, "max_count": 1},
                )
        except httpx.TimeoutException:
            raise ProviderError("Profile request timed out (cold start or upstream slow)")
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderError(f"Profile request failed: {type(exc).__name__}") from exc

        err = self._error_for_status(resp.status_code)
        if err:
            raise err
        if resp.status_code != 200:
            raise ProviderError(f"Unexpected status {resp.status_code}")

        data: dict[str, Any] = resp.json()
        if not data.get("success"):
            ec = data.get("error_code")
            if ec == "NOT_FOUND" or "not found" in (data.get("message") or "").lower():
                raise ProfileNotFound(f"Profile not found: {username}")
            raise ProviderError(f"Source API error: {data.get('message') or 'unknown'}")

        return TikTokProfile(
            user_id=data.get("username") or username,
            username=data.get("username") or username,
            display_name=data.get("author") or data.get("display_name"),
            follower_count=None,
            following_count=None,
            is_verified=None,
            raw=data,
        )

    async def list_videos(
        self,
        profile: TikTokProfile,
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[TikTokReel], str | None]:
        """List reels for a profile.

        Returns ``(reels, next_cursor)``.  If the API's cursor pagination
        does not advance (``has_more`` true but cursor unchanged), the caller
        can detect a partial scan by comparing ``next_cursor`` to the input.
        """
        url = f"https://www.tiktok.com/@{profile.username}"
        body: dict[str, Any] = {"url": url, "max_count": min(limit, settings.tiktok_source_max_count)}
        if cursor:
            body["cursor"] = cursor

        try:
            async with self._client() as client:
                resp = await client.post(
                    f"{_base_url()}/api/tiktok/channel/videos",
                    json=body,
                )
        except httpx.TimeoutException:
            raise ProviderError("List request timed out")
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderError(f"List request failed: {type(exc).__name__}") from exc

        err = self._error_for_status(resp.status_code)
        if err:
            raise err
        if resp.status_code != 200:
            raise ProviderError(f"Unexpected status {resp.status_code}")

        data: dict[str, Any] = resp.json()
        if not data.get("success"):
            raise ProviderError(f"Source API error: {data.get('message') or 'unknown'}")

        videos: list[dict[str, Any]] = data.get("videos") or []
        reels: list[TikTokReel] = []
        for v in videos:
            if not isinstance(v, dict):
                continue
            video_id = str(v.get("video_id") or v.get("id") or "")
            if not video_id:
                continue
            reel_url = v.get("url") or (
                f"https://www.tiktok.com/@{profile.username}/video/{video_id}"
            )
            reels.append(
                TikTokReel(
                    video_id=video_id,
                    video_url=reel_url,
                    thumbnail_url=v.get("cover_url"),
                    caption=v.get("title") or v.get("desc"),
                    duration=v.get("duration_seconds"),
                    play_count=v.get("views") or v.get("playCount"),
                    create_time=v.get("created_at"),
                    width=v.get("width"),
                    height=v.get("height"),
                    raw=v,
                )
            )

        next_cursor = data.get("next_cursor")
        return reels, str(next_cursor) if next_cursor is not None else None

    async def resolve_media(self, url: str) -> TikTokMedia:
        """Resolve a single TikTok video URL to its media metadata.

        Uses GET /api/tiktok/video/info?url=<url>.  Does NOT download the
        MP4 — that is handled by the PHIMTAT shortcut provider.
        """
        if not url:
            raise ProviderError("Empty video URL")

        try:
            async with self._client() as client:
                resp = await client.get(
                    f"{_base_url()}/api/tiktok/video/info",
                    params={"url": url},
                )
        except httpx.TimeoutException:
            raise ProviderError("Media request timed out")
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderError(f"Media request failed: {type(exc).__name__}") from exc

        err = self._error_for_status(resp.status_code)
        if err:
            raise err
        if resp.status_code != 200:
            raise ProviderError(f"Unexpected status {resp.status_code}")

        data: dict[str, Any] = resp.json()
        if not data.get("success"):
            ec = data.get("error_code")
            if ec == "VIDEO_NOT_FOUND":
                raise ProviderError("Video not found or unavailable")
            raise ProviderError(f"Source API error: {data.get('message') or 'unknown'}")

        video: dict[str, Any] = data.get("video") or {}
        if not video:
            raise ProviderError("No video data in response")

        # The Source API doesn't return a direct download URL — the caller
        # (manual publish) must use PHIMTAT for the actual MP4 download.
        # We return the video URL itself; the publisher will delegate to PHIMTAT.
        return TikTokMedia(
            source_url=url,
            download_url="",
            content_type="video/mp4",
            caption=video.get("title") or video.get("desc"),
            thumbnail_url=video.get("cover_url"),
            duration=video.get("duration_seconds"),
            play_count=video.get("views") or video.get("playCount"),
            width=video.get("width"),
            height=video.get("height"),
        )

    async def health_check(self) -> bool:
        try:
            async with self._client() as client:
                resp = await client.post(
                    f"{_base_url()}/api/tiktok/video/urls",
                    json={"url": "https://www.tiktok.com/@tiktok", "max_count": 1},
                )
                return resp.status_code == 200
        except Exception:
            return False
