import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app, resolve_douyin_input
from app.models import Destination, DouyinVideo, Pipeline, Publication, VideoJob
from app.db import SessionLocal
from app.config import settings


@pytest.fixture
def client():
    # TestClient with mock or real db
    return TestClient(app, headers={"X-Admin-Token": settings.admin_token})


def test_resolve_douyin_profile():
    # Test profile link detection
    profile_url = "https://www.douyin.com/user/MS4wLjABAAAASChg57PV3dhImQ4h76xHPZm-k4R-jpwteiDcODneqTzBIlj-uoFyBwPCbMVighsq"
    res = resolve_douyin_input(profile_url)
    assert res["type"] == "profile"
    assert "Douyin profile" in res["message"]
    assert res["sec_uid"] == "MS4wLjABAAAASChg57PV3dhImQ4h76xHPZm-k4R-jpwteiDcODneqTzBIlj-uoFyBwPCbMVighsq"


def test_resolve_douyin_video_mocked():
    sample_text = "7.11 02/05 三石 这里不准跳水 #游泳 #安全员 https://v.douyin.com/a3YI-rSItwI/ 复制打开抖音，看看【三石的作品】"
    with patch("app.main.call_rcuts_parser") as mock_rcuts, \
         patch("app.main.urllib.request.urlopen") as mock_urlopen, \
         patch("subprocess.run") as mock_subproc:
        mock_resp = MagicMock()
        mock_resp.geturl.return_value = "https://www.iesdouyin.com/share/video/7661222513787886918/?from_ssr=1"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        mock_rcuts.return_value = {
            "video_name": "这里不准跳水 #游泳 #安全员",
            "cover": "https://p3-sign.douyinpic.com/cover.jpg",
            "video_url": "https://v.douyin.com/video.mp4",
        }

        mock_subproc.return_value.stdout = "37.2\n"

        res = resolve_douyin_input(sample_text)
        assert res["type"] == "video"
        assert res["video_id"] == "7661222513787886918"
        assert res["author"] == "三石"
        assert "这里不准跳水" in res["caption"]
        assert res["thumbnail"] == "https://p3-sign.douyinpic.com/cover.jpg"
        assert res["duration"] == 37
        assert res["status"] == "Video detected"


def test_manual_metadata_endpoint(client):
    with patch("app.main.generate_metadata_structured") as mock_gen:
        mock_gen.return_value = {
            "title": "Generated Title",
            "description": "Clean description",
            "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
            "final_description": "Clean description\n\n#tag1 #tag2 #tag3 #tag4 #tag5",
        }

        resp = client.post(
            "/api/manual/metadata",
            json={
                "source_url": "https://v.douyin.com/test1234/",
                "caption": "Test video caption",
                "metadata_mode": "same",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata_mode"] == "same"
        assert data["same"]["title"] == "Generated Title"
        assert len(data["same"]["hashtags"]) == 5


def test_manual_publish_flow(client):
    with SessionLocal() as db:
        dest = db.query(Destination).filter(Destination.connected == True).first()
        if not dest:
            pytest.skip("No connected destination for manual publish test")
        dest_id = dest.id

    # Test publish request
    pub_payload = {
        "source_url": "https://v.douyin.com/test_manual_video/",
        "source_title": "Manual Test Title",
        "video_id": "test_manual_vid_9999",
        "thumbnail": "https://example.com/thumb.jpg",
        "duration": 45,
        "destination_ids": [dest_id],
        "metadata_mode": "same",
        "title": "Manual Custom Title",
        "description": "Manual custom desc\n\n#tag1 #tag2 #tag3 #tag4 #tag5",
        "privacy_status": "unlisted",
        "force_duplicate": True,
    }

    resp = client.post("/api/manual/publish", json=pub_payload)
    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] is True
    assert len(data["publications"]) == 1
    pub_item = data["publications"][0]
    assert pub_item["status"] == "queued"
    pub_id = pub_item["id"]

    # Verify publication in database has publication_mode = 'manual'
    with SessionLocal() as db:
        p = db.get(Publication, pub_id)
        assert p is not None
        assert p.publication_mode == "manual"
        assert p.status == "queued"

        job = db.query(VideoJob).filter(VideoJob.publication_id == pub_id).first()
        assert job is not None
        assert job.status == "pending"
        assert job.privacy_status == "unlisted"
        assert job.title == "Manual Custom Title"

    # Test list manual publications
    list_resp = client.get("/api/manual/publications")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert any(item["id"] == pub_id for item in list_data)

    # Test get manual publication
    get_resp = client.get(f"/api/manual/publications/{pub_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == pub_id

    # Clean up test job & publication
    with SessionLocal() as db:
        db.query(VideoJob).filter(VideoJob.publication_id == pub_id).delete()
        db.query(Publication).filter(Publication.id == pub_id).delete()
        db.query(DouyinVideo).filter(DouyinVideo.video_id == "test_manual_vid_9999").delete()
        db.commit()
