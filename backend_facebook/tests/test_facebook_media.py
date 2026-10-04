import asyncio
from pathlib import Path

import httpx
import pytest

from app.services.facebook_media import (
    FacebookMediaError,
    FacebookMediaResolver,
    MediaResolverConfig,
    ResolvedFacebookMedia,
    cleanup_job_dir,
    job_dir,
    sanitize_job_id,
)

REEL = "https://www.facebook.com/reel/1403287535249535/"
MEDIA_JSON = {
    "ok": True,
    "id": "abc",
    "source": "facebook.com",
    "type": "video",
    "download_url": "https://cdn.example.com/v.mp4?sig=1",
    "thumbnail_url": "https://cdn.example.com/t.jpg",
    "width": None,
    "height": None,
    "duration": 34,
    "caption": "hello",
}


def make_resolver(handler=None, **over) -> tuple[FacebookMediaResolver, list]:
    calls: list = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers.get("X-Api-Key") == "KEY1", "auth header missing"
        return handler(request)

    cfg = MediaResolverConfig(base_url="https://api.example.com", api_key="KEY1", **over)
    return FacebookMediaResolver(cfg, transport=httpx.MockTransport(_handler)), calls


def run(coro):
    return asyncio.run(coro)


# ---------- resolve ----------


def test_resolve_success() -> None:
    r, calls = make_resolver(lambda req: httpx.Response(200, json=MEDIA_JSON))
    m = run(r.resolve(REEL))
    assert isinstance(m, ResolvedFacebookMedia)
    assert m.download_url == MEDIA_JSON["download_url"]
    assert m.media_type == "video" and m.duration == 34.0
    assert m.thumbnail_url and m.caption == "hello"
    assert "url=" in calls[0] and "/fetch" in calls[0]


def test_resolve_rejects_non_facebook() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(200, json=MEDIA_JSON))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve("https://evil.com/facebook.com/x"))
    assert e.value.code == "FASTSAVER_RESOLVE_FAILED"


def test_resolve_ok_false() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(200, json={"ok": False}))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_RESOLVE_FAILED"


def test_resolve_missing_download_url() -> None:
    body = dict(MEDIA_JSON, download_url=None)
    r, _ = make_resolver(lambda req: httpx.Response(200, json=body))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_RESPONSE_INVALID"


def test_resolve_non_video_type() -> None:
    body = dict(MEDIA_JSON, type="image")
    r, _ = make_resolver(lambda req: httpx.Response(200, json=body))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_RESPONSE_INVALID"


def test_resolve_401() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(401, text="nope"))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_AUTH_ERROR"


def test_resolve_429() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(429, text="slow"))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_RATE_LIMITED"


def test_resolve_500() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_UPSTREAM_ERROR"


def test_resolve_timeout() -> None:
    def _h(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    r, _ = make_resolver(_h)
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_TIMEOUT"


def test_resolve_bad_json() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(200, text="<html>nope"))
    with pytest.raises(FacebookMediaError) as e:
        run(r.resolve(REEL))
    assert e.value.code == "FASTSAVER_RESPONSE_INVALID"


def test_no_key_leak_in_errors() -> None:
    r, _ = make_resolver(lambda req: httpx.Response(401, text="bad"))
    try:
        run(r.resolve(REEL))
        raise AssertionError("should raise")
    except FacebookMediaError as e:
        assert "KEY1" not in str(e) and "KEY1" not in e.code


def test_missing_key_fail_fast() -> None:
    with pytest.raises(FacebookMediaError):
        FacebookMediaResolver(MediaResolverConfig(base_url="https://x", api_key=""))


# ---------- download ----------


def media() -> ResolvedFacebookMedia:
    return ResolvedFacebookMedia(
        download_url="https://cdn.example.com/v.mp4",
        source="facebook.com",
        media_type="video",
        thumbnail_url=None,
        duration=None,
        caption=None,
    )


