import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import pipelines, sources
from app.main import create_app
from app.services.facebook_url import (
    InvalidFacebookUrlError,
    PageIdRequiredError,
    parse_facebook_reels_url,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_task3_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}

MAIN_URL = "https://www.facebook.com/people/CM88-Tr%E1%BA%A1m-Ph%C3%A2n-Bi%E1%BB%87t/61592409539824/?sk=reels_tab"


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    # clear wal/shm leftovers
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


def make_client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def db():
    prev_url = os.environ.get("TURSO_DATABASE_URL")
    prev_token = os.environ.get("TURSO_AUTH_TOKEN")
    prev_admin = os.environ.get("ADMIN_TOKEN")
    prev_settings_url = settings.TURSO_DATABASE_URL
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    # restore env/settings so Task 1 + Task 2 tests are unaffected
    if prev_url is not None:
        os.environ["TURSO_DATABASE_URL"] = prev_url
    if prev_token is not None:
        os.environ["TURSO_AUTH_TOKEN"] = prev_token
    if prev_admin is not None:
        os.environ["ADMIN_TOKEN"] = prev_admin
    settings.TURSO_DATABASE_URL = prev_settings_url
    client_module._client = None


# ---------- 1. Main URL parses page_id ----------


def test_main_url_page_id() -> None:
    parsed = parse_facebook_reels_url(MAIN_URL)
    assert parsed["page_id"] == "61592409539824"
    assert parsed["source_type"] == "facebook_reels"


# ---------- 2. /people/NAME/ID/?sk=reels_tab ----------


def test_people_format() -> None:
    parsed = parse_facebook_reels_url(
        "https://www.facebook.com/people/Some-Name/61592409539824/?sk=reels_tab"
    )
    assert parsed["page_id"] == "61592409539824"


# ---------- 3. /ID/reels/ ----------


def test_id_reels_format() -> None:
    parsed = parse_facebook_reels_url("https://www.facebook.com/61592409539824/reels/")
    assert parsed["page_id"] == "61592409539824"
    assert parsed["source_type"] == "facebook_reels"


# ---------- 4. /ID/?sk=reels_tab ----------


def test_id_query_format() -> None:
    parsed = parse_facebook_reels_url("https://www.facebook.com/61592409539824/?sk=reels_tab")
    assert parsed["page_id"] == "61592409539824"


# ---------- 5. m.facebook.com normalize ----------


def test_mobile_host_normalizes() -> None:
    a = parse_facebook_reels_url(
        "https://m.facebook.com/people/Test/61592409539824/?sk=reels_tab&utm_source=x"
    )
    b = parse_facebook_reels_url(
        "https://www.facebook.com/people/Test/61592409539824/?sk=reels_tab"
    )
    assert a["page_id"] == "61592409539824"
    assert a["page_id"] == b["page_id"]
    assert a["normalized_url"] == b["normalized_url"]


# ---------- 6. username URL -> PAGE_ID_REQUIRED ----------


def test_username_url_requires_page_id() -> None:
    with pytest.raises(PageIdRequiredError):
        parse_facebook_reels_url("https://www.facebook.com/SomePageName/reels/")
    with pytest.raises(PageIdRequiredError):
        parse_facebook_reels_url("https://www.facebook.com/SomePageName/?sk=reels_tab")


# ---------- 7-9. rejections ----------


def test_fake_host_rejected() -> None:
    with pytest.raises(InvalidFacebookUrlError):
        parse_facebook_reels_url("https://fakefacebook.com/61592409539824/reels/")


def test_lookalike_subdomain_rejected() -> None:
    with pytest.raises(InvalidFacebookUrlError):
        parse_facebook_reels_url("https://facebook.com.evil.com/61592409539824/reels/")


def test_malformed_rejected() -> None:
    for bad in ("", "not a url", "ftp://facebook.com/61592409539824/reels/", "https://evil.com/facebook.com/123/reels/"):
        with pytest.raises(InvalidFacebookUrlError):
            parse_facebook_reels_url(bad)


# ---------- 10. create pipeline ----------


