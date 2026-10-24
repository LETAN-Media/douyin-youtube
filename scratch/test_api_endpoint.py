import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import os
import sys

# Mock env
os.environ["AUDIO_ADMIN_TOKEN"] = "Tan@230997"
os.environ["SQLITE_URL"] = "sqlite:///app.db"

# Create a slim app to avoid running lifespan (workers, migrations)
app = FastAPI()
from app.routes import pipelines
app.include_router(pipelines.router)

client = TestClient(app)

def test_endpoint():
    token = "Tan@230997"
    # Find pipeline
    res = client.get("/api/audio/pipelines", headers={"X-Admin-Token": token})
    assert res.status_code == 200
    items = res.json()["items"]
    audio_pipe = next((p for p in items if p["name"] == "Audio Truyện"), items[0] if items else None)
    if not audio_pipe:
        print("No pipelines found")
        return
        
    pid = audio_pipe["id"]
    
    # Test flow-status
    res = client.get(f"/api/audio/pipelines/{pid}/flow-status", headers={"X-Admin-Token": token})
    assert res.status_code == 200
    data = res.json()
    print("STATUS 200 OK")
    print(f"Data pipeline: {data['pipeline']['name']}")
    print(f"Data counts: {data['counts']}")
    print(f"Queue preview items: {len(data['queue_preview'])}")
    if data['queue_preview']:
        print(f"Queue[0]: {data['queue_preview'][0]}")
    print(f"Recent failures items: {len(data['recent_failures'])}")
    if data['recent_failures']:
        print(f"Failure[0]: {data['recent_failures'][0]}")

if __name__ == "__main__":
    test_endpoint()
