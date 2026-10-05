"""Shortcut-derived manual resolver (Task 14).

The provider transport is mocked: canned snapvideo JSON (multi-quality +
guide/close chrome), HTTP errors, timeouts. Proves adapter parsing,
guide filtering, typed errors, fallback rules, and a mocked end-to-end
manual publish through the shortcut path (not FastSaver).
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.services.facebook_manual_media import (
    ManualResolverError,
    ShortcutDerivedFacebookResolver,
    _pick_media_url,
    download_manual_media,
    resolve_manual_media,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_manual_resolver_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"

_KEYS = (
    "ADMIN_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    "FACEBOOK_MANUAL_RESOLVER", "MANUAL_FB_PROVIDER_BASE_URL", "MANUAL_FB_PROVIDER_API_KEY",
    "PHIMTAT_API_KEY",
    "FASTSAVER_BASE_URL", "FASTSAVER_API_KEY",
)
_PREV_SETTINGS: dict = {}
_PREV_ENV: dict = {}


def setup_function(_func=None) -> None:
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    for key in _KEYS:
        _PREV_SETTINGS[key] = getattr(settings, key, None)
        _PREV_ENV[key] = os.environ.get(key)
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.FACEBOOK_MANUAL_RESOLVER = "shortcut"
    settings.MANUAL_FB_PROVIDER_BASE_URL = "https://provider.example.com"
    settings.MANUAL_FB_PROVIDER_API_KEY = "test_provider_key"
    settings.FASTSAVER_BASE_URL = "https://fastsaver.example.com"
    settings.FASTSAVER_API_KEY = "test_fs_key"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


def teardown_function(_func=None) -> None:
    client_module._client = None
    for key, value in _PREV_SETTINGS.items():
        setattr(settings, key, value)
    for key, value in _PREV_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()


REEL = "https://www.facebook.com/reel/123456789/"

SHARE_REEL = "https://www.facebook.com/share/v/1K8ZxRDSSy/?mibextid=wwXIfr"

CANNED_MEDIAS = {
    "title": "Funny cats compilation",
    "thumbnail": "https://cdn.example.com/t.jpg",
    "source": "snapvideo",
    "medias": {
        "HD 720p": "https://cdn.example.com/v720.mp4",
        "SD 360p": "https://cdn.example.com/v360.mp4",
        "🖼️ JPG UPDATE GUIDE": "https://cdn.example.com/guide.jpg",
        "❌ Close": "{{open-url}}",
    },
}

GUIDE_ONLY = {
    "title": "Update shortcuts at snapvideo.co",
    "thumbnail": "https://cdn.example.com/g.jpg",
    "medias": {
        "🖼️ JPG UPDATE GUIDE": "https://cdn.example.com/guide.jpg",
        "❌ Close": "{{open-url}}",
    },
}


def provider_transport(payload=None, status=200) -> httpx.MockTransport:
    import base64 as _b64
    from urllib.parse import parse_qs, urlparse

    def handler(req: httpx.Request) -> httpx.Response:
        # Faithful to the shortcut: JSON API fetched wrapped through red64.
        assert req.url.path == "/snapvideo/red64.php", req.url.path
        wrapped = parse_qs(urlparse(str(req.url)).query)["url"][0]
        api_url = _b64.b64decode(wrapped).decode()
        assert "api-key" in api_url and "b64=" in api_url
        return httpx.Response(status, json=payload or {})

    return httpx.MockTransport(handler)


def test_pick_media_url_filters_chrome() -> None:
    assert _pick_media_url(CANNED_MEDIAS["medias"]) == "https://cdn.example.com/v720.mp4"
    assert _pick_media_url(GUIDE_ONLY["medias"]) is None
    assert _pick_media_url({}) is None
    assert _pick_media_url([]) is None


def test_adapter_parses_medias_and_metadata() -> None:
    r = ShortcutDerivedFacebookResolver(
        "https://provider.example.com/json/snapvideo.json",
        "https://provider.example.com/snapvideo/red64.php",
        "k", 60.0,
        transport=provider_transport(CANNED_MEDIAS),
    )
    out = asyncio.run(r.resolve(REEL))
    assert out.download_url == "https://cdn.example.com/v720.mp4"
    assert out.caption == "Funny cats compilation"
    assert out.thumbnail_url == "https://cdn.example.com/t.jpg"
    assert out.provider == "shortcut"
    assert out.source_url == REEL


def test_adapter_guide_only_is_unsupported() -> None:
    r = ShortcutDerivedFacebookResolver(
        "https://provider.example.com/json/snapvideo.json",
        "https://provider.example.com/snapvideo/red64.php",
        "k", 60.0,
        transport=provider_transport(GUIDE_ONLY),
    )
    with pytest.raises(ManualResolverError) as exc:
        asyncio.run(r.resolve(REEL))
    assert exc.value.code == "MANUAL_RESOLVER_UNSUPPORTED"


def test_adapter_401_is_auth_failed() -> None:
    r = ShortcutDerivedFacebookResolver(
        "https://provider.example.com/json/snapvideo.json",
        "https://provider.example.com/snapvideo/red64.php",
        "bad", 60.0,
        transport=provider_transport({}, status=401),
    )
    with pytest.raises(ManualResolverError) as exc:
        asyncio.run(r.resolve(REEL))
    assert exc.value.code == "MANUAL_RESOLVER_AUTH_FAILED"


def test_missing_key_fails_without_http() -> None:
    settings.MANUAL_FB_PROVIDER_API_KEY = ""
    settings.PHIMTAT_API_KEY = ""

    def _boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP must happen without a key")

    with pytest.raises(ManualResolverError) as exc:
        asyncio.run(resolve_manual_media(REEL, transport=httpx.MockTransport(_boom)))
    assert exc.value.code == "MANUAL_RESOLVER_AUTH_FAILED"


def test_phimtat_api_key_alias_accepted() -> None:
    from app.services.facebook_manual_media import _provider_config

    settings.MANUAL_FB_PROVIDER_API_KEY = ""
    settings.PHIMTAT_API_KEY = "alias_key_value"
    api_base, redirect_url, api_key, timeout = _provider_config()
    assert api_base == "https://api.phimtat.vn/json/snapvideo.json"
    assert redirect_url == "https://api.phimtat.vn/snapvideo/red64.php"
    assert api_key == "alias_key_value"


def test_invalid_url_never_touches_provider() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("validation must come first")

    with pytest.raises(ManualResolverError) as exc:
        asyncio.run(resolve_manual_media(
            "https://www.facebook.com/somepage",
            transport=httpx.MockTransport(_boom),
        ))
    assert exc.value.code == "MANUAL_RESOLVER_UNSUPPORTED"


def test_share_links_accepted_as_video_urls() -> None:
    from app.services.facebook_manual_media import is_manual_video_url

    assert is_manual_video_url(SHARE_REEL)
    assert is_manual_video_url("https://www.facebook.com/reel/123/")
    assert is_manual_video_url("https://fb.watch/abc123/")
    assert not is_manual_video_url("https://www.facebook.com/somepage")
    assert not is_manual_video_url("not a url")


def test_share_url_unwrapped_before_provider_call() -> None:
    from app.services.facebook_manual_media import resolve_share_url

    seen: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if "/share/" in str(req.url):
            return httpx.Response(302, headers={"Location": "https://www.facebook.com/reel/999/"})
        return httpx.Response(200, json=CANNED_MEDIAS)

    transport = httpx.MockTransport(handler)
    out = asyncio.run(resolve_share_url(SHARE_REEL, transport=transport))
    assert out == "https://www.facebook.com/reel/999/"
    assert seen and "/share/" in seen[0]


def test_share_unwrap_failure_keeps_original() -> None:
    from app.services.facebook_manual_media import resolve_share_url

    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    out = asyncio.run(resolve_share_url(SHARE_REEL, transport=httpx.MockTransport(_boom)))
    assert out == SHARE_REEL


def test_fallback_on_timeout_never_on_auth() -> None:
    from app.services import facebook_manual_media as mm

    fastsaver_calls: list = []

    def fs_handler(req: httpx.Request) -> httpx.Response:
        fastsaver_calls.append(str(req.url))
        return httpx.Response(200, json={
            "ok": True, "download_url": "https://cdn.example.com/fs.mp4",
            "type": "video", "source": "facebook",
        })

    settings.FACEBOOK_MANUAL_RESOLVER = "shortcut_fastsaver"

    # Timeout path: shortcut transport times out, FastSaver mock serves.
    async def _run_timeout():
        orig = mm.ShortcutDerivedFacebookResolver.resolve

        async def _timeout(self, url):
            raise ManualResolverError("MANUAL_RESOLVER_TIMEOUT", "slow")

        mm.ShortcutDerivedFacebookResolver.resolve = _timeout
        try:
            return await resolve_manual_media(REEL, transport=httpx.MockTransport(fs_handler))
        finally:
            mm.ShortcutDerivedFacebookResolver.resolve = orig

    out = asyncio.run(_run_timeout())
    assert out.provider == "fastsaver"
    assert out.download_url == "https://cdn.example.com/fs.mp4"
    assert fastsaver_calls, "fallback must call FastSaver"

    # Auth path: must NOT fall back.
    async def _run_auth():
        orig = mm.ShortcutDerivedFacebookResolver.resolve

        async def _auth(self, url):
            raise ManualResolverError("MANUAL_RESOLVER_AUTH_FAILED", "bad key")

        mm.ShortcutDerivedFacebookResolver.resolve = _auth
        try:
            await resolve_manual_media(REEL, transport=httpx.MockTransport(fs_handler))
        finally:
            mm.ShortcutDerivedFacebookResolver.resolve = orig

    fastsaver_calls.clear()
    with pytest.raises(ManualResolverError) as exc:
        asyncio.run(_run_auth())
    assert exc.value.code == "MANUAL_RESOLVER_AUTH_FAILED"
    assert not fastsaver_calls, "auth errors must never fall back"


def test_download_guards_content_type_and_cleans_up() -> None:
    from app.services.facebook_media import TMP_ROOT
    from app.services.facebook_manual_media import ManualResolvedMedia

    def bad_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html></html>",
                              headers={"Content-Type": "text/html"})

    media = ManualResolvedMedia(
        source_url=REEL, download_url="https://cdn.example.com/x.mp4",
        caption=None, thumbnail_url=None, duration=None, provider="shortcut",
    )
    with pytest.raises(ManualResolverError) as exc:
        asyncio.run(download_manual_media(
            media, "manual_probe1", transport=httpx.MockTransport(bad_handler)))
    assert exc.value.code == "MANUAL_DOWNLOAD_FAILED"
    assert not list(TMP_ROOT.glob("manual_probe1*"))


def test_shortcut_end_to_end_mocked_publish() -> None:
    from tests.test_manual_publish import (
        fake_youtube_factory, seed_channel,
    )
    from app.db.repositories import manual_publications as manual_repo
    from app.services.facebook_manual_publisher import process_manual_job

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/snapvideo/red64.php":
            return httpx.Response(200, json=CANNED_MEDIAS)
        if "cdn.example.com/v720.mp4" in str(req.url):
            return httpx.Response(200, content=b"1" * 2048,
                                  headers={"Content-Type": "video/mp4"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    pipe_id, did = seed_channel("pl_sr1", "ytd_sr1", "Channel SR")
    settings.FACEBOOK_MANUAL_RESOLVER = "shortcut"

    async def _go():
        row = await manual_repo.create_manual_publication(
            destination_id=did, pipeline_id=pipe_id, source_url=REEL,
            caption=None, thumbnail_url=None, duration=None,
            title="T", description="D", hashtags=[], visibility="public",
            publish_at=None,
        )
        claimed = await manual_repo.claim_next_manual_job()
        assert claimed is not None
        return row["id"]

    mid = asyncio.run(_go())
    job = asyncio.run(manual_repo.get_manual_publication(mid))
    assert job is not None
    result = asyncio.run(process_manual_job(job, transport=transport,
                                            youtube_factory=fake_youtube_factory))
    assert result["result"] == "published", result
    row = asyncio.run(manual_repo.get_manual_publication(mid))
    assert row is not None and row["status"] == "published"


def test_warning_title_filtered_but_media_kept() -> None:
    payload = {
        "title": "⚠️ Phím tắt chỉ dùng cho mục đích cá nhân, không reup",
        "thumbnail": "https://cdn.example.com/t.jpg",
        "source": "facebook",
        "medias": {"🎬 MP4 HD": "https://cdn.example.com/v.mp4"},
    }
    r = ShortcutDerivedFacebookResolver(
        "https://provider.example.com/json/snapvideo.json",
        "https://provider.example.com/snapvideo/red64.php",
        "k", 60.0,
        transport=provider_transport(payload),
    )
    out = asyncio.run(r.resolve(REEL))
    assert out.caption is None
    assert out.thumbnail_url == "https://cdn.example.com/t.jpg"
    assert out.download_url == "https://cdn.example.com/v.mp4"


def test_phimtat_disabled_shortcut_strict() -> None:
    settings.PHIMTAT_ENABLED = False
    try:
        with pytest.raises(ManualResolverError) as exc:
            asyncio.run(resolve_manual_media(REEL))
        assert exc.value.code == "MANUAL_RESOLVER_UNSUPPORTED"
    finally:
        settings.PHIMTAT_ENABLED = True


def test_provider_config_prefers_phimtat_env() -> None:
    from app.services.facebook_manual_media import _provider_config

    settings.PHIMTAT_API_BASE_URL = "https://custom.example.com/json/snapvideo.json"
    settings.PHIMTAT_REDIRECT_URL = "https://custom.example.com/snapvideo/red64.php"
    settings.PHIMTAT_API_KEY = "custom_key"
    settings.PHIMTAT_TIMEOUT_SECONDS = 42
    try:
        api_base, redirect_url, api_key, timeout = _provider_config()
        assert api_base == "https://custom.example.com/json/snapvideo.json"
        assert redirect_url == "https://custom.example.com/snapvideo/red64.php"
        assert api_key == "custom_key"
        assert timeout == 42.0
    finally:
        settings.PHIMTAT_API_BASE_URL = "https://api.phimtat.vn/json/snapvideo.json"
        settings.PHIMTAT_REDIRECT_URL = "https://api.phimtat.vn/snapvideo/red64.php"
        settings.PHIMTAT_API_KEY = "test_provider_key"
        settings.PHIMTAT_TIMEOUT_SECONDS = 60


def test_direct_vs_app_pick_same_media() -> None:
    """Regression §7: the canned proven payload must resolve identically
    through the adapter (thumbnail, caption, MP4 HD pick)."""
    payload = {
        "title": "Facebook 4",
        "source": "facebook",
        "thumbnail": "https://example/thumb.jpg",
        "medias": {"🎬 MP4 HD": "https://example/video.mp4"},
    }
    # Direct reference logic (mirrors the proven client script).
    medias = payload["medias"]
    direct_url = medias.get("🎬 MP4 HD") or next(
        (u for u in medias.values() if isinstance(u, str) and ".mp4" in u), None
    )
    r = ShortcutDerivedFacebookResolver(
        "https://provider.example.com/json/snapvideo.json",
        "https://provider.example.com/snapvideo/red64.php",
        "k", 60.0,
        transport=provider_transport(payload),
    )
    out = asyncio.run(r.resolve(REEL))
    assert out.download_url == direct_url == "https://example/video.mp4"
    assert out.caption == "Facebook 4"
    assert out.thumbnail_url == "https://example/thumb.jpg"
