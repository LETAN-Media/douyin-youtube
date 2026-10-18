"""Snap Video shortcut v8 contract regression tests (Oct 2026).

Covers:
- ver=8 + object medias values {"url": ..., "ext": ...}
- ver=8 params ask_format=true&show_menu=true&skip_update=false
- personal-use terms gate: accept wrapped via red64 then retry once
- update wall (ver=7 rollback) -> SNAPVIDEO_UNRESOLVABLE (no fallback lies)
- legacy string-value medias (v7 shape) still parse
- prefer_sd selects the SD stream
- the provider API key never appears in error messages
"""

import asyncio
import base64 as b64mod
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


REEL = "https://www.facebook.com/reel/1234567890/"


def _decode_fetch(request: httpx.Request) -> str:
    assert request.url.path == "/snapvideo/red64.php", request.url.path
    wrapped = parse_qs(urlparse(str(request.url)).query)["url"][0]
    return b64mod.b64decode(wrapped).decode()


@pytest.fixture()
def phimtat(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PHIMTAT_ENABLED", True)
    monkeypatch.setattr(settings, "PHIMTAT_API_KEY", "phimtat_test_key")
    monkeypatch.setattr(settings, "PHIMTAT_API_BASE_URL",
                        "https://api.phimtat.vn/json/snapvideo.json")
    monkeypatch.setattr(settings, "PHIMTAT_REDIRECT_URL",
                        "https://api.phimtat.vn/snapvideo/red64.php")
    monkeypatch.setattr(settings, "PHIMTAT_VER", "8")
    monkeypatch.setattr(settings, "PHIMTAT_PREFER_SD", False)
    # Keep fallback out of the picture unless a test opts in explicitly.
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_BASE_URL", "")
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_API_KEY", "")
    yield settings


def _v8_medias(sd_first: bool = False) -> dict:
    hd = {"url": "https://cdn.example.com/hd.mp4", "ext": "mp4"}
    sd = {"url": "https://cdn.example.com/sd.mp4", "ext": "mp4"}
    return ({"🎬 MP4 SD": sd, "🎬 MP4 HD": hd} if sd_first
            else {"🎬 MP4 HD": hd, "🎬 MP4 SD": sd})


def test_ver8_object_medias_pick_hd(phimtat):
    from app.services import snapvideo as sv

    api_urls, uas = [], []

    def handler(req: httpx.Request) -> httpx.Response:
        uas.append(req.headers.get("user-agent", ""))
        api_urls.append(_decode_fetch(req))
        return httpx.Response(200, json={
            "title": "Some reel", "thumbnail": "https://cdn.example.com/t.jpg",
            "source": "snapvideo", "medias": _v8_medias()})

    out = asyncio.run(sv.resolve_media_url(REEL, transport=httpx.MockTransport(handler),
                                           prefer_sd=False))
    assert out["media_url"] == "https://cdn.example.com/hd.mp4"
    assert out["provider"] == "phimtat"
    assert out["title"] == "Some reel"
    assert out["duration"] is None
    assert api_urls and all("ver=8" in u for u in api_urls)
    assert all("ask_format=true" in u for u in api_urls)
    assert all("show_menu=true" in u for u in api_urls)
    assert all("skip_update=false" in u for u in api_urls)
    assert all(b64mod.b64encode(REEL.encode()).decode() in u for u in api_urls)
    assert all(u.startswith("https://api.phimtat.vn/json/snapvideo.json")
               for u in api_urls)
    assert uas and all("Chrome/150" in ua for ua in uas)


def test_ver8_prefer_sd(phimtat):
    from app.services import snapvideo as sv

    def handler(req: httpx.Request) -> httpx.Response:
        _decode_fetch(req)
        return httpx.Response(200, json={"title": "t", "medias": _v8_medias()})

    out = asyncio.run(sv.resolve_media_url(
        REEL, transport=httpx.MockTransport(handler), prefer_sd=True))
    assert out["media_url"] == "https://cdn.example.com/sd.mp4"


def test_ver8_prefer_sd_even_when_sd_listed_last(phimtat):
    from app.services import snapvideo as sv

    def handler(req: httpx.Request) -> httpx.Response:
        _decode_fetch(req)
        return httpx.Response(200, json={"title": "t", "medias": _v8_medias()})

    out = asyncio.run(sv.resolve_media_url(
        REEL, transport=httpx.MockTransport(handler), prefer_sd=True))
    assert out["media_url"] == "https://cdn.example.com/sd.mp4"


def test_prefer_sd_settings_default_used_when_not_passed(phimtat):
    from app.config import settings as s
    from app.services import snapvideo as sv

    s.PHIMTAT_PREFER_SD = True

    def handler(req: httpx.Request) -> httpx.Response:
        _decode_fetch(req)
        return httpx.Response(200, json={"title": "t", "medias": _v8_medias()})

    out = asyncio.run(sv.resolve_media_url(REEL, transport=httpx.MockTransport(handler)))
    assert out["media_url"] == "https://cdn.example.com/sd.mp4"
    s.PHIMTAT_PREFER_SD = False
    out = asyncio.run(sv.resolve_media_url(REEL, transport=httpx.MockTransport(handler)))
    assert out["media_url"] == "https://cdn.example.com/hd.mp4"


def test_terms_gate_accept_wrapped_retry_once(phimtat):
    from app.services import snapvideo as sv

    stage = {"n": 0}
    calls: list[str] = []

    agree_url = "https://api.phimtat.vn/snapvideo/agree-terms.php?sid=grok"

    def handler(req: httpx.Request) -> httpx.Response:
        target = _decode_fetch(req)
        calls.append(target)
        if "agree-terms.php" in target:
            # The consent GET must also be wrapped through red64.php.
            return httpx.Response(
                200, json={"ok": True, "agreed": True, "lang": "vi",
                           "ver": 8, "reload": REEL})
        stage["n"] += 1
        if stage["n"] == 1:
            return httpx.Response(200, json={
                "title": "⚠️ Chỉ dùng cá nhân. Không reup.",
                "medias": {"✅ Đồng ý": {"url": agree_url},
                           "❌ Đóng": {"url": "{{open-link}}"}}})
        # Second call after consent -> real media, no second terms gate.
        return httpx.Response(200, json={"title": "Real video",
                                         "medias": _v8_medias()})

    out = asyncio.run(sv.resolve_media_url(REEL, transport=httpx.MockTransport(handler)))
    assert out["media_url"] == "https://cdn.example.com/hd.mp4"
    assert out["title"] == "Real video"
    assert len(calls) == 3, calls  # api -> agree (wrapped) -> api retry
    assert calls[1].startswith("https://api.phimtat.vn/snapvideo/agree-terms.php")


def test_terms_gate_never_leaks_api_key(phimtat):
    from app.services import snapvideo as sv

    def handler(req: httpx.Request) -> httpx.Response:
        _decode_fetch(req)
        return httpx.Response(403, json={"error": "bad key"})
    with pytest.raises(sv.SnapVideoError) as exc:
        asyncio.run(sv.resolve_media_url(REEL,
                                         transport=httpx.MockTransport(handler)))
    assert "phimtat_test_key" not in str(exc.value)


def test_update_wall_ver7_rollback_unresolvable(phimtat):
    from app.services import snapvideo as sv

    monkey_wall = {
        "labels": ["🚀 Cập nhật phím tắt", "📸 Xem link video"],
        "medias": {
            "🚀 Cập nhật phím tắt": {"url": "https://api.phimtat.vn/snapvideo/"},
            "📸 Xem link video": {"url": "{{open-url}}"},
        },
        "required_version": 8,
        "update": True,
        "menu_done_title": "Quay trở lại update phím tắt SnapVideo mới nhất",
        "menu_title": "Update shortcuts",
    }
    phimtat.PHIMTAT_VER = "7"

    def handler(req: httpx.Request) -> httpx.Response:
        _decode_fetch(req)
        return httpx.Response(200, json=monkey_wall)

    with pytest.raises(sv.SnapVideoError) as exc:
        asyncio.run(sv.resolve_media_url(REEL, transport=httpx.MockTransport(handler)))
    assert exc.value.code == sv.UNRESOLVABLE
    assert "ver>=8" in str(exc.value)


def test_legacy_v7_string_values_still_parse(phimtat):
    from app.services import snapvideo as sv

    phimtat.PHIMTAT_VER = "7"

    def handler(req: httpx.Request) -> httpx.Response:
        target = _decode_fetch(req)
        assert "ver=7&" in target
        return httpx.Response(200, json={
            "title": "Legacy",
            "medias": {"🎬 MP4 HD": "https://cdn.example.com/legacyhd.mp4",
                       "🎬 MP4 SD": "https://cdn.example.com/legacysd.mp4"}})

    out = asyncio.run(sv.resolve_media_url(
        REEL, transport=httpx.MockTransport(handler), prefer_sd=False))
    assert out["media_url"] == "https://cdn.example.com/legacyhd.mp4"


def test_pick_media_url_object_and_string_variants():
    from app.services import snapvideo as sv

    assert sv._pick_media_url(_v8_medias()) == "https://cdn.example.com/hd.mp4"
    assert sv._pick_media_url(_v8_medias(), prefer_sd=True) == \
        "https://cdn.example.com/sd.mp4"
    assert sv._pick_media_url({"🖼️ Hướng dẫn":
                               {"url": "https://cdn.example.com/g.jpg"}}) is None
    assert sv._pick_media_url({"❌ Đóng": {"url": "{{open-link}}"}}) is None
    assert sv._pick_media_url(None) is None
    assert sv._pick_media_url({"x": {"url": ""}}) is None
    # Consent placeholder must never be picked as a media URL.
    assert sv._pick_media_url({
        "✅ Đồng ý": {"url": "https://api.phimtat.vn/snapvideo/agree-terms.php?sid=x"},
    }) is None