def test_create_pipeline(db) -> None:
    client = make_client()
    r = client.post("/api/facebook/pipelines", json={"name": "FB Pipe"}, headers=AUTH_HEADERS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "FB Pipe"
    assert body["id"]


def test_create_pipeline_requires_auth(db) -> None:
    client = make_client()
    r = client.post("/api/facebook/pipelines", json={"name": "No Auth"})
    assert r.status_code == 401


# ---------- 11. create valid source ----------


def _create_pipeline(client: TestClient, name: str = "P1") -> dict:
    r = client.post("/api/facebook/pipelines", json={"name": name}, headers=AUTH_HEADERS)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_valid_source(db) -> None:
    client = make_client()
    pipe = _create_pipeline(client)
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": MAIN_URL},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["page_id"] == "61592409539824"
    assert body["pipeline_id"] == pipe["id"]
    assert body["page_name"] is None
    assert body["enabled"] is True
    assert body["initial_scan_completed"] is False
    assert body["crawl_complete"] is False
    assert body["discovered_total"] == 0
    assert body["reels_url"]


def test_create_source_requires_auth(db) -> None:
    client = make_client()
    pipe = _create_pipeline(client)
    r = client.post(f"/api/facebook/pipelines/{pipe['id']}/sources", json={"url": MAIN_URL})
    assert r.status_code == 401


def test_create_source_invalid_url(db) -> None:
    client = make_client()
    pipe = _create_pipeline(client)
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://fakefacebook.com/123/reels/"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_FACEBOOK_URL"


def test_create_source_username_resolves_or_reports(db, monkeypatch) -> None:
    # New contract: username URLs resolve via provider instead of 400.
    # Without network access the resolver must fail with a clear code,
    # never PAGE_ID_REQUIRED.
    import app.services.facebook_url as fb_url
    from app.services.facebook_url import PageResolutionError

    async def fake_fail(raw_url, transport=None):
        raise PageResolutionError("unreachable in test")

    monkeypatch.setattr(fb_url, "resolve_page_id_from_url", fake_fail)
    client = make_client()
    pipe = _create_pipeline(client)
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://www.facebook.com/SomeName/reels/"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "PAGE_UNRESOLVABLE"


def test_create_source_pipeline_not_found(db) -> None:
    client = make_client()
    r = client.post(
        "/api/facebook/pipelines/does-not-exist/sources",
        json={"url": MAIN_URL},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "PIPELINE_NOT_FOUND"


# ---------- 12. duplicate same pipeline -> 409 ----------


def test_duplicate_same_pipeline_409(db) -> None:
    client = make_client()
    pipe = _create_pipeline(client)
    url_variant_a = "https://m.facebook.com/people/Test/61592409539824/?sk=reels_tab&utm_source=x"
    url_variant_b = "https://www.facebook.com/people/Test/61592409539824/?sk=reels_tab"
    r1 = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": url_variant_a},
        headers=AUTH_HEADERS,
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": url_variant_b},
        headers=AUTH_HEADERS,
    )
    assert r2.status_code == 409
    assert r2.json()["error"] == "SOURCE_ALREADY_EXISTS"


def test_duplicate_protected_at_repository_layer(db) -> None:
    async def _run() -> None:
        await pipelines.create_pipeline(pipeline_id="p1", name="P1", slug="p1")
        await sources.create_source(
            source_id="s1", pipeline_id="p1", page_id="61592409539824", page_name=None,
            reels_url="https://www.facebook.com/61592409539824/reels/",
        )
        with pytest.raises(sources.DuplicateSourceError):
            await sources.create_source(
                source_id="s2", pipeline_id="p1", page_id="61592409539824", page_name=None,
            )

    asyncio.run(_run())


# ---------- 13. same page_id in different pipeline allowed ----------


def test_same_page_other_pipeline_allowed(db) -> None:
    client = make_client()
    p1 = _create_pipeline(client, "PA")
    p2 = _create_pipeline(client, "PB")
    r1 = client.post(
        f"/api/facebook/pipelines/{p1['id']}/sources",
        json={"url": MAIN_URL},
        headers=AUTH_HEADERS,
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        f"/api/facebook/pipelines/{p2['id']}/sources",
        json={"url": MAIN_URL},
        headers=AUTH_HEADERS,
    )
    assert r2.status_code == 201, r2.text


# ---------- 14/15. GET pipelines / sources ----------


def test_get_pipelines_and_sources(db) -> None:
    client = make_client()
    pipe = _create_pipeline(client, "List Pipe")
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": MAIN_URL},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 201, r.text

    gp = client.get("/api/facebook/pipelines")
    assert gp.status_code == 200
    assert any(p["id"] == pipe["id"] for p in gp.json())

    gs = client.get(f"/api/facebook/pipelines/{pipe['id']}/sources")
    assert gs.status_code == 200
    items = gs.json()
    assert len(items) == 1
    assert items[0]["page_id"] == "61592409539824"

    one = client.get(f"/api/facebook/pipelines/{pipe['id']}")
    assert one.status_code == 200

    single = client.get(f"/api/facebook/sources/{items[0]['id']}")
    assert single.status_code == 200
    assert single.json()["page_id"] == "61592409539824"


# ---------- 16. health still passes ----------


def test_health(db) -> None:
    client = make_client()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "backend-facebook", "version": "1.0.0"}


