"""Tests for manual vs auto audio pipelines (migration audio_008, filtering, scheduler guards)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(db):
    return TestClient(app, headers={"X-Admin-Token": "test_admin_token"})


def test_migration_and_defaults(db):
    from app.db.repositories import pipelines as repo

    # Default created pipeline is auto
    p_auto = repo.create_pipeline("Auto Truyện Test")
    assert p_auto["pipeline_type"] == "auto"
    assert p_auto["auto_publish"] is True

    # Manual pipeline has auto_publish = False
    p_manual = repo.create_pipeline("Manual Truyện Test", pipeline_type="manual")
    assert p_manual["pipeline_type"] == "manual"
    assert p_manual["auto_publish"] is False


def test_list_filtering(db):
    from app.db.repositories import pipelines as repo

    p1 = repo.create_pipeline("Auto 1", pipeline_type="auto")
    p2 = repo.create_pipeline("Manual 1", pipeline_type="manual")

    all_pipes = repo.list_pipelines()
    assert len(all_pipes) >= 2

    auto_pipes = repo.list_pipelines(pipeline_type="auto")
    assert any(p["id"] == p1["id"] for p in auto_pipes)
    assert not any(p["id"] == p2["id"] for p in auto_pipes)

    manual_pipes = repo.list_pipelines(pipeline_type="manual")
    assert any(p["id"] == p2["id"] for p in manual_pipes)
    assert not any(p["id"] == p1["id"] for p in manual_pipes)


def test_api_create_and_list_tabs(client):
    # Create auto pipeline
    res_auto = client.post("/api/audio/pipelines", json={"name": "Auto Story"})
    assert res_auto.status_code == 201
    d_auto = res_auto.json()
    assert d_auto["pipeline_type"] == "auto"
    assert d_auto["auto_publish"] is True

    # Create manual pipeline
    res_man = client.post("/api/audio/pipelines", json={
        "name": "Manual Story",
        "pipeline_type": "manual",
        "auto_publish": True,  # should be forced to False
    })
    assert res_man.status_code == 201
    d_man = res_man.json()
    assert d_man["pipeline_type"] == "manual"
    assert d_man["auto_publish"] is False

    # List all
    res_all = client.get("/api/audio/pipelines")
    assert res_all.status_code == 200
    ids_all = [p["id"] for p in res_all.json()["items"]]
    assert d_auto["id"] in ids_all
    assert d_man["id"] in ids_all

    # List tab Auto
    res_tab_auto = client.get("/api/audio/pipelines?type=auto")
    assert res_tab_auto.status_code == 200
    ids_tab_auto = [p["id"] for p in res_tab_auto.json()["items"]]
    assert d_auto["id"] in ids_tab_auto
    assert d_man["id"] not in ids_tab_auto

    # List tab Manual
    res_tab_man = client.get("/api/audio/pipelines?type=manual")
    assert res_tab_man.status_code == 200
    ids_tab_man = [p["id"] for p in res_tab_man.json()["items"]]
    assert d_man["id"] in ids_tab_man
    assert d_auto["id"] not in ids_tab_man


def test_scheduler_ignores_manual_pipeline(client):
    from app.services.scheduler import pipeline_due

    # Create manual pipeline
    res = client.post("/api/audio/pipelines", json={
        "name": "Manual No Scheduler",
        "pipeline_type": "manual",
    })
    pid = res.json()["id"]

    # Scheduler due check returns False
    due, reason = pipeline_due(pid)
    assert due is False
    assert "manual" in reason.lower()

    # Attempt to enable scheduler returns 400
    res_enable = client.put(f"/api/audio/pipelines/{pid}/scheduler", json={"enabled": True})
    assert res_enable.status_code == 400
    assert res_enable.json()["error"] == "MANUAL_PIPELINE"

    # Attempt to trigger tick returns 400
    res_tick = client.post(f"/api/audio/pipelines/{pid}/scheduler/tick")
    assert res_tick.status_code == 400
    assert res_tick.json()["error"] == "MANUAL_PIPELINE"


def test_delete_manual_pipeline_preserves_auto(client):
    res_auto = client.post("/api/audio/pipelines", json={"name": "Auto Preserved"})
    pid_auto = res_auto.json()["id"]

    res_man = client.post("/api/audio/pipelines", json={
        "name": "Manual To Delete",
        "pipeline_type": "manual",
    })
    pid_man = res_man.json()["id"]

    # Delete manual
    res_del = client.delete(f"/api/audio/pipelines/{pid_man}")
    assert res_del.status_code == 200

    # Auto still exists
    res_get = client.get(f"/api/audio/pipelines/{pid_auto}")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "Auto Preserved"
