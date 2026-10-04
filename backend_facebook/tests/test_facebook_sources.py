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


def test_create_source_username_gives_page_id_required(db) -> None:
    client = make_client()
    pipe = _create_pipeline(client)
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/sources",
        json={"url": "https://www.facebook.com/SomeName/reels/"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "PAGE_ID_REQUIRED"


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
