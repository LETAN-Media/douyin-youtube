import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.media.drama_media import (
    resolve_drama_media,
    ResolvedDramaMedia,
)
from app.services.drama_youtube_publisher import (
    build_metadata,
    publish_job_final,
)
from app.services.processing import run_series_job


@pytest.mark.asyncio
async def test_resolve_crazymaple_thumbnail_hls():
    raw_payload = {
        "thumbnail_url": "https://v-mps.crazymaplestudios.com/vod-112094/0094e947d73671eebfbe1426d0910102/snapshots/1472d5b427804b90882d6b21df182ad9-00001.jpg"
    }
    resolved = await resolve_drama_media(
        source_url="https://www.reelshort.com/movie/65df8281515dc2c2300535b9",
        raw_payload=raw_payload,
    )
    assert resolved.media_type == "HLS"
    assert "0094e947d73671eebfbe1426d0910102" in resolved.media_url
    assert resolved.media_url == "https://v-mps.crazymaplestudios.com/0094e947d73671eebfbe1426d0910102/h264-ordinary-fd.m3u8"


def test_build_metadata_unlisted_visibility():
    meta = build_metadata(
        title="Test Title",
        description="Test Desc",
        visibility="unlisted",
    )
    assert meta["status"]["privacyStatus"] == "unlisted"


@pytest.mark.asyncio
async def test_publish_job_final_visibility_override(tmp_path):
    job = {
        "id": "job_reg_test_1",
        "pipeline_id": "pip_1",
        "series_id": "ser_1",
        "episode_start": 1,
        "episode_end": 2,
    }
    dummy_file = tmp_path / "final.mp4"
    dummy_file.write_bytes(b"dummy")

    with patch("app.db.repositories.processing.get_job", return_value=job), \
         patch("app.db.repositories.processing.get_settings", return_value={"youtube_destination_id": "dest_1"}), \
         patch("app.db.repositories.youtube.get_destination", return_value={"id": "dest_1", "connected": 1, "visibility": "public"}), \
         patch("app.services.drama_youtube_oauth.load_credentials", return_value=MagicMock()), \
         patch("app.services.drama_ai_metadata.ensure_drama_ai_metadata", side_effect=RuntimeError("AI off")), \
         patch("app.db.repositories.processing.update_job") as mock_update, \
         patch("app.services.drama_youtube_publisher.upload_video", return_value="yt_test_vid_123") as mock_upload:

        out = await publish_job_final(
            job,
            dummy_file,
            title="Custom Title",
            visibility="unlisted",
        )
        assert out["youtube_video_id"] == "yt_test_vid_123"
        # Verify metadata passed to upload_video has unlisted visibility!
        passed_metadata = mock_upload.call_args[0][2]
        assert passed_metadata["status"]["privacyStatus"] == "unlisted"
        assert "Tập 1-2" in passed_metadata["snippet"]["title"]


@pytest.mark.asyncio
async def test_create_single_test_job_endpoint():
    from app.routes.processing import create_single_test_job, TestMergeJobRequest
    from fastapi import HTTPException

    # Test series not found
    with patch("app.db.repositories.drama.get_series", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await create_single_test_job("ser_unknown", TestMergeJobRequest())
        assert exc.value.status_code == 404

    # Test pipeline slug mismatch
    with patch("app.db.repositories.drama.get_series", return_value={"id": "ser_1", "source_id": "src_1"}), \
         patch("app.db.repositories.drama.get_source", return_value={"id": "src_1", "pipeline_id": "pip_1"}), \
         patch("app.db.repositories.drama.get_pipeline", return_value={"id": "pip_1", "slug": "real-pipeline"}):
        with pytest.raises(HTTPException) as exc:
            await create_single_test_job("ser_1", TestMergeJobRequest(pipeline_slug="wrong-slug"))
        assert exc.value.status_code == 400
        assert "SLUG_MISMATCH" in str(exc.value.detail)

    # Test idempotency (reused existing job)
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchone.side_effect = [
        (2,), # ep_count
        ("job_existing_1",), # existing job
    ]
    with patch("app.db.repositories.drama.get_series", return_value={"id": "ser_1", "source_id": "src_1"}), \
         patch("app.db.repositories.drama.get_source", return_value={"id": "src_1", "pipeline_id": "pip_1"}), \
         patch("app.db.repositories.drama.get_pipeline", return_value={"id": "pip_1", "slug": "test-rapidix-pipeline"}), \
         patch("app.db.client.get_client", return_value=mock_db), \
         patch("app.db.repositories.processing.get_job", return_value={"id": "job_existing_1", "status": "queued"}):
        res = await create_single_test_job("ser_1", TestMergeJobRequest(pipeline_slug="test-rapidix-pipeline"))
        assert res["action"] == "reused"
        assert res["job"]["id"] == "job_existing_1"

