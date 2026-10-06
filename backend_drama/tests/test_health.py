"""Config, health, readiness (no provider calls, no secrets)."""

from fastapi.testclient import TestClient


def test_health_ok(db):
    from app.main import create_app

    r = TestClient(create_app()).get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "backend-drama"}


def test_ready_reports_db_and_rapidix(db):
    from app.main import create_app

    r = TestClient(create_app()).get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "backend-drama"
    assert body["db"] == "sqlite"
    assert body["rapidix"] == "configured"
    assert body["ok"] is True


def test_ready_without_rapidix_key(db, monkeypatch):
    from app.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "RAPIDIX_KEY", "")
    r = TestClient(create_app()).get("/ready")
    assert r.status_code == 200
    assert r.json()["rapidix"] == "missing"


def test_config_defaults_and_overrides(monkeypatch):
    from app.config import Settings

    s = Settings()
    assert s.SERVICE_NAME == "backend-drama"
    assert s.PORT == 8080
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("RAPIDIX_TIMEOUT_SECONDS", "45")
    s2 = Settings()
    assert s2.PORT == 9999
    assert s2.RAPIDIX_TIMEOUT_SECONDS == 45.0
