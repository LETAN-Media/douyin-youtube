"""TikTok provider adapter abstraction.

The Scheduler and scan services depend ONLY on the ``TikTokProvider`` ABC
defined here.  Concrete providers (e.g. TikTok Source API) implement this interface, so
the data-source can be swapped via configuration without touching the Scheduler.

Provider verification contract:
  1. ``resolve_profile`` MUST return a TikTokProfile for a given username,
     or raise ``ProviderError`` / ``ProfileNotFound``.
  2. ``list_videos`` MUST return TikTokReel items with at least ``video_id``,
     ``video_url``, ``thumbnail_url``, ``caption``, ``duration``, and
     ``play_count`` populated, plus an opaque ``next_cursor`` for pagination.
  3. ``resolve_media`` MUST return a TikTokMedia with a working ``download_url``
     and ``content_type`` for playback ingestion.
  4. Transient errors (rate-limit / timeout / 5xx) must be raised as
     ``ProviderError``; validation errors (bad username) as ``ProfileNotFound``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderError(Exception):
    """Transient / recoverable provider error (rate-limit, timeout, 5xx)."""


class ProfileNotFound(Exception):
    """Permanent error: the requested profile/username does not exist."""


@dataclass
class TikTokProfile:
    user_id: str
    username: str
    display_name: str | None = None
    follower_count: int | None = None
    following_count: int | None = None
    is_verified: bool | None = None
    raw: dict | None = None


@dataclass
class TikTokReel:
    video_id: str
    video_url: str
    thumbnail_url: str | None = None
    caption: str | None = None
    duration: int | None = None
    play_count: int | None = None
    create_time: int | None = None
    width: int | None = None
    height: int | None = None
    is_video: bool = True
    raw: dict | None = field(default=None, repr=False)


@dataclass
class TikTokMedia:
    source_url: str
    download_url: str
    content_type: str
    caption: str | None = None
    thumbnail_url: str | None = None
    duration: int | None = None
    play_count: int | None = None
    width: int | None = None
    height: int | None = None


class TikTokProvider(ABC):
    """Abstract adapter every concrete provider must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (for logging/metrics)."""

    @abstractmethod
    async def resolve_profile(self, username: str) -> TikTokProfile:
        """Resolve a TikTok username to a TikTokProfile."""

    @abstractmethod
    async def list_videos(
        self,
        profile: TikTokProfile,
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[TikTokReel], str | None]:
        """Return up to ``limit`` reels and an opaque ``next_cursor``."""

    @abstractmethod
    async def resolve_media(self, url: str) -> TikTokMedia:
        """Resolve a TikTok video URL into a downloadable media descriptor."""

    async def health_check(self) -> bool:
        """Optional liveness probe; default True."""
        return True
