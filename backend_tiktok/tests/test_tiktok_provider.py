"""Tests for TikTok provider adapter — abstract interface compliance."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.tiktok_provider import (
    ProfileNotFound,
    ProviderError,
    TikTokMedia,
    TikTokProfile,
    TikTokProvider,
    TikTokReel,
)
from app.services.tiktok_provider_factory import (
    available_providers,
    get_scan_provider,
    register_provider,
)


class DummyProvider(TikTokProvider):
    """In-memory provider for testing the adapter abstraction."""

    @property
    def name(self) -> str:
        return "dummy"

    async def resolve_profile(self, username: str) -> TikTokProfile:
        if username == "nonexistent":
            raise ProfileNotFound("not found")
        return TikTokProfile(user_id="123", username=username, display_name="Test")

    async def list_videos(self, profile, cursor=None, limit=20):
        if cursor == "next":
            return [], None
        reels = [
            TikTokReel(video_id="v1", video_url="https://tiktok.com/@test/video/1"),
            TikTokReel(video_id="v2", video_url="https://tiktok.com/@test/video/2"),
        ]
        return reels, "next"

    async def resolve_media(self, url: str) -> TikTokMedia:
        return TikTokMedia(
            source_url=url,
            download_url="https://example.com/video.mp4",
            content_type="video/mp4",
        )


def test_provider_abc_enforcement():
    """TikTokProvider is abstract — can't instantiate directly."""
    try:
        TikTokProvider()  # type: ignore[abstract]
        assert False, "Should not instantiate ABC"
    except TypeError:
        pass


def test_dummy_provider_implements_interface():
    """A concrete provider must implement all abstract methods."""
    provider = DummyProvider()
    assert provider.name == "dummy"
    assert isinstance(provider, TikTokProvider)


def test_provider_factory_register_and_select():
    """New providers can be registered without touching the scheduler."""
    register_provider("dummy", DummyProvider)
    available = available_providers()
    assert "dummy" in available


def test_provider_data_classes():
    profile = TikTokProfile(user_id="1", username="test", display_name="Test User")
    assert profile.user_id == "1"
    assert profile.username == "test"

    reel = TikTokReel(video_id="v1", video_url="https://tiktok.com/v/1")
    assert reel.video_id == "v1"

    media = TikTokMedia(
        source_url="https://tiktok.com/v/1",
        download_url="https://x.com/d.mp4",
        content_type="video/mp4",
    )
    assert media.download_url == "https://x.com/d.mp4"


if __name__ == "__main__":
    test_provider_abc_enforcement()
    test_dummy_provider_implements_interface()
    test_provider_factory_register_and_select()
    test_provider_data_classes()
    print("All provider adapter tests passed!")
