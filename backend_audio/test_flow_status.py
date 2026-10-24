import pytest
from fastapi.testclient import TestClient
from app.main import app
import uuid
import sys

client = TestClient(app)

def test_flow_status():
    # Attempt to fetch pipelines to get a valid pipeline ID
    response = client.get("/api/audio/pipelines", headers={"Authorization": "Bearer admin-token-here"})
    # Since auth might be an issue, let's bypass require_admin
    # We can patch it.
    pass
