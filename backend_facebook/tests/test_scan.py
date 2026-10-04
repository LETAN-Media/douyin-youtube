import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
import app.routes.scan as scan_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import pipelines, reels, scan_runs, sources
from app.main import create_app
from app.routes.scan import run_initial_scan
from app.services.facebook_rapidapi import (
    FacebookRapidApiClient,
    RapidApiConfig,
    RapidApiError,
    normalize_reel,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_task4_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}
PAGE_ID = "61592409539824"
RPID = "RPID_TEST_123"


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.RAPIDAPI_KEY = "test_key_1"
    settings.RAPIDAPI_KEY_FALLBACK = None
    settings.FACEBOOK_RAPIDAPI_HOST = "test-host"
    settings.FACEBOOK_RAPIDAPI_BASE_URL = "https://test-host"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


@pytest.fixture()
def db():
    prev = {
        "url": os.environ.get("TURSO_DATABASE_URL"),
        "token": os.environ.get("TURSO_AUTH_TOKEN"),
        "admin": os.environ.get("ADMIN_TOKEN"),
        "settings_url": settings.TURSO_DATABASE_URL,
        "key": settings.RAPIDAPI_KEY,
        "fallback": settings.RAPIDAPI_KEY_FALLBACK,
        "host": settings.FACEBOOK_RAPIDAPI_HOST,
        "base": settings.FACEBOOK_RAPIDAPI_BASE_URL,
        "max_pages": settings.FACEBOOK_RAPIDAPI_MAX_PAGES,
        "max_reels": settings.FACEBOOK_RAPIDAPI_MAX_REELS,
    }
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev["url"] is not None:
        os.environ["TURSO_DATABASE_URL"] = prev["url"]
    if prev["token"] is not None:
        os.environ["TURSO_AUTH_TOKEN"] = prev["token"]
    if prev["admin"] is not None:
        os.environ["ADMIN_TOKEN"] = prev["admin"]
    settings.TURSO_DATABASE_URL = prev["settings_url"]
    settings.RAPIDAPI_KEY = prev["key"]
    settings.RAPIDAPI_KEY_FALLBACK = prev["fallback"]
    settings.FACEBOOK_RAPIDAPI_HOST = prev["host"]
    settings.FACEBOOK_RAPIDAPI_BASE_URL = prev["base"]
    settings.FACEBOOK_RAPIDAPI_MAX_PAGES = prev["max_pages"]
    settings.FACEBOOK_RAPIDAPI_MAX_REELS = prev["max_reels"]
    client_module._client = None


@pytest.fixture()
def no_sleep(monkeypatch):
    async def _fast(_s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast)


def make_source(suffix: str = "a") -> dict:
    async def _run() -> dict:
        try:
            await pipelines.create_pipeline(
                pipeline_id=f"p{suffix}", name=f"P{suffix}", slug=f"p{suffix}"
            )
        except Exception:
            pass
        return await sources.create_source(
            source_id=f"src{suffix}",
            pipeline_id=f"p{suffix}",
            page_id=PAGE_ID,
            page_name=None,
            reels_url=f"https://www.facebook.com/{PAGE_ID}/reels/",
        )

    return asyncio.run(_run())


def make_run(source_id: str, run_id: str = "scan1") -> dict:
    async def _run() -> dict:
        return await scan_runs.create_scan_run(
            scan_run_id=run_id, source_id=source_id, status="queued"
        )

    return asyncio.run(_run())


def reel_item(vid: str, **over) -> dict:
    item = {
        "type": "reel",
        "video_id": vid,
        "post_id": f"post_{vid}",
        "url": f"https://www.facebook.com/reel/{vid}/",
        "description": f"caption {vid}",
        "timestamp": 1791039716,
        "thumbnail_uri": f"https://example.com/t/{vid}.jpg",
    }
    item.update(over)
    return item


