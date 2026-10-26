"""Regression tests for TikTok Auto Publishing, Queue lifecycle, and Video Formats."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.db.client import close_client, execute, migrate
from app.db.repositories import (
    destinations,
    pipelines,
    publications,
    publish_queue,
    reels,
    schedules,
    sources,
)
from app.services import tiktok_scheduler, tiktok_shorts


@pytest.fixture(autouse=True)
async def setup_test_db():
    await migrate()
    # Clean up test tables
    await execute("DELETE FROM tiktok_publish_queue")
    await execute("DELETE FROM tiktok_publications")
    await execute("DELETE FROM tiktok_reels")
    await execute("DELETE FROM tiktok_sources")
    await execute("DELETE FROM youtube_destinations")
    await execute("DELETE FROM tiktok_publish_schedules")
    await execute("DELETE FROM tiktok_publish_schedule_slots")
    await execute("DELETE FROM tiktok_scheduler_batches")
    await execute("DELETE FROM tiktok_pipelines")
    yield
    await close_client()


# ============================================================================
# 1. Video Publishing Format & Shorts Verification Tests
# ============================================================================

def test_shorts_format_classification_matrix(tmp_path: Path):
    """Test classification for 'shorts', 'video', and 'both' modes."""
    # Mock probe_file results
    vertical_short = {"duration": 45.0, "width": 1080, "height": 1920, "is_vertical": True, "is_square": False, "is_landscape": False}
    square_short = {"duration": 60.0, "width": 1080, "height": 1080, "is_vertical": False, "is_square": True, "is_landscape": False}
    landscape_short = {"duration": 45.0, "width": 1920, "height": 1080, "is_vertical": False, "is_square": False, "is_landscape": True}
    long_vertical = {"duration": 240.0, "width": 1080, "height": 1920, "is_vertical": True, "is_square": False, "is_landscape": False}

    with patch.object(tiktok_shorts, "probe_file") as mock_probe:
        # Case 1: Mode = 'shorts', Vertical 45s -> Eligible Shorts
        mock_probe.return_value = vertical_short
        target, ok, note, _ = tiktok_shorts.classify_upload_format("shorts", tmp_path / "v1.mp4")
        assert target == "shorts"
        assert ok is True
        assert "Đủ điều kiện Shorts" in note

        # Case 2: Mode = 'shorts', Square 60s -> Eligible Shorts
        mock_probe.return_value = square_short
        target, ok, note, _ = tiktok_shorts.classify_upload_format("shorts", tmp_path / "v2.mp4")
        assert target == "shorts"
        assert ok is True

        # Case 3: Mode = 'shorts', Landscape -> Ineligible Shorts
        mock_probe.return_value = landscape_short
        target, ok, note, _ = tiktok_shorts.classify_upload_format("shorts", tmp_path / "v3.mp4")
        assert target == "shorts"
        assert ok is False
        assert "ngang" in note.lower()

        # Case 4: Mode = 'shorts', > 180s -> Ineligible Shorts
        mock_probe.return_value = long_vertical
        target, ok, note, _ = tiktok_shorts.classify_upload_format("shorts", tmp_path / "v4.mp4")
        assert target == "shorts"
        assert ok is False
        assert "vượt quá giới hạn" in note.lower()

        # Case 5: Mode = 'video' (Regular Only) -> Always proceeds as regular video
        mock_probe.return_value = vertical_short
        target, ok, note, _ = tiktok_shorts.classify_upload_format("video", tmp_path / "v5.mp4")
        assert target == "video"
        assert ok is True

        # Case 6: Mode = 'both', Vertical Short -> Auto-selects Shorts
        mock_probe.return_value = vertical_short
        target, ok, note, _ = tiktok_shorts.classify_upload_format("both", tmp_path / "v6.mp4")
        assert target == "shorts"
        assert ok is True
        assert "Shorts" in note

        # Case 7: Mode = 'both', Landscape -> Auto-selects Regular Video
        mock_probe.return_value = landscape_short
        target, ok, note, _ = tiktok_shorts.classify_upload_format("both", tmp_path / "v7.mp4")
        assert target == "video"
        assert ok is True
        assert "Regular Video" in note


# ============================================================================
# 2. Pipeline Settings & Upload Mode Repository Tests
# ============================================================================

async def test_pipeline_upload_mode_crud():
    """Verify creating, getting, and updating youtube_upload_mode on pipeline."""
    pipe = await pipelines.create_pipeline(
        pipeline_id="pl_mode_1",
        name="Pipeline Mode Test",
        slug="pl-mode-1",
        youtube_upload_mode="shorts",
    )
    assert pipe["youtube_upload_mode"] == "shorts"

    # Update to 'both'
    updated = await pipelines.update_pipeline("pl_mode_1", youtube_upload_mode="both")
    assert updated is not None
    assert updated["youtube_upload_mode"] == "both"

    # Update to 'video'
    updated2 = await pipelines.update_pipeline("pl_mode_1", youtube_upload_mode="video")
    assert updated2 is not None
    assert updated2["youtube_upload_mode"] == "video"

    # Invalid mode raises ValueError
    with pytest.raises(ValueError):
        await pipelines.update_pipeline("pl_mode_1", youtube_upload_mode="invalid_mode")


# ============================================================================
# 3. Auto Scheduler & Daily Limit Tests
# ============================================================================

async def test_scheduler_auto_enqueue_respects_daily_limit():
    """Verify scheduler selects unpublished reels, generates slots, and enforces daily limit."""
    # 1. Create pipeline with auto_publish ON
    pipe = await pipelines.create_pipeline(
        pipeline_id="pl_sched_1",
        name="Sched Test",
        slug="sched-test-1",
        auto_publish=True,
        youtube_upload_mode="shorts",
    )
    assert pipe["enabled"] == 1
    assert pipe["auto_publish"] == 1

    # 2. Create connected YouTube destination
    dest = await destinations.create_destination(
        destination_id="dest_sched_1",
        pipeline_id="pl_sched_1",
        channel_id="UC_test_123",
        channel_name="Test Channel",
        connected=True,
    )
    assert dest["connected"] == 1

    # 3. Create TikTok source
    src = await sources.create_source(
        source_id="src_sched_1",
        pipeline_id="pl_sched_1",
        username="tiktok_creator_test",
    )

    # 4. Insert 10 unpublished reels
    for i in range(10):
        await reels.insert_reel_if_new(
            reel_db_id=f"reel_test_{i}",
            source_id="src_sched_1",
            reel_id=f"tt_vid_{i}",
            reel_url=f"https://www.tiktok.com/@tiktok_creator_test/video/100{i}",
            caption=f"TikTok Viral Video #{i}",
            duration=30 + i * 5,  # all <= 180s
        )

    # 5. Create schedule with max_daily = 3
    await schedules.get_or_create_schedule(
        pipeline_id="pl_sched_1",
        timezone="Asia/Ho_Chi_Minh",
        max_daily=3,
    )
    await schedules.set_schedule_enabled("pl_sched_1", True)

    # 6. Run batch (force_now=True to test immediate scheduling logic)
    res = await tiktok_scheduler.execute_daily_batch("pl_sched_1", force_now=True)
    assert res["ok"] is True
    assert res["videos_enqueued"] == 3  # Exactly capped at max_daily=3!

    # 7. Verify jobs in publish queue
    q_items = await publish_queue.list_queue_for_pipeline("pl_sched_1")
    assert len(q_items) == 3
    for item in q_items:
        assert item["status"] == "queued"
        assert item["destination_id"] == "dest_sched_1"
        assert item["source_username"] == "tiktok_creator_test"
        assert item["destination_channel_name"] == "Test Channel"
        assert item["youtube_upload_mode"] == "shorts"

    # 8. Run batch second time today -> Daily limit reached!
    res2 = await tiktok_scheduler.execute_daily_batch("pl_sched_1", force_now=True)
    assert res2["ok"] is False
    assert res2["reason"] == "DAILY_LIMIT_REACHED"


async def test_scheduler_skips_when_auto_publish_off():
    """Verify that automatic tick does not schedule if auto_publish is OFF."""
    await pipelines.create_pipeline(
        pipeline_id="pl_disabled_auto",
        name="Auto Off Test",
        slug="auto-off-test",
        auto_publish=False,
    )
    res = await tiktok_scheduler.execute_daily_batch("pl_disabled_auto", force_now=False)
    assert res["ok"] is False
    assert res["reason"] == "AUTO_PUBLISH_DISABLED"


async def test_scheduler_requires_connected_destination():
    """Verify scheduler fails gracefully if no YouTube destination is connected."""
    await pipelines.create_pipeline(
        pipeline_id="pl_no_dest",
        name="No Dest Test",
        slug="no-dest-test",
        auto_publish=True,
    )
    await schedules.get_or_create_schedule("pl_no_dest")
    await schedules.set_schedule_enabled("pl_no_dest", True)

    res = await tiktok_scheduler.execute_daily_batch("pl_no_dest", force_now=True)
    assert res["ok"] is False
    assert res["reason"] == "NO_DESTINATION"


# ============================================================================
# 4. Queue Lifecycle Tests (Claim, Retry, Cancel, Reschedule)
# ============================================================================

async def test_queue_lifecycle():
    """Verify complete queue operations: claim, cancel, retry, reschedule."""
    await pipelines.create_pipeline(pipeline_id="pl_q", name="Queue Test", slug="q-test")
    await destinations.create_destination(
        destination_id="dest_q", pipeline_id="pl_q", channel_id="yt_q", channel_name="Q Channel", connected=True
    )
    await sources.create_source(source_id="src_q", pipeline_id="pl_q", username="user_q")
    await reels.insert_reel_if_new(reel_db_id="reel_q_1", source_id="src_q", reel_id="vid_q_1")

    pub = await publications.create_publication(
        publication_id="pub_q_1", reel_db_id="reel_q_1", destination_id="dest_q", status="queued"
    )
    await publish_queue.enqueue_publication_job(
        job_id="job_q_1",
        pipeline_id="pl_q",
        destination_id="dest_q",
        reel_db_id="reel_q_1",
        publication_id=pub["id"],
        priority=100,
    )

    # 1. Reschedule job
    resched_ok = await publish_queue.reschedule_job("job_q_1", "2026-10-27T10:00:00Z")
    assert resched_ok is True
    job_updated = await publish_queue.get_job("job_q_1")
    assert job_updated["scheduled_at"] == "2026-10-27T10:00:00Z"

    # 2. Cancel job
    cancel_ok = await publish_queue.cancel_job("job_q_1")
    assert cancel_ok is True
    job_cancelled = await publish_queue.get_job("job_q_1")
    assert job_cancelled["status"] == "cancelled"

    # Reel should be released back to 'new'
    reel_after_cancel = await reels.get_reel("reel_q_1")
    assert reel_after_cancel["status"] == "new"

    # 3. Retry cancelled job
    retry_ok = await publish_queue.retry_job("job_q_1")
    assert retry_ok is True
    job_retried = await publish_queue.get_job("job_q_1")
    assert job_retried["status"] == "queued"


# ============================================================================
# 5. Pipeline Isolation Tests
# ============================================================================

async def test_queue_pipeline_isolation():
    """Verify list_queue_for_pipeline only returns jobs belonging to the target pipeline."""
    # Pipeline A
    await pipelines.create_pipeline(pipeline_id="pl_A", name="Pipe A", slug="pipe-a")
    await destinations.create_destination(destination_id="dest_A", pipeline_id="pl_A", channel_id="yt_A", channel_name="Chan A")
    await sources.create_source(source_id="src_A", pipeline_id="pl_A", username="user_A")
    await reels.insert_reel_if_new(reel_db_id="reel_A", source_id="src_A", reel_id="vid_A")
    await publications.create_publication(publication_id="pub_A", reel_db_id="reel_A", destination_id="dest_A")
    await publish_queue.enqueue_publication_job(
        job_id="job_A", pipeline_id="pl_A", destination_id="dest_A", reel_db_id="reel_A", publication_id="pub_A"
    )

    # Pipeline B
    await pipelines.create_pipeline(pipeline_id="pl_B", name="Pipe B", slug="pipe-b")
    await destinations.create_destination(destination_id="dest_B", pipeline_id="pl_B", channel_id="yt_B", channel_name="Chan B")
    await sources.create_source(source_id="src_B", pipeline_id="pl_B", username="user_B")
    await reels.insert_reel_if_new(reel_db_id="reel_B", source_id="src_B", reel_id="vid_B")
    await publications.create_publication(publication_id="pub_B", reel_db_id="reel_B", destination_id="dest_B")
    await publish_queue.enqueue_publication_job(
        job_id="job_B", pipeline_id="pl_B", destination_id="dest_B", reel_db_id="reel_B", publication_id="pub_B"
    )

    # List queue for Pipeline A
    jobs_A = await publish_queue.list_queue_for_pipeline("pl_A")
    assert len(jobs_A) == 1
    assert jobs_A[0]["id"] == "job_A"
    assert jobs_A[0]["pipeline_id"] == "pl_A"

    # List queue for Pipeline B
    jobs_B = await publish_queue.list_queue_for_pipeline("pl_B")
    assert len(jobs_B) == 1
    assert jobs_B[0]["id"] == "job_B"
    assert jobs_B[0]["pipeline_id"] == "pl_B"


# ============================================================================
# 6. Video Validation & Publisher Direct Media Resolution Tests
# ============================================================================

def test_validate_video_file_checks(tmp_path: Path):
    """Verify validate_video_file checks size, headers, streams and duration."""
    from app.services.tiktok_shorts import ShortsCheckError, validate_video_file

    # Non-existent file
    with pytest.raises(ShortsCheckError) as exc_info:
        validate_video_file(tmp_path / "missing.mp4")
    assert exc_info.value.code == "FILE_NOT_FOUND"

    # Too small file (< 10 KB)
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"short bytes")
    with pytest.raises(ShortsCheckError) as exc_info:
        validate_video_file(tiny)
    assert exc_info.value.code == "FILE_TOO_SMALL"

    # HTML error page disguised as mp4
    html_file = tmp_path / "error.mp4"
    html_file.write_bytes(b"<!DOCTYPE html><html><body>Error 502" + b" " * 12000 + b"</body></html>")
    with pytest.raises(ShortsCheckError) as exc_info:
        validate_video_file(html_file)
    assert exc_info.value.code == "INVALID_MEDIA_FORMAT"

    # JSON error payload disguised as mp4
    json_file = tmp_path / "error.json"
    json_file.write_bytes(b'{"error": "Video not found", "padding": "' + b"A" * 12000 + b'"}')
    with pytest.raises(ShortsCheckError) as exc_info:
        validate_video_file(json_file)
    assert exc_info.value.code == "INVALID_MEDIA_FORMAT"

    # Valid file with mocked probe
    valid_file = tmp_path / "valid.mp4"
    valid_file.write_bytes(b"\x00\x00\x00 ftypisom" + b"\x00" * 15000)
    with patch("app.services.tiktok_shorts.probe_file") as mock_probe:
        mock_probe.return_value = {
            "duration": 30.0,
            "width": 720,
            "height": 1280,
            "is_vertical": True,
            "is_square": False,
            "is_landscape": False,
        }
        res = validate_video_file(valid_file)
        assert res["duration"] == 30.0
        assert res["is_vertical"] is True


def test_extract_download_url_quality_priority():
    """Verify _extract_download_url ignores MP3 audio and prefers MP4 HD."""
    from app.services.tiktok_media import _extract_download_url

    # Case 1: Dict with MP3 audio and MP4 HD
    payload = {
        "medias": {
            "MP3": {"url": "https://cdn.example.com/audio.mp3", "ext": "mp3", "type": "audio"},
            "MP4": {"url": "https://cdn.example.com/sd.mp4", "ext": "mp4"},
            "MP4 HD": {"url": "https://cdn.example.com/hd.mp4", "ext": "mp4"},
        }
    }
    assert _extract_download_url(payload) == "https://cdn.example.com/hd.mp4"

    # Case 2: Only MP3 available -> should not pick audio
    payload_audio_only = {
        "medias": {
            "MP3": {"url": "https://cdn.example.com/audio.mp3", "ext": "mp3", "type": "audio"}
        }
    }
    assert _extract_download_url(payload_audio_only) is None


async def test_global_publisher_resolves_via_shortcut(tmp_path: Path):
    """Verify _process_job resolves media via resolve_manual_media and publishes."""
    from app.services.tiktok_global_publisher import _process_job
    from app.services.tiktok_media import ManualResolvedMedia

    await pipelines.create_pipeline(pipeline_id="pl_pub_1", name="Pipe Pub", slug="pipe-pub-1", youtube_upload_mode="shorts")
    await destinations.create_destination(destination_id="dest_pub_1", pipeline_id="pl_pub_1", channel_id="yt_1", channel_name="Chan 1", connected=True)
    await sources.create_source(source_id="src_pub_1", pipeline_id="pl_pub_1", username="creator_1")
    await reels.insert_reel_if_new(
        reel_db_id="reel_pub_1", source_id="src_pub_1", reel_id="vid_1",
        reel_url="https://www.tiktok.com/@creator_1/video/111", caption="Test reel caption"
    )
    pub = await publications.create_publication(
        publication_id="pub_job_1", reel_db_id="reel_pub_1", destination_id="dest_pub_1", youtube_upload_mode="shorts"
    )
    await publish_queue.enqueue_publication_job(
        job_id="job_pub_1", pipeline_id="pl_pub_1", destination_id="dest_pub_1",
        reel_db_id="reel_pub_1", publication_id=pub["id"]
    )

    fake_video = tmp_path / "downloaded_test.mp4"
    fake_video.write_bytes(b"\x00\x00\x00 ftypisom" + b"\x00" * 15000)

    job = await publish_queue.get_job("job_pub_1")

    mock_resolved = ManualResolvedMedia(
        source_url="https://www.tiktok.com/@creator_1/video/111",
        download_url="https://cdn.example.com/test.mp4",
        content_type="video/mp4",
        caption="Resolved caption",
        thumbnail_url="https://cdn.example.com/thumb.jpg",
        duration=30.0,
        provider="shortcut",
    )

    with patch("app.services.tiktok_global_publisher.resolve_manual_media", new_callable=AsyncMock) as mock_res, \
         patch("app.services.tiktok_global_publisher.download_media", new_callable=AsyncMock) as mock_dl, \
         patch("app.services.tiktok_global_publisher.validate_video_file") as mock_val, \
         patch("app.services.tiktok_global_publisher.classify_upload_format") as mock_class, \
         patch("app.services.tiktok_global_publisher.generate_ai_metadata", new_callable=AsyncMock) as mock_ai, \
         patch("app.services.tiktok_global_publisher.publish_video_to_youtube", new_callable=AsyncMock) as mock_yt:

        mock_res.return_value = mock_resolved
        mock_dl.return_value = fake_video
        mock_val.return_value = {"duration": 30.0, "width": 1080, "height": 1920, "is_vertical": True, "is_square": False, "is_landscape": False}
        mock_class.return_value = ("shorts", True, "Đủ điều kiện Shorts", {"is_vertical": True, "is_square": False})
        mock_ai.return_value = {"title": "AI Title #Shorts", "description": "AI Desc", "hashtags_json": "[\"#Shorts\"]", "model": "gemini"}
        mock_yt.return_value = "YT_VID_SUCCESS_123"

        await _process_job(job)

        assert mock_res.called
        assert mock_dl.called
        assert mock_val.called
        assert mock_class.called
        assert mock_yt.called

    updated_pub = await publications.get_publication(pub["id"])
    assert updated_pub["status"] == "published"
    assert updated_pub["youtube_video_id"] == "YT_VID_SUCCESS_123"

    updated_reel = await reels.get_reel("reel_pub_1")
    assert updated_reel["status"] == "published"
    assert updated_reel["youtube_video_id"] == "YT_VID_SUCCESS_123"

    updated_job = await publish_queue.get_job("job_pub_1")
    assert updated_job["stage"] == "done"
