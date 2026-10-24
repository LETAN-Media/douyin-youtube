from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "backend-facebook"
    assert body["version"] == "1.0.0"
    assert "commit" in body