def provider_transport(
    pages: dict[str | None, tuple[int, object]] | None = None,
    *,
    details_ok: bool = True,
    reels_page_id: str = RPID,
    on_request: list | None = None,
) -> httpx.MockTransport:
    pages = pages or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request.append(str(request.url))
        path = request.url.path
        if path == "/page/details":
            if not details_ok:
                return httpx.Response(200, json={"results": {"name": "x"}})
            return httpx.Response(200, json={"results": {"reels_page_id": reels_page_id}})
        if path == "/page/reels":
            cursor = request.url.params.get("cursor")
            if cursor in pages:
                code, body = pages[cursor]
            elif None in pages and cursor is None:
                code, body = pages[None]
            else:
                return httpx.Response(404, json={"detail": "no mock page"})
            if isinstance(body, Exception):
                raise body
            if isinstance(body, str):
                return httpx.Response(code, text=body)
            return httpx.Response(code, json=body)
        return httpx.Response(404, json={"detail": "unknown path"})

    return httpx.MockTransport(handler)


def make_client() -> FacebookRapidApiClient:
    return FacebookRapidApiClient(
        RapidApiConfig(
            base_url="https://test-host", host="test-host", api_keys=["k1"],
            timeout=5.0, max_retries=2,
        )
    )


# ---------- 1. parse provider response ----------


def test_parse_response(db, no_sleep) -> None:
    t = provider_transport({None: (200, {"results": [reel_item("111")], "cursor": None})})
    cli = make_client()
    out = asyncio.run(cli.list_reels(PAGE_ID, transport=t))
    assert len(out.items) == 1 and out.has_more is False
    rid = asyncio.run(cli.resolve_reels_page_id("https://x/", transport=t))
    assert rid == RPID


# ---------- 2/3. normalize ----------


def test_normalize_reel() -> None:
    item = normalize_reel(reel_item("1403287535249535"))
    assert item is not None
    assert item["reel_id"] == "1403287535249535"
    assert item["reel_url"] == "https://www.facebook.com/reel/1403287535249535/"
    assert item["caption"] == "caption 1403287535249535"
    assert item["thumbnail_url"] == "https://example.com/t/1403287535249535.jpg"
    assert item["source_published_at"] is not None and "2026" in item["source_published_at"]
    assert normalize_reel({"url": "https://x/"}) is None
    assert normalize_reel("nope") is None
    assert normalize_reel(reel_item("1", timestamp=None))["source_published_at"] is None


# ---------- 4. pagination ----------


def test_pagination_two_pages(db, no_sleep) -> None:
    src = make_source("a")
    make_run(src["id"])
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("101"), reel_item("102")], "cursor": "C2"}),
            "C2": (200, {"results": [reel_item("103")], "cursor": None}),
        }
    )
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["status"] == "completed"
    assert run["discovered_count"] == 3 and run["inserted_count"] == 3
    assert run["crawl_complete"] is True


# ---------- 5. repeated cursor protection ----------


def test_repeated_cursor_stops(db, no_sleep) -> None:
    src = make_source("b")
    make_run(src["id"])
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("201")], "cursor": "LOOP"}),
            "LOOP": (200, {"results": [reel_item("202")], "cursor": "LOOP"}),
        }
    )
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["stop_reason"] == "SAFETY_LIMIT"
    assert run["crawl_complete"] is False
    assert run["discovered_count"] == 2  # loop cut, no infinite fetch


# ---------- 6. duplicate items ----------


def test_duplicate_items_deduped(db, no_sleep) -> None:
    src = make_source("c")
    make_run(src["id"])
    t = provider_transport(
        {None: (200, {"results": [reel_item("301"), reel_item("301"), reel_item("302")], "cursor": None})}
    )
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["discovered_count"] == 2 and run["inserted_count"] == 2


# ---------- 7/8. insert + existing ----------


