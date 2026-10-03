from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "service": "backend-facebook", "version": "1.0.0"}
