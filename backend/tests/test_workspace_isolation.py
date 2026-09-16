import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.db import SessionLocal
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline, Publication


def test_workspace_isolation_api():
    client = TestClient(app)
    headers = {"X-Admin-Token": settings.admin_token}

    with SessionLocal() as db:
        # Pipeline & Destination A (e.g. VibeMen)
        pipe_a = db.query(Pipeline).filter(Pipeline.slug == "vibe-men-world").first()
        dest_a = db.query(Destination).filter(Destination.pipeline_id == pipe_a.id).first() if pipe_a else None

        # Pipeline & Destination B (e.g. JoyBeat)
        pipe_b = db.query(Pipeline).filter(Pipeline.slug == "joybeat-dance").first()
        dest_b = db.query(Destination).filter(Destination.pipeline_id == pipe_b.id).first() if pipe_b else None

        if not pipe_a or not dest_a or not pipe_b or not dest_b:
            pytest.skip("Test requires both VibeMen and JoyBeat workspaces in DB")

        # Create a test video in Pipeline A
        vid_a = db.query(DouyinVideo).filter(DouyinVideo.pipeline_id == pipe_a.id).first()
        if not vid_a:
            vid_a = DouyinVideo(
                pipeline_id=pipe_a.id,
                video_id="video-unique-pipe-a-12345",
                title="Pipe A Video",
                description="Test description",
                url="https://v.douyin.com/pipe_a_test/",
                status="inventory",
            )
            db.add(vid_a)
            db.commit()
            db.refresh(vid_a)

        # Create a test source in Pipeline A
        src_a = db.query(DouyinSource).filter(DouyinSource.pipeline_id == pipe_a.id).first()
        if not src_a:
            src_a = DouyinSource(
                pipeline_id=pipe_a.id,
                name="Source Pipe A",
                profile_url="https://www.douyin.com/user/pipe_a_src",
                enabled=True,
            )
            db.add(src_a)
            db.commit()
            db.refresh(src_a)

        dest_a_id = dest_a.id
        dest_b_id = dest_b.id
        vid_a_video_id = vid_a.video_id
        src_a_id = src_a.id

    # 1. Test GET /api/channels/{destination_id} returns workspace-scoped inventory and info
    res_a = client.get(f"/api/channels/{dest_a_id}", headers=headers)
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["channel"]["destination_id"] == dest_a_id
    assert "inventory" in data_a
    assert "queue" in data_a
    assert "published" in data_a
    assert "sources" in data_a

    # 2. Test GET /api/channels/{destination_id}/inventory is scoped to that workspace
    inv_res_a = client.get(f"/api/channels/{dest_a_id}/inventory", headers=headers)
    assert inv_res_a.status_code == 200
    inv_data_a = inv_res_a.json()
    assert "items" in inv_data_a
    for item in inv_data_a["items"]:
        # Verify video belongs to pipeline A
        assert item["video_id"] is not None

    inv_res_b = client.get(f"/api/channels/{dest_b_id}/inventory", headers=headers)
    assert inv_res_b.status_code == 200
    inv_data_b = inv_res_b.json()
    # Video A must not appear in Workspace B inventory
    b_video_ids = [item["video_id"] for item in inv_data_b["items"]]
    assert vid_a_video_id not in b_video_ids

    # 3. Test Cross-Workspace Publish Rejection (Requirement 15):
    # Try to publish Video A (from Pipeline A) into Destination B (Pipeline B)
    cross_pub_res = client.post(
        "/api/manual/publish",
        headers=headers,
        json={
            "source_url": "https://v.douyin.com/test_cross/",
            "source_title": "Cross video test",
            "video_id": vid_a_video_id,
            "destination_ids": [dest_b_id],
        }
    )
    assert cross_pub_res.status_code == 403
    assert "Cross-workspace mismatch" in cross_pub_res.text

    # 4. Test Cross-Workspace Source Action Rejection (Requirement 15):
    # Try to delete Source A (belonging to Pipeline A) via Destination B API
    cross_del_src = client.delete(
        f"/api/channels/{dest_b_id}/sources/{src_a_id}",
        headers=headers,
    )
    assert cross_del_src.status_code == 403
    assert "Cross-workspace mismatch" in cross_del_src.text

    # Try to sync Source A via Destination B API
    cross_sync_src = client.post(
        f"/api/channels/{dest_b_id}/sources/{src_a_id}/sync",
        headers=headers,
    )
    assert cross_sync_src.status_code == 403
    assert "Cross-workspace mismatch" in cross_sync_src.text

    # 5. Test Workspace Settings Update via PATCH
    patch_res = client.patch(
        f"/api/channels/{dest_b_id}",
        headers=headers,
        json={
            "daily_upload_limit": 4,
            "timezone": "America/New_York",
        }
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.json()
    assert patch_data["daily_upload_limit"] == 4
    assert patch_data["timezone"] == "America/New_York"
