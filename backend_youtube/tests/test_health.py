import pytest

from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    app = create_app()
    import anyio
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/api/youtube-fb/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_openapi(client):
    resp = client.get("/api/youtube-fb/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    paths = data["paths"]
    assert "/api/youtube-fb/pipelines" in paths
    assert "/api/youtube-fb/health" in paths