# ---------- source update (enable/disable) + delete ----------


def _make_pipeline_with_source(db, suffix: str = "upd") -> tuple[str, str]:
    async def _go():
        pipe = await pipelines.create_pipeline(
            pipeline_id=f"pl_{suffix}", name=f"P {suffix}", slug=f"pl-{suffix}"
        )
        src = await sources.create_source(
            source_id=f"src_{suffix}", pipeline_id=pipe["id"],
            page_id=f"page_{suffix}", reels_url=f"https://www.facebook.com/{suffix}/reels/",
        )
        return pipe["id"], src["id"]

    return asyncio.run(_go())


def test_update_source_enabled_toggle(db) -> None:
    pipe_id, src_id = _make_pipeline_with_source(db, "tgl")
    client = make_client()
    off = client.patch(
        f"/api/facebook/sources/{src_id}", headers=AUTH_HEADERS, json={"enabled": False}
    )
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    on = client.patch(
        f"/api/facebook/sources/{src_id}", headers=AUTH_HEADERS, json={"enabled": True}
    )
    assert on.status_code == 200, on.text
    assert on.json()["enabled"] is True
    missing = client.patch(
        "/api/facebook/sources/src_nope", headers=AUTH_HEADERS, json={"enabled": True}
    )
    assert missing.status_code == 404, missing.text


def test_delete_empty_source(db) -> None:
    _pipe_id, src_id = _make_pipeline_with_source(db, "delempty")
    client = make_client()
    r = client.delete(f"/api/facebook/sources/{src_id}", headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    again = client.delete(f"/api/facebook/sources/{src_id}", headers=AUTH_HEADERS)
    assert again.status_code == 404, again.text


def test_delete_source_with_reels_is_409(db) -> None:
    from app.db.repositories import reels

    pipe_id, src_id = _make_pipeline_with_source(db, "delbusy")

    async def _seed_reel():
        await reels.insert_reel_if_new(
            reel_db_id=f"{src_id}_r1", source_id=src_id, reel_id="r1",
        )

    asyncio.run(_seed_reel())
    client = make_client()
    r = client.delete(f"/api/facebook/sources/{src_id}", headers=AUTH_HEADERS)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "SOURCE_HAS_VIDEOS"
    # Source still there and toggle still works.
    assert asyncio.run(sources.get_source(src_id)) is not None


# ---------- 20. username URL resolution ----------

BEEK_HTML = (
    '<html><head><title>Beeknoee AI Reels</title></head><body>'
    '"sectionToken":"eA==","userID":"100064159950207",'
    '"userVanity":"beeknoee","viewerID":null}'
    "</body></html>"
)


def test_extract_username_candidate() -> None:
    from app.services.facebook_url import extract_username_candidate

    assert extract_username_candidate("https://www.facebook.com/beeknoee/reels/") == "beeknoee"
    assert extract_username_candidate("https://www.facebook.com/beeknoee/") == "beeknoee"
    assert extract_username_candidate("https://fb.watch/abc123/") is None
    assert extract_username_candidate("https://www.facebook.com/share/abc123/") is None
    assert extract_username_candidate("https://facebook.com/people/foo/123/") is None
    assert extract_username_candidate("https://www.facebook.com/61592409539824/reels/") is None
    assert extract_username_candidate("https://www.facebook.com/reel/123/") is None
    assert extract_username_candidate("https://example.com/beeknoee/") is None
    assert extract_username_candidate("not a url") is None
    assert extract_username_candidate(None) is None


def test_extract_page_id_from_html_verified_pairing() -> None:
    from app.services.facebook_url import extract_page_id_from_html

    assert extract_page_id_from_html(BEEK_HTML, "beeknoee") == "100064159950207"
    assert extract_page_id_from_html(BEEK_HTML, "BeekNoee") == "100064159950207"
    # Vanity mismatch: never trust a stray ID.
    assert extract_page_id_from_html(BEEK_HTML, "someoneelse") is None
    assert extract_page_id_from_html("", "beeknoee") is None
    assert extract_page_id_from_html("<html></html>", "beeknoee") is None


def test_resolve_page_id_mock_transport() -> None:
    import httpx

    from app.services.facebook_url import resolve_page_id_from_url

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=BEEK_HTML)

    async def _go():
        return await resolve_page_id_from_url(
            "https://www.facebook.com/beeknoee/reels/",
            transport=httpx.MockTransport(handler),
        )

    out = asyncio.run(_go())
    assert out["page_id"] == "100064159950207"
    assert out["username"] == "beeknoee"
    assert out["normalized_url"] == "https://www.facebook.com/100064159950207/reels/"


