import os
import sys

# Load test env
os.environ["AUDIO_ADMIN_TOKEN"] = "Tan@230997"
os.environ["SQLITE_URL"] = "sqlite:///app.db" # Maybe default?

from fastapi.testclient import TestClient
from app.main import app
from app.db.repositories import pipelines as pipe_repo

client = TestClient(app)

def test_flow_status():
    # First get a pipeline
    token = "Tan@230997"
    res = client.get("/api/audio/pipelines", headers={"X-Admin-Token": token})
    assert res.status_code == 200
    items = res.json().get("items", [])
    if not items:
        # Create a mock one if empty
        res = client.post("/api/audio/pipelines", json={"name": "Test Audio"}, headers={"X-Admin-Token": token})
        assert res.status_code == 201
        pipe_id = res.json()["id"]
    else:
        pipe_id = items[0]["id"]
        
    # Get flow status
    res = client.get(f"/api/audio/pipelines/{pipe_id}/flow-status", headers={"X-Admin-Token": token})
    assert res.status_code == 200, res.text
    data = res.json()
    assert "pipeline" in data
    assert "steps" in data
    assert "queue_preview" in data
    assert "counts" in data
    print("SUCCESS: GET /flow-status returned 200 OK")
    print(f"Data counts: {data['counts']}")

if __name__ == "__main__":
    test_flow_status()
