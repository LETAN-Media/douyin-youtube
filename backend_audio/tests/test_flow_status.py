import pytest
from fastapi.testclient import TestClient
import os

@pytest.fixture(scope="session", autouse=True)
def set_env():
    os.environ["AUDIO_ADMIN_TOKEN"] = "Tan@230997"

def test_flow_status_endpoint():
    from app.config import settings
    token = settings.AUDIO_ADMIN_TOKEN or "Tan@230997"
    settings.AUDIO_ADMIN_TOKEN = token
    from app.main import create_app
    app = create_app()
    app.router.lifespan_context = None # disable lifespan to prevent worker from starting
    client = TestClient(app)
    res = client.get("/api/audio/pipelines", headers={"X-Admin-Token": token})
    assert res.status_code == 200
    
    items = res.json()["items"]
    audio_pipe = next((p for p in items if p["name"] == "Audio Truyện"), items[0] if items else None)
    
    if not audio_pipe:
        pytest.skip("No pipeline found")
        
    pid = audio_pipe["id"]
    
    res = client.get(f"/api/audio/pipelines/{pid}/flow-status", headers={"X-Admin-Token": token})
    assert res.status_code == 200
    
    data = res.json()
    assert "pipeline" in data
    assert "worker_alive" in data
    assert "steps" in data
    assert "queue_preview" in data
    assert "recent_failures" in data
    assert "counts" in data
    
    counts = data["counts"]
    print("\n--- TEST SUCCESS ---")
    print("Counts:", counts)