def test_resolve_page_id_wrong_vanity_fails() -> None:
    import httpx

    from app.services.facebook_url import PageResolutionError, resolve_page_id_from_url

    html = BEEK_HTML.replace('"userVanity":"beeknoee"', '"userVanity":"otherpage"')

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    async def _go():
        await resolve_page_id_from_url(
            "https://www.facebook.com/beeknoee/reels/",
            transport=httpx.MockTransport(handler),
        )

    try:
        asyncio.run(_go())
        raise AssertionError("expected PageResolutionError")
    except PageResolutionError:
        pass


def test_resolve_share_redirect_follows() -> None:
    import httpx

    from app.services.facebook_url import resolve_page_id_from_url

    def handler(req: httpx.Request) -> httpx.Response:
        if "fb.watch" in str(req.url):
            return httpx.Response(
                302, headers={"location": "https://www.facebook.com/beeknoee/reels/"}
            )
        return httpx.Response(200, text=BEEK_HTML)

    async def _go():
        return await resolve_page_id_from_url(
            "https://fb.watch/abc123/",
            transport=httpx.MockTransport(handler),
        )

    out = asyncio.run(_go())
    assert out["page_id"] == "100064159950207"


def test_resolve_http_error_fails() -> None:
    import httpx

    from app.services.facebook_url import PageResolutionError, resolve_page_id_from_url

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async def _go():
        await resolve_page_id_from_url(
            "https://www.facebook.com/ghostpage/reels/",
            transport=httpx.MockTransport(handler),
        )

    try:
        asyncio.run(_go())
        raise AssertionError("expected PageResolutionError")
    except PageResolutionError:
        pass


def _patch_resolver(monkeypatch, page_id="100064159950207"):
    import app.services.facebook_url as fb_url

    async def fake_resolve(raw_url, transport=None):
        assert transport is None  # route never injects test transports
        return {
            "page_id": page_id,
            "username": "beeknoee",
            "normalized_url": f"https://www.facebook.com/{page_id}/reels/",
        }

    monkeypatch.setattr(fb_url, "resolve_page_id_from_url", fake_resolve)


def test_create_source_username_url(db, monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    client = make_client()
    pipe = _create_pipeline(client, name="DEVAI VN")
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://www.facebook.com/beeknoee/reels/"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["page_id"] == "100064159950207"
    assert body["source_url"] == "https://www.facebook.com/beeknoee/reels/"
    assert body["reels_url"] == "https://www.facebook.com/100064159950207/reels/"


def test_create_source_duplicate_across_url_forms(db, monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    client = make_client()
    pipe = _create_pipeline(client, name="DEVAI VN 2")
    first = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://www.facebook.com/beeknoee/"},
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://www.facebook.com/100064159950207/reels/"},
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"] == "SOURCE_ALREADY_EXISTS"


def test_create_source_unresolvable_username(db, monkeypatch) -> None:
    import app.services.facebook_url as fb_url
    from app.services.facebook_url import PageResolutionError

    async def fake_fail(raw_url, transport=None):
        raise PageResolutionError("Không xác định được Page ID cho 'ghostpage'.")

    monkeypatch.setattr(fb_url, "resolve_page_id_from_url", fake_fail)
    client = make_client()
    pipe = _create_pipeline(client, name="DEVAI VN 3")
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://www.facebook.com/ghostpage/reels/"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "PAGE_UNRESOLVABLE"


def test_migration_18_source_url_column(db) -> None:
    import asyncio

    import app.db.client as client_module

    async def _cols():
        rows = await client_module._client.execute(
            "PRAGMA table_info(facebook_sources)"
        )
        return [r[1] for r in rows.rows]

    cols = asyncio.run(_cols())
    assert "source_url" in cols
