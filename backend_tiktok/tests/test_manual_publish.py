"""Regression tests for the manual publish workflow.

Covers:
- manual_publications repository CRUD (create, get, list, status transitions,
  started_at population, media updates, error marking, retry, youtube id)
- source_hash determinism (no query params)
- ManualMediaError codes for unsupported/invalid URLs
- SSRF guard rejects private-IP download URLs
- _to_manual_resolved adapter normalizes TikTokMedia → ManualResolvedMedia
- _do_manual_publish error handling path (ManualMediaError → failed status)

All async tests use asyncio_mode=auto (configured in pytest.ini).
The test DB is a fresh local file per test to avoid Turso.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

TEST_DB_PATH = Path("/tmp/tiktok_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"

os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
os.environ.setdefault("TURSO_DATABASE_URL", TEST_DB_URL)
os.environ.setdefault("TURSO_TOKEN", "test_token")

sys.path.insert(0, str(Path(__file__).parent.parent))


def _reset_db() -> None:
    from app.db import client as db_client

    db_client._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


async def _setup_test_data() -> None:
    from app.db.repositories import pipelines, destinations

    await pipelines.create_pipeline(
        pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline-1",
    )
    await destinations.create_destination(
        destination_id="dest-1", pipeline_id="pipeline-1",
        channel_id="yt-1", channel_name="Test Channel 1",
    )
    await destinations.create_destination(
        destination_id="dest-2", pipeline_id="pipeline-1",
        channel_id="yt-2", channel_name="Test Channel 2",
    )


@pytest.fixture(autouse=True)
def _db():
    _reset_db()
    yield
    _reset_db()


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

async def test_create_and_get_manual_publication():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    pub_id = "mpub_test001"
    created = await manual_publications.create_manual_publication(
        pub_id=pub_id,
        destination_id="dest-1",
        pipeline_id="pipeline-1",
        source_url="https://www.tiktok.com/@user/video/123",
        source_hash="abc123",
        caption="Test caption",
        youtube_title="YT Title",
        youtube_description="YT Desc",
        youtube_hashtags_json='["tag1"]',
        visibility="public",
        publish_at=None,
    )
    assert created["id"] == pub_id
    assert created["status"] == "queued"
    assert created["started_at"] is None
    assert created["youtube_title"] == "YT Title"

    fetched = await manual_publications.get_manual_publication(pub_id)
    assert fetched is not None
    assert fetched["caption"] == "Test caption"
    assert fetched["source_url"] == "https://www.tiktok.com/@user/video/123"
    assert fetched["source_hash"] == "abc123"


async def test_list_manual_publications_filters():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_a", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="h1", visibility="public",
    )
    await manual_publications.create_manual_publication(
        pub_id="mpub_b", destination_id="dest-2", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/2", source_hash="h2", visibility="unlisted",
    )
    await manual_publications.create_manual_publication(
        pub_id="mpub_c", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/3", source_hash="h3", visibility="public",
    )

    dest1_pubs = await manual_publications.list_manual_publications(destination_id="dest-1")
    assert len(dest1_pubs) == 2
    assert {p["id"] for p in dest1_pubs} == {"mpub_a", "mpub_c"}

    public_pubs = await manual_publications.list_manual_publications(status="queued")
    assert len(public_pubs) == 3


async def test_set_manual_pub_status_sets_started_at():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_stat", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="h1", visibility="public",
    )

    # queued → started_at should still be None
    pub = await manual_publications.get_manual_publication("mpub_stat")
    assert pub["started_at"] is None

    # Transition to processing → started_at should be populated
    await manual_publications.set_manual_pub_status("mpub_stat", "processing", stage="resolving_media")
    pub = await manual_publications.get_manual_publication("mpub_stat")
    assert pub["status"] == "processing"
    assert pub["stage"] == "resolving_media"
    assert pub["started_at"] is not None

    # set_manual_pub_started should not overwrite an already-set started_at
    await manual_publications.set_manual_pub_started("mpub_stat")
    pub2 = await manual_publications.get_manual_publication("mpub_stat")
    assert pub2["started_at"] == pub["started_at"]


async def test_set_manual_pub_media_updates_fields():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_media", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="h1",
        youtube_title="Old Title", visibility="public",
    )

    await manual_publications.set_manual_pub_media(
        "mpub_media",
        thumbnail_url="https://example.com/thumb.jpg",
        duration=42.5,
        youtube_title="New Title",
        youtube_description="New Desc",
        youtube_hashtags_json='["a","b"]',
        caption="caption",
    )
    pub = await manual_publications.get_manual_publication("mpub_media")
    assert pub["thumbnail_url"] == "https://example.com/thumb.jpg"
    assert pub["duration"] == 42.5
    assert pub["youtube_title"] == "New Title"
    assert pub["youtube_description"] == "New Desc"
    assert pub["youtube_hashtags_json"] == '["a","b"]'


async def test_mark_manual_pub_error_increments_retry():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_err", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="h1", visibility="public",
    )

    await manual_publications.mark_manual_pub_error("mpub_err", "Some error", retry_increment=True)
    pub = await manual_publications.get_manual_publication("mpub_err")
    assert pub["error"] == "Some error"
    assert pub["retry_count"] == 1

    await manual_publications.mark_manual_pub_error("mpub_err", "Another error", retry_increment=False)
    pub = await manual_publications.get_manual_publication("mpub_err")
    assert pub["error"] == "Another error"
    assert pub["retry_count"] == 1  # not incremented


async def test_set_manual_pub_yt_video():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_yt", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="h1", visibility="public",
    )
    await manual_publications.set_manual_pub_yt_video("mpub_yt", "dQw4w9WgXcQ")
    pub = await manual_publications.get_manual_publication("mpub_yt")
    assert pub["youtube_video_id"] == "dQw4w9WgXcQ"
    assert pub["completed_at"] is not None


async def test_find_manual_pub_by_hash():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_hash1", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="hash_abc", visibility="public",
    )
    found = await manual_publications.find_manual_pub_by_hash("dest-1", "hash_abc")
    assert found is not None
    assert found["id"] == "mpub_hash1"

    not_found = await manual_publications.find_manual_pub_by_hash("dest-1", "missing")
    assert not_found is None


# ---------------------------------------------------------------------------
# Source hash / URL tests
# ---------------------------------------------------------------------------

def test_source_hash_deterministic():
    from app.services.tiktok_media import source_hash

    url = "https://www.tiktok.com/@user/video/12345"
    h1 = source_hash(url)
    h2 = source_hash(url)
    assert h1 == h2
    assert len(h1) == 32


def test_source_hash_different_urls():
    from app.services.tiktok_media import source_hash

    h1 = source_hash("https://www.tiktok.com/@user/video/123")
    h2 = source_hash("https://www.tiktok.com/@user/video/456")
    assert h1 != h2


def test_source_hash_ignores_query_params():
    from app.services.tiktok_media import source_hash

    url1 = "https://www.tiktok.com/@user/video/123?utm_source=share"
    url2 = "https://www.tiktok.com/@user/video/123"
    assert source_hash(url1) == source_hash(url2)


# ---------------------------------------------------------------------------
# Resolver / media error tests
# ---------------------------------------------------------------------------

async def test_resolve_shortcut_media_not_tiktok():
    from app.services.tiktok_media import resolve_shortcut_media, ManualMediaError

    with pytest.raises(ManualMediaError):
        await resolve_shortcut_media("https://facebook.com/reel/123")


async def test_resolve_shortcut_media_not_configured():
    from app.services.tiktok_media import resolve_shortcut_media, ManualMediaError

    os.environ["PHIMTAT_API_BASE_URL"] = ""
    os.environ["PHIMTAT_REDIRECT_URL"] = ""
    try:
        from app.config import settings
        settings.phimtat_api_base_url = ""
        settings.phimtat_redirect_url = ""
        with pytest.raises(ManualMediaError):
            await resolve_shortcut_media("https://www.tiktok.com/@user/video/123")
    finally:
        os.environ.pop("PHIMTAT_API_BASE_URL", None)
        os.environ.pop("PHIMTAT_REDIRECT_URL", None)


async def test_resolve_shortcut_media_api_error():
    from app.services.tiktok_media import resolve_shortcut_media, ManualMediaError

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    os.environ["PHIMTAT_API_BASE_URL"] = "https://api.phimtat.vn/json/snapvideo.json"
    os.environ["PHIMTAT_REDIRECT_URL"] = "https://api.phimtat.vn/snapvideo/red64.php"
    os.environ["PHIMTAT_API_KEY"] = "test_key"
    try:
        from app.config import settings
        settings.phimtat_api_base_url = "https://api.phimtat.vn/json/snapvideo.json"
        settings.phimtat_redirect_url = "https://api.phimtat.vn/snapvideo/red64.php"
        settings.phimtat_api_key = "test_key"
        with pytest.raises(ManualMediaError) as exc_info:
            await resolve_shortcut_media(
                "https://www.tiktok.com/@user/video/123",
                transport=httpx.MockTransport(handler),
            )
        # API key must never appear in error message
        assert "test_key" not in str(exc_info.value)
    finally:
        os.environ.pop("PHIMTAT_API_BASE_URL", None)
        os.environ.pop("PHIMTAT_REDIRECT_URL", None)
        os.environ.pop("PHIMTAT_API_KEY", None)


# ---------------------------------------------------------------------------
# SSRF guard tests
# ---------------------------------------------------------------------------

async def test_ssrf_guard_rejects_private_ip():
    from app.services.tiktok_media import download_media, ManualResolvedMedia, ManualMediaError

    media = ManualResolvedMedia(
        source_url="https://tiktok.com/v/1",
        download_url="http://192.168.1.1/video.mp4",
        content_type="video/mp4",
        caption=None,
        thumbnail_url=None,
    )
    with pytest.raises(ManualMediaError) as exc_info:
        await download_media(media, job_id="test_ssrf_1")
    assert "private" in str(exc_info.value).lower() or "public" in str(exc_info.value).lower()


async def test_ssrf_guard_rejects_loopback():
    from app.services.tiktok_media import download_media, ManualResolvedMedia, ManualMediaError

    media = ManualResolvedMedia(
        source_url="https://tiktok.com/v/1",
        download_url="http://127.0.0.1:8080/video.mp4",
        content_type="video/mp4",
        caption=None,
        thumbnail_url=None,
    )
    with pytest.raises(ManualMediaError) as exc_info:
        await download_media(media, job_id="test_ssrf_2")
    assert "private" in str(exc_info.value).lower() or "public" in str(exc_info.value).lower()


async def test_ssrf_guard_rejects_file_scheme():
    from app.services.tiktok_media import download_media, ManualResolvedMedia, ManualMediaError

    media = ManualResolvedMedia(
        source_url="https://tiktok.com/v/1",
        download_url="file:///etc/passwd",
        content_type="video/mp4",
        caption=None,
        thumbnail_url=None,
    )
    with pytest.raises(ManualMediaError) as exc_info:
        await download_media(media, job_id="test_ssrf_3")
    assert "public" in str(exc_info.value).lower()


async def test_ssrf_guard_rejects_redirect_to_private():
    from app.services.tiktok_media import download_media, ManualResolvedMedia, ManualMediaError

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://10.0.0.1/video.mp4"})
        return httpx.Response(200, content=b"")

    media = ManualResolvedMedia(
        source_url="https://tiktok.com/v/1",
        download_url="https://example.com/start",
        content_type="video/mp4",
        caption=None,
        thumbnail_url=None,
    )
    with pytest.raises(ManualMediaError):
        await download_media(
            media, job_id="test_ssrf_4",
            transport=httpx.MockTransport(handler),
        )


async def test_download_media_validates_content_type():
    from app.services.tiktok_media import download_media, ManualResolvedMedia, ManualMediaError

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html>nope</html>",
        )

    media = ManualResolvedMedia(
        source_url="https://tiktok.com/v/1",
        download_url="https://example.com/video.mp4",
        content_type="video/mp4",
        caption=None,
        thumbnail_url=None,
    )
    with pytest.raises(ManualMediaError):
        await download_media(
            media, job_id="test_ct",
            transport=httpx.MockTransport(handler),
        )


# ---------------------------------------------------------------------------
# _to_manual_resolved adapter test
# ---------------------------------------------------------------------------

def test_to_manual_resolved_adapter():
    from app.services.tiktok_global_publisher import _to_manual_media
    from app.services.tiktok_provider import TikTokMedia

    media = TikTokMedia(
        source_url="https://tiktok.com/v/1",
        download_url="https://cdn.example.com/v.mp4",
        content_type="video/mp4",
        caption="A cool video",
        thumbnail_url="https://example.com/th.jpg",
        duration=30,
    )
    adapted = _to_manual_media(media, "https://tiktok.com/v/1")
    assert adapted.download_url == "https://cdn.example.com/v.mp4"
    assert adapted.caption == "A cool video"
    assert adapted.thumbnail_url == "https://example.com/th.jpg"
    assert adapted.duration == 30
    assert adapted.content_type == "video/mp4"


# ---------------------------------------------------------------------------
# Background task error handling test
# ---------------------------------------------------------------------------

async def test_do_manual_publish_handles_resolution_error():
    from app.db.client import migrate
    from app.db.repositories import manual_publications
    from app.routes.manual import _do_manual_publish

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_fail", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/999", source_hash="fail_hash", visibility="public",
    )

    # Patch both source_provider.resolve_media and resolve_manual_media
    with patch("app.routes.manual.TikTokSourceAPIProvider.resolve_media") as mock_source, \
         patch("app.routes.manual.resolve_manual_media") as mock_resolve:
        from app.services.tiktok_media import ManualMediaError, ManualResolvedMedia

        mock_metadata = ManualResolvedMedia(
            source_url="https://tiktok.com/v/999",
            download_url="",
            content_type="video/mp4",
            caption=None,
            thumbnail_url=None,
        )
        mock_source.return_value = mock_metadata
        mock_resolve.side_effect = ManualMediaError("TIKTOK_MANUAL_UNSUPPORTED", "Not supported")
        await _do_manual_publish("mpub_fail")

    pub = await manual_publications.get_manual_publication("mpub_fail")
    assert pub["status"] == "failed"
    assert pub["error"] is not None
    assert "Not supported" in pub["error"]


async def test_do_manual_publish_handles_generic_error():
    from app.db.client import migrate
    from app.db.repositories import manual_publications
    from app.routes.manual import _do_manual_publish

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_generic_fail", destination_id="dest-1",
        pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/998", source_hash="fail_hash2", visibility="public",
    )

    with patch("app.routes.manual.TikTokSourceAPIProvider.resolve_media") as mock_source, \
         patch("app.routes.manual.resolve_manual_media") as mock_resolve:
        from app.services.tiktok_media import ManualResolvedMedia

        mock_metadata = ManualResolvedMedia(
            source_url="https://tiktok.com/v/998",
            download_url="",
            content_type="video/mp4",
            caption=None,
            thumbnail_url=None,
        )
        mock_source.return_value = mock_metadata
        mock_resolve.side_effect = RuntimeError("unexpected")
        await _do_manual_publish("mpub_generic_fail")

    pub = await manual_publications.get_manual_publication("mpub_generic_fail")
    assert pub["status"] == "failed"
    assert pub["error"] is not None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Source API provider mock tests
# ---------------------------------------------------------------------------

def _mock_videos_response() -> dict:
    return {
        "success": True,
        "platform": "tiktok",
        "username": "testuser",
        "author": "Test User",
        "total_collected": 2,
        "video_urls": [
            "https://www.tiktok.com/@testuser/video/123",
            "https://www.tiktok.com/@testuser/video/456",
        ],
        "videos": [
            {
                "video_id": "123",
                "url": "https://www.tiktok.com/@testuser/video/123",
                "title": "First video",
                "cover_url": "https://example.com/thumb1.jpg",
                "duration_seconds": 30,
                "created_at": 1792508447,
                "likes": 100,
                "comments": 5,
                "shares": 2,
                "views": 1000,
                "bookmarks": 10,
            },
            {
                "video_id": "456",
                "url": "https://www.tiktok.com/@testuser/video/456",
                "title": "Second video",
                "cover_url": "https://example.com/thumb2.jpg",
                "duration_seconds": 45,
                "created_at": 1792508448,
                "likes": 200,
                "comments": 10,
                "shares": 4,
                "views": 2000,
                "bookmarks": 20,
            },
        ],
        "has_more": False,
        "next_cursor": None,
        "error_code": None,
        "message": "Success",
    }


def _mock_video_info_response() -> dict:
    return {
        "success": True,
        "platform": "tiktok",
        "video": {
            "video_id": "123",
            "url": "https://www.tiktok.com/@testuser/video/123",
            "title": "Test video title",
            "cover_url": "https://example.com/thumb.jpg",
            "duration_seconds": 29,
            "created_at": 1792508447,
            "likes": 1293,
            "comments": 82,
            "shares": 18,
            "views": 9279,
            "bookmarks": 41,
        },
        "error_code": None,
        "message": "Lấy thông tin video thành công.",
    }


def _make_mock_provider(handler):
    """Create a TikTokSourceAPIProvider with a mocked HTTP transport."""
    from app.services.tiktok_source_api import TikTokSourceAPIProvider

    provider = TikTokSourceAPIProvider()
    # Override _client to inject mock transport
    def _mock_client(transport=None):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            timeout=30.0,
            headers={"X-API-Key": "test_key", "Accept": "application/json",
                     "Content-Type": "application/json"},
            follow_redirects=True,
        )
    provider._client = _mock_client
    return provider


def _source_env():
    os.environ["TIKTOK_SOURCE_API_BASE_URL"] = "https://tiktok-api-xzze.onrender.com"
    os.environ["TIKTOK_SOURCE_API_KEY"] = "test_key"
    os.environ["TIKTOK_SOURCE_TIMEOUT_SECONDS"] = "30"


def _unset_source_env():
    os.environ.pop("TIKTOK_SOURCE_API_BASE_URL", None)
    os.environ.pop("TIKTOK_SOURCE_API_KEY", None)
    os.environ.pop("TIKTOK_SOURCE_TIMEOUT_SECONDS", None)


async def test_source_api_list_videos():
    _source_env()
    try:
        from app.config import settings
        settings.tiktok_source_api_base_url = "https://tiktok-api-xzze.onrender.com"
        settings.tiktok_source_api_key = "test_key"
        settings.tiktok_source_timeout_seconds = 30.0

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_mock_videos_response())

        provider = _make_mock_provider(handler)
        from app.services.tiktok_provider import TikTokProfile
        profile = TikTokProfile(user_id="123", username="testuser", display_name="Test User")
        reels, cursor = await provider.list_videos(profile, limit=20)
        assert len(reels) == 2
        assert reels[0].video_id == "123"
        assert reels[0].caption == "First video"
        assert reels[0].duration == 30
        assert reels[0].play_count == 1000
        assert reels[0].thumbnail_url == "https://example.com/thumb1.jpg"
        assert reels[1].video_id == "456"
        assert cursor is None
    finally:
        _unset_source_env()


async def test_source_api_resolve_media():
    _source_env()
    try:
        from app.config import settings
        settings.tiktok_source_api_base_url = "https://tiktok-api-xzze.onrender.com"
        settings.tiktok_source_api_key = "test_key"
        settings.tiktok_source_timeout_seconds = 30.0

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_mock_video_info_response())

        provider = _make_mock_provider(handler)
        media = await provider.resolve_media(
            "https://www.tiktok.com/@testuser/video/123"
        )
        assert media.caption == "Test video title"
        assert media.thumbnail_url == "https://example.com/thumb.jpg"
        assert media.duration == 29
        assert media.play_count == 9279
    finally:
        _unset_source_env()


async def test_source_api_auth_error():
    from app.services.tiktok_provider import ProviderError

    _source_env()
    try:
        from app.config import settings
        settings.tiktok_source_api_base_url = "https://tiktok-api-xzze.onrender.com"
        settings.tiktok_source_api_key = "test_key"
        settings.tiktok_source_timeout_seconds = 30.0

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid key"})

        provider = _make_mock_provider(handler)
        with pytest.raises(ProviderError):
            await provider.resolve_profile("testuser")
    finally:
        _unset_source_env()


async def test_source_api_error_hides_api_key():
    """API key must never appear in error messages."""
    from app.services.tiktok_provider import ProviderError

    _source_env()
    os.environ["TIKTOK_SOURCE_API_KEY"] = "secret_my_key_123"
    try:
        from app.config import settings
        settings.tiktok_source_api_base_url = "https://tiktok-api-xzze.onrender.com"
        settings.tiktok_source_api_key = "secret_my_key_123"
        settings.tiktok_source_timeout_seconds = 30.0

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "upstream"})

        provider = _make_mock_provider(handler)
        with pytest.raises(ProviderError) as exc_info:
            await provider.resolve_profile("testuser")
        assert "secret_my_key_123" not in str(exc_info.value)
    finally:
        _unset_source_env()


# ---------------------------------------------------------------------------
# Route endpoint test (duplicate protection)
# ---------------------------------------------------------------------------

async def test_manual_duplicate_protection():
    from app.db.client import migrate
    from app.db.repositories import manual_publications

    await migrate()
    await _setup_test_data()

    await manual_publications.create_manual_publication(
        pub_id="mpub_dup", destination_id="dest-1", pipeline_id="pipeline-1",
        source_url="https://tiktok.com/v/1", source_hash="dup_hash", visibility="public",
        youtube_title="Existing",
    )

    existing = await manual_publications.find_manual_pub_by_hash("dest-1", "dup_hash")
    assert existing is not None
    assert existing["status"] in ("queued", "processing")
    assert existing["id"] == "mpub_dup"
