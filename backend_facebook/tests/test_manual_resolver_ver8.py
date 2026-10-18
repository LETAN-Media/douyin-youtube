"""Backend_facebook manual resolver v8 contract regression tests.

Covers the updated ShortcutDerivedFacebookResolver against the Snap Video
v8 shortcut contract (verified live Oct 2026):
- ver from config (PHIMTAT_VER, default 8), ask_format=true & show_menu=true
- medias entries as objects {"url": ..., "ext": ...}
- personal-use terms gate accepted once through red64.php, retried once
- update wall (phimtat ver=7 rollback) -> MANUAL_RESOLVER_UNSUPPORTED
  (fallback-eligible), with required_ver hint preserved
- legacy string medias still pickable
"""

import asyncio
import base64 as b64mod
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


REEL = "https://www.facebook.com/reel/1234567890/"


def _decode_fetch(request: httpx.Request) -> str:
    assert request.url.path == "/snapvideo/red64.php", request.url.path
    wrapped = parse_qs(urlparse(str(request.url)).query)["url"][0]
    return b64mod.b64decode(wrapped).decode("utf-8")


def _provider(payload, calls: list[str] | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        target = _decode_fetch(req)
        if calls is not None:
            calls.append(target)
        if "agree-terms.php" in target:
            return httpx.Response(200, json={"ok": True, "agreed": True,
                                             "lang": "vi", "ver": 8,
                                             "reload": REEL})
        return httpx.Response(200, json=payload)
    return httpx.MockTransport(handler)


def _resolver(transport):
    from app.services.facebook_manual_media import ShortcutDerivedFacebookResolver
    return ShortcutDerivedFacebookResolver(
        "https://provider.example.com/json/snapvideo.json",
        "https://provider.example.com/snapvideo/red64.php",
        "k", 60.0, transport=transport)


@pytest.fixture()
def ver8(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PHIMTAT_VER", "8")


def test_v8_default_params_and_object_medias(ver8):
    calls: list[str] = []
    r = _resolver(_provider({
        "title": "Facebook 9", "source": "facebook",
        "thumbnail": "https://cdn.example.com/t.jpg",
        "medias": {
            "🎬 MP4 HD": {"url": "https://cdn.example.com/hd.mp4", "ext": "mp4"},
            "🎬 MP4 SD": {"url": "https://cdn.example.com/sd.mp4", "ext": "mp4"},
        },
    }, calls))
    out = asyncio.run(r.resolve(REEL))
    assert out.download_url == "https://cdn.example.com/hd.mp4"
    assert out.caption == "Facebook 9"
    assert out.provider == "shortcut"
    assert out.duration is None
    assert calls and all("ver=8" in u for u in calls)
    assert all("ask_format=true" in u for u in calls)
    assert all("show_menu=true" in u for u in calls)
    assert b64mod.b64encode(REEL.encode()).decode() in calls[0]
    assert calls[0].startswith("https://provider.example.com/json/snapvideo.json")


def test_v8_terms_gate_accept_wrapped_and_retry(ver8):
    calls: list[str] = []
    state = {"call": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        target = _decode_fetch(req)
        calls.append(target)
        if "agree-terms.php" in target:
            return httpx.Response(200, json={"ok": True, "agreed": True,
                                             "reload": REEL})
        state["call"] += 1
        if state["call"] == 1:
            return httpx.Response(200, json={
                "title": "⚠️ Phím tắt chỉ dùng cho mục đích cá nhân, không reup",
                "medias": {
                    "✅ Đồng ý": {"url":
                                  "https://api.phimtat.vn/snapvideo/agree-terms.php?sid=x"},
                    "❌ Đóng": {"url": "{{open-link}}"},
                }})
        return httpx.Response(200, json={
            "title": "Real reel",
            "medias": {"🎬 MP4 HD": {"url": "https://cdn.example.com/hd.mp4",
                                     "ext": "mp4"}}})

    out = asyncio.run(_resolver(httpx.MockTransport(handler)).resolve(REEL))
    assert out.download_url == "https://cdn.example.com/hd.mp4"
    assert out.caption == "Real reel"
    assert len(calls) == 3, calls  # api -> agree (wrapped) -> api retry
    assert calls[1].startswith("https://api.phimtat.vn/snapvideo/agree-terms.php")


def test_v8_update_wall_is_fallback_unsupported(ver8):
    from app.services.facebook_manual_media import ManualResolverError

    wall = {
        "labels": ["🚀 Cập nhật phím tắt", "📸 Xem link video"],
        "medias": {
            "🚀 Cập nhật phím tắt": {"url": "https://api.phimtat.vn/snapvideo/"},
            "📸 Xem link video": {"url": "{{open-url}}"},
        },
        "required_version": 8,
        "update": True,
    }
    r = _resolver(_provider(wall))
    with pytest.raises(ManualResolverError) as exc_info:
        asyncio.run(r.resolve(REEL))
    assert exc_info.value.code == "MANUAL_RESOLVER_UNSUPPORTED"
    assert "ver>=8" in str(exc_info.value)


def test_ver7_rollback_uses_config_version(ver8, monkeypatch):
    from app.config import settings

    calls: list[str] = []
    monkeypatch.setattr(settings, "PHIMTAT_VER", "7")
    r = _resolver(_provider({
        "title": "Legacy",
        "medias": {"🎬 MP4 HD": "https://cdn.example.com/legacyhd.mp4"},
    }, calls))
    out = asyncio.run(r.resolve(REEL))
    assert out.download_url == "https://cdn.example.com/legacyhd.mp4"
    assert calls and all("ver=7" in u for u in calls)
    assert all("ask_format=true" in u and "show_menu=true" in u for u in calls)


def test_legacy_string_medias_still_pickable(ver8):
    from app.services.facebook_manual_media import _pick_media_url

    assert _pick_media_url({"🎬 MP4 HD": "https://cdn.example.com/h.mp4"}) == \
        "https://cdn.example.com/h.mp4"
    assert _pick_media_url({"✅ Đồng ý":
                            {"url": "https://api.phimtat.vn/snapvideo/agree-terms.php?sid=x"}}) is None
    assert _pick_media_url({"❌ Đóng": {"url": "{{open-link}}"}}) is None