def test_download_stream_success(tmp_path) -> None:
    payload = b"B" * (2 * 1024 * 1024 + 100)  # >2 chunks of 1MiB
    r, _ = make_resolver(
        lambda req: httpx.Response(200, content=payload, headers={"Content-Type": "video/mp4"})
    )
    out = run(r.download_media(media(), "job_abc123", tmp_root=tmp_path))
    assert out == tmp_path / "job_abc123" / "video.mp4"
    assert out.stat().st_size == len(payload)


def test_download_follows_redirect(tmp_path) -> None:
    def _h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v.mp4":
            return httpx.Response(302, headers={"location": "https://cdn.example.com/real.mp4"})
        return httpx.Response(200, content=b"DATA" * 500, headers={"Content-Type": "video/mp4"})

    r, calls = make_resolver(_h)
    out = run(r.download_media(media(), "job_redir", tmp_root=tmp_path))
    assert out.stat().st_size == 2000
    assert len(calls) == 2


def test_download_max_size_declared(tmp_path) -> None:
    r, _ = make_resolver(
        lambda req: httpx.Response(
            200, content=b"x", headers={"Content-Type": "video/mp4", "Content-Length": str(2_000_000_000)}
        )
    )
    with pytest.raises(FacebookMediaError) as e:
        run(r.download_media(media(), "job_big", tmp_root=tmp_path))
    assert e.value.code == "MEDIA_TOO_LARGE"
    assert not (tmp_path / "job_big").exists()


def test_download_max_size_running_count(tmp_path) -> None:
    payload = b"C" * 3000
    r, _ = make_resolver(
        lambda req: httpx.Response(200, content=payload, headers={"Content-Type": "video/mp4"}),
        max_bytes=1000,
    )
    with pytest.raises(FacebookMediaError) as e:
        run(r.download_media(media(), "job_over", tmp_root=tmp_path))
    assert e.value.code == "MEDIA_TOO_LARGE"
    assert not (tmp_path / "job_over").exists()


def test_download_bad_content_type(tmp_path) -> None:
    r, _ = make_resolver(
        lambda req: httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"})
    )
    with pytest.raises(FacebookMediaError) as e:
        run(r.download_media(media(), "job_html", tmp_root=tmp_path))
    assert e.value.code == "MEDIA_BAD_CONTENT_TYPE"
    assert not (tmp_path / "job_html").exists()


def test_download_octet_stream_allowed(tmp_path) -> None:
    r, _ = make_resolver(
        lambda req: httpx.Response(200, content=b"ZZZ", headers={"Content-Type": "application/octet-stream"})
    )
    out = run(r.download_media(media(), "job_oct", tmp_root=tmp_path))
    assert out.stat().st_size == 3


def test_download_interrupted_cleans_up(tmp_path) -> None:
    class Flaky(httpx.AsyncBaseTransport):
        def __init__(self):
            self.n = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.n += 1
            if self.n == 1:
                raise httpx.ConnectError("cut")
            return httpx.Response(200, content=b"x")

    cfg = MediaResolverConfig(base_url="https://api.example.com", api_key="KEY1")
    r = FacebookMediaResolver(cfg, transport=Flaky())
    with pytest.raises(FacebookMediaError) as e:
        run(r.download_media(media(), "job_flaky", tmp_root=tmp_path))
    assert e.value.code in ("MEDIA_DOWNLOAD_FAILED", "FASTSAVER_UPSTREAM_ERROR")
    assert not (tmp_path / "job_flaky").exists()


def test_job_id_sanitized(tmp_path) -> None:
    assert sanitize_job_id("../../etc") == "etc"
    assert sanitize_job_id(None).startswith("job_")
    with pytest.raises(FacebookMediaError):
        sanitize_job_id("...")
    d = job_dir("ok-123_X", tmp_path)
    assert d.parent == tmp_path


def test_cleanup_helper(tmp_path) -> None:
    d = tmp_path / "j1"
    d.mkdir()
    (d / "video.mp4.part").write_bytes(b"partial")
    cleanup_job_dir(d)
    assert not d.exists()
