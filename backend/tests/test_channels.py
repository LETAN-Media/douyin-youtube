from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

def test_channels_api():
    client = TestClient(app)
    # Test unauthorized
    res_unauth = client.get("/api/channels")
    assert res_unauth.status_code == 401

    # Test authorized
    res = client.get(
        "/api/channels",
        headers={"X-Admin-Token": settings.admin_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)

    if data:
        ch = data[0]
        assert "destination_id" in ch
        assert "pipeline_id" in ch
        assert "channel_title" in ch
        assert "connected" in ch
        assert "published_today" in ch
        assert "queue_count" in ch

        # Test channel detail
        detail_res = client.get(
            f"/api/channels/{ch['destination_id']}",
            headers={"X-Admin-Token": settings.admin_token},
        )
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert "channel" in detail_data
        assert "pipeline" in detail_data
        assert "sources" in detail_data
        assert "queue" in detail_data
        assert "published" in detail_data