def test_insert_and_existing(db, no_sleep) -> None:
    src = make_source("d")
    asyncio.run(
        reels.insert_reel_if_new(
            reel_db_id=f"{src['id']}_401", source_id=src["id"], reel_id="401"
        )
    )
    make_run(src["id"])
    t = provider_transport(
        {None: (200, {"results": [reel_item("401"), reel_item("402")], "cursor": None})}
    )
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["discovered_count"] == 2
    assert run["inserted_count"] == 1 and run["existing_count"] == 1


# ---------- 9. published kept ----------


def test_published_not_reset(db, no_sleep) -> None:
    src = make_source("e")
    asyncio.run(
        reels.insert_reel_if_new(
            reel_db_id=f"{src['id']}_501", source_id=src["id"], reel_id="501"
        )
    )
    asyncio.run(reels.update_reel_status(f"{src['id']}_501", "published"))
    make_run(src["id"])
    t = provider_transport({None: (200, {"results": [reel_item("501")], "cursor": None})})
    asyncio.run(run_initial_scan("scan1", transport=t))
    row = asyncio.run(reels.get_reel(f"{src['id']}_501"))
    assert row["status"] == "published"


# ---------- 10. complete sets flags ----------


def test_complete_sets_source_flags(db, no_sleep) -> None:
    src = make_source("f")
    make_run(src["id"])
    t = provider_transport({None: (200, {"results": [reel_item("601")], "cursor": None})})
    asyncio.run(run_initial_scan("scan1", transport=t))
    stored = asyncio.run(sources.get_source(src["id"]))
    assert stored["crawl_complete"] is True
    assert stored["initial_scan_completed"] is True
    assert stored["discovered_total"] == 1
    assert stored["last_scan_status"] == "completed"
    assert stored["last_scan_error"] is None


# ---------- 11. partial ----------


def test_partial_on_midway_failure(db, no_sleep) -> None:
    src = make_source("g")
    make_run(src["id"])
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("701")], "cursor": "BAD"}),
            "BAD": (500, {"detail": "upstream boom"}),
        }
    )
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["status"] == "partial"
    assert run["discovered_count"] == 1 and run["inserted_count"] == 1
    assert run["crawl_complete"] is False
    stored = asyncio.run(sources.get_source(src["id"]))
    assert stored["discovered_total"] == 1 and stored["crawl_complete"] is False


# ---------- 12. 429 ----------


def test_rate_limited(db, no_sleep) -> None:
    src = make_source("h")
    make_run(src["id"])
    t = provider_transport({None: (429, "slow down")})
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["status"] == "failed"
    assert run["stop_reason"] == "RAPIDAPI_RATE_LIMITED"


# ---------- 13. 401/403 ----------


def test_auth_error(db, no_sleep) -> None:
    for code in (401, 403):
        src = make_source(f"i{code}")
        run_id = f"scan{code}"
        make_run(src["id"], run_id)
        t = provider_transport({None: (code, "unauthorized")})
        asyncio.run(run_initial_scan(run_id, transport=t))
        run = asyncio.run(scan_runs.get_scan_run(run_id))
        assert run["status"] == "failed", code
        assert run["stop_reason"] == "RAPIDAPI_AUTH_ERROR", code


# ---------- 14. timeout ----------


def test_timeout(db, no_sleep) -> None:
    src = make_source("j")
    make_run(src["id"])
    t = provider_transport({None: (200, httpx.ConnectError("down"))})
    asyncio.run(run_initial_scan("scan1", transport=t))
    run = asyncio.run(scan_runs.get_scan_run("scan1"))
    assert run["status"] == "failed"
    assert run["stop_reason"] == "RAPIDAPI_TIMEOUT"


# ---------- 15. invalid schema ----------


def test_invalid_schema(db, no_sleep) -> None:
    cases = [
        provider_transport({None: (200, "NOT JSON{{")}),
        provider_transport({None: (200, {"noresults": []})}),
        provider_transport({None: (200, {"results": "oops"})}),
        provider_transport(details_ok=False),
    ]
    for idx, t in enumerate(cases):
        src = make_source(f"k{idx}")
        run_id = f"scanx{idx}"
        make_run(src["id"], run_id)
        asyncio.run(run_initial_scan(run_id, transport=t))
        run = asyncio.run(scan_runs.get_scan_run(run_id))
        assert run["status"] == "failed", idx
        assert run["stop_reason"] == "RAPIDAPI_RESPONSE_INVALID", idx


