"""Route contracts: pipelines, sources, scan trigger, inventory, auth."""

from fastapi.testclient import TestClient

from app.db.repositories import drama as repo
from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


def _client():
    return TestClient(create_app())


def test_auth_required(db):
    assert _client().get("/api/drama/pipelines").status_code in (401, 500)


def test_pipeline_crud(db):
    c = _client()
    assert c.get("/api/drama/pipelines", headers=ADMIN).json() == []
    r = c.post("/api/drama/pipelines", headers=ADMIN, json={"name": "Show A"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["slug"] == "show-a"
    dup = c.post(
        "/api/drama/pipelines", headers=ADMIN,
        json={"name": "Show A", "slug": "show-a"},
    )
    assert dup.status_code == 409
    got = c.get(f"/api/drama/pipelines/{pid}", headers=ADMIN)
    assert got.status_code == 200 and got.json()["name"] == "Show A"
    assert c.get("/api/drama/pipelines/dpl_nope", headers=ADMIN).status_code == 404


def test_source_and_scan_flow(db):
    c = _client()
    pid = c.post("/api/drama/pipelines", headers=ADMIN, json={"name": "Show B"}).json()["id"]
    s = c.post(
        f"/api/drama/pipelines/{pid}/sources", headers=ADMIN,
        json={"external_series_id": "b77", "name": "B"},
    )
    assert s.status_code == 201, s.text
    sid = s.json()["id"]
    listed = c.get(f"/api/drama/pipelines/{pid}/sources", headers=ADMIN).json()
    assert [x["id"] for x in listed] == [sid]
    # Without endpoint paths the scan refuses with a typed provider error
    # (no network, no quota burned).
    from app.config import settings

    settings.RAPIDIX_SEARCH_PATH = None
    settings.RAPIDIX_EPISODES_PATH = None
    settings.RAPIDIX_EPISODE_PATH = None
    r = c.post(f"/api/drama/sources/{sid}/scan", headers=ADMIN)
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["error"] in (
        "NOT_CONFIGURED", "PROVIDER_ERROR", "ALL_PROVIDERS_FAILED",
    )
    assert c.post("/api/drama/sources/dsrc_nope/scan", headers=ADMIN).status_code == 404


def test_inventory_ordering_and_filter(db):
    c = _client()
    pid = c.post("/api/drama/pipelines", headers=ADMIN, json={"name": "Show C"}).json()["id"]
    src = c.post(
        f"/api/drama/pipelines/{pid}/sources", headers=ADMIN,
        json={"external_series_id": "b88"},
    ).json()
    series, _ = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="b88"
    )
    for n in (2, 1):
        repo.upsert_episode(
            series_id=series["id"], provider="rapidix",
            external_episode_id=f"e{n}", episode_number=n,
        )
    inv = c.get(f"/api/drama/pipelines/{pid}/inventory", headers=ADMIN).json()
    assert inv["total"] == 2
    assert [e["episode_number"] for e in inv["items"]] == [1, 2]
    eps = c.get(f"/api/drama/series/{series['id']}/episodes", headers=ADMIN).json()
    assert eps["total"] == 2
    assert c.get(f"/api/drama/pipelines/dpl_nope/inventory", headers=ADMIN).status_code == 404
