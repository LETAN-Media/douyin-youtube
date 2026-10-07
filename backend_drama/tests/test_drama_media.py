"""Tests for Drama media resolution and stream download pipeline."""

import base64
import json
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest

from app.services.media.drama_media import (
    AUTH_FAILED,
    DOWNLOAD_FAILED,
    DramaMediaError,
    MEDIA_UNAVAILABLE,
    ResolvedDramaMedia,
    SNAPVIDEO_UNSUPPORTED,
    download_resolved_media,
    probe_media,
    resolve_drama_media,
    resolve_via_phimtat,
)


@pytest.mark.asyncio
async def test_resolve_direct_mp4():
    raw = {"video_url": "https://cdn.example.com/episodes/ep1.mp4"}
    media = await resolve_drama_media(raw_payload=raw)
    assert media.media_type == "DIRECT_MP4"
    assert media.download_host == "cdn.example.com"
    assert media.media_url == "https://cdn.example.com/episodes/ep1.mp4"


@pytest.mark.asyncio
async def test_resolve_hls_stream():
    raw = {"play_url": "https://vod.example.com/stream/ep1.m3u8"}
    media = await resolve_drama_media(raw_payload=raw)
    assert media.media_type == "HLS"
    assert media.download_host == "vod.example.com"
    assert media.media_url == "https://vod.example.com/stream/ep1.m3u8"


@pytest.mark.asyncio
async def test_resolve_webpage_ldjson_hls():
    html = """
    <html>
    <head>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": "Episode 1",
        "contentUrl": "https://v-mps.example.com/vod/sample-ld.m3u8"
    }
    </script>
    </head>
    </html>
    """

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        media = await resolve_drama_media(
            source_url="https://www.reelshort.com/movie/123",
            client=client,
        )
        assert media.media_type == "HLS"
        assert media.download_host == "v-mps.example.com"
        assert "sample-ld.m3u8" in media.media_url


@pytest.mark.asyncio
async def test_phimtat_success_mp4_hd(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "PHIMTAT_ENABLED", True)
    monkeypatch.setattr(settings, "PHIMTAT_API_KEY", "test_phimtat_key")
    monkeypatch.setattr(settings, "PHIMTAT_API_BASE_URL", "https://api.phimtat.vn/json/snapvideo.json")
    monkeypatch.setattr(settings, "PHIMTAT_REDIRECT_URL", "https://api.phimtat.vn/snapvideo/red64.php")

    snap_json = {
        "status": "success",
        "source": "snapvideo",
        "title": "Drama Ep 1",
        "medias": {
            "🎬 MP4 HD": "https://cdn.snapvideo.co/download/ep1_hd.mp4",
            "MP4 SD": "https://cdn.snapvideo.co/download/ep1_sd.mp4",
        },
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/snapvideo/red64.php"
        return httpx.Response(200, json=snap_json)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        media = await resolve_via_phimtat("https://www.example.com/drama/1", client=client)
        assert media.media_type == "PHIMTAT"
        assert media.media_url == "https://cdn.snapvideo.co/download/ep1_hd.mp4"
        assert media.label == "🎬 MP4 HD"
        assert media.download_host == "cdn.snapvideo.co"


@pytest.mark.asyncio
async def test_phimtat_unsupported_drama_url(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "PHIMTAT_ENABLED", True)
    monkeypatch.setattr(settings, "PHIMTAT_API_KEY", "test_phimtat_key")

    err_json = {
        "menu_title": "⚠️ Nền tảng chưa được hỗ trợ",
        "medias": {
            "✨ [QC] Làm nét ảnh bằng AI": "{{open-url}}https://tiemanhai.com/lam-net-anh",
            "❌ Đóng": "{{open-url}}",
        },
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=err_json)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DramaMediaError) as exc:
            await resolve_via_phimtat("https://www.reelshort.com/movie/test", client=client)
        assert exc.value.code == SNAPVIDEO_UNSUPPORTED
        assert "chưa được hỗ trợ" in str(exc.value)


@pytest.mark.asyncio
async def test_media_unavailable_when_no_source(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "PHIMTAT_ENABLED", False)

    with pytest.raises(DramaMediaError) as exc:
        await resolve_drama_media(source_url=None, raw_payload={})
    assert exc.value.code == MEDIA_UNAVAILABLE


def test_download_direct_mp4_stream(tmp_path):
    video_bytes = b"fake mp4 video stream content for testing"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=video_bytes, headers={"Content-Type": "video/mp4"})

    media = ResolvedDramaMedia(
        media_url="https://cdn.example.com/test.mp4",
        media_type="DIRECT_MP4",
        download_host="cdn.example.com",
    )

    out_file = tmp_path / "test_download.mp4"
    real_client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch("httpx.Client") as mock_client_cls:
        # Test download with real chunk writing
        mock_client_cls.return_value.__enter__.return_value = real_client
        res = download_resolved_media(media, out_file)
        assert res.exists()
        assert res.stat().st_size == len(video_bytes)


def test_download_unexpected_content_type(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>error</html>", headers={"Content-Type": "text/html"})

    media = ResolvedDramaMedia(
        media_url="https://cdn.example.com/test.mp4",
        media_type="DIRECT_MP4",
        download_host="cdn.example.com",
    )

    out_file = tmp_path / "bad.mp4"
    real_client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value = real_client
        with pytest.raises(DramaMediaError) as exc:
            download_resolved_media(media, out_file)
        assert exc.value.code == DOWNLOAD_FAILED
        assert "Unexpected Content-Type" in str(exc.value)
        assert not out_file.exists()