# ---------- 16. 409 ----------


def test_scan_already_running_409(db, monkeypatch) -> None:
    src = make_source("l")

    async def _noop(scan_run_id: str, transport=None) -> None:
        return None

    monkeypatch.setattr(scan_module, "run_initial_scan", _noop)
    client = TestClient(create_app())
    r1 = client.post(f"/api/facebook/sources/{src['id']}/scan", headers=AUTH_HEADERS)
    assert r1.status_code == 202, r1.text
    assert r1.json()["status"] == "queued"
    r2 = client.post(f"/api/facebook/sources/{src['id']}/scan", headers=AUTH_HEADERS)
    assert r2.status_code == 409
    assert r2.json()["error"] == "SCAN_ALREADY_RUNNING"


def test_scan_requires_auth_and_source(db) -> None:
    client = TestClient(create_app())
    r = client.post("/api/facebook/sources/nope/scan", headers=AUTH_HEADERS)
    assert r.status_code == 404
    assert r.json()["error"] == "SOURCE_NOT_FOUND"
    src = make_source("m")
    r = client.post(f"/api/facebook/sources/{src['id']}/scan")
    assert r.status_code == 401


def test_scan_run_status_endpoint(db, no_sleep) -> None:
    src = make_source("n")
    make_run(src["id"])
    t = provider_transport({None: (200, {"results": [reel_item("801")], "cursor": None})})
    asyncio.run(run_initial_scan("scan1", transport=t))
    client = TestClient(create_app())
    r = client.get("/api/facebook/scan-runs/scan1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["discovered_count"] == 1 and body["inserted_count"] == 1
    assert body["crawl_complete"] is True and body["error"] is None


# ---------- 17. discovered_total ----------


def test_discovered_total_is_count(db, no_sleep) -> None:
    src = make_source("o")
    other = make_source("p")
    asyncio.run(
        reels.insert_reel_if_new(
            reel_db_id=f"{other['id']}_999", source_id=other["id"], reel_id="999"
        )
    )
    make_run(src["id"])
    t = provider_transport(
        {None: (200, {"results": [reel_item("901"), reel_item("902")], "cursor": None})}
    )
    asyncio.run(run_initial_scan("scan1", transport=t))
    stored = asyncio.run(sources.get_source(src["id"]))
    assert stored["discovered_total"] == 2


# ---------- 18. stale cleanup ----------


def test_stale_running_cleanup(db) -> None:
    src = make_source("q")
    asyncio.run(scan_runs.create_scan_run(scan_run_id="st1", source_id=src["id"], status="running"))
    asyncio.run(scan_runs.create_scan_run(scan_run_id="st2", source_id=src["id"], status="queued"))
    n = asyncio.run(scan_runs.fail_stale_scan_runs())
    assert n == 2
    assert (asyncio.run(scan_runs.get_scan_run("st1")))["status"] == "failed"
    assert asyncio.run(scan_runs.get_active_scan_run(src["id"])) is None


# ---------- 19. health ----------


def test_health(db) -> None:
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "backend-facebook", "version": "1.0.0"}


def test_error_codes_have_no_key_leak(db, no_sleep) -> None:
    cli = FacebookRapidApiClient(
        RapidApiConfig(base_url="https://test-host", host="test-host", api_keys=["SECRETKEY"])
    )
    t = provider_transport({None: (401, "bad")})
    try:
        asyncio.run(cli.list_reels(PAGE_ID, transport=t))
        raise AssertionError("should raise")
    except RapidApiError as exc:
        assert "SECRETKEY" not in str(exc) and "SECRETKEY" not in exc.code
