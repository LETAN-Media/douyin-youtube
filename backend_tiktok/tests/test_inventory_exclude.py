"""Tests for TikTok Inventory Deletion/Exclusion, Bulk Actions, Pipeline Scoping, and Restoration."""

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
from app.services import tiktok_scheduler


@pytest.fixture(autouse=True)
async def setup_test_db():
    await migrate()
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


@pytest.mark.asyncio
async def test_exclude_single_reel_and_restore():
    """Test excluding a single reel and restoring it."""
    # Setup pipeline and source
    pipe = await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")

    # Insert reel
    status, row, _ = await reels.insert_reel_if_new(
        source_id=src["id"],
        reel_id="v1",
        caption="Video 1",
        duration=30,
    )
    assert status == "INSERTED"
    reel_id = row["id"]

    # Exclude
    res = await reels.exclude_reel(reel_id, pipeline_id="p1")
    assert res["ok"] is True
    assert res["status"] == "excluded"
    assert res["previous_status"] == "new"

    # Verify in DB
    updated = await reels.get_reel(reel_id)
    assert updated["status"] == "excluded"
    assert updated["previous_status"] == "new"

    # Restore
    rest_res = await reels.restore_reel(reel_id, pipeline_id="p1")
    assert rest_res["ok"] is True
    assert rest_res["status"] == "new"

    # Verify restored in DB
    restored = await reels.get_reel(reel_id)
    assert restored["status"] == "new"
    assert restored["previous_status"] is None


@pytest.mark.asyncio
async def test_exclude_pipeline_isolation():
    """Verify cannot exclude a reel belonging to a different pipeline."""
    # Pipeline 1 and 2
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    await pipelines.create_pipeline(pipeline_id="p2", name="Pipe 2", slug="pipe-2")

    src1 = await sources.create_source("s1", "p1", "creator1")
    _, row, _ = await reels.insert_reel_if_new(source_id=src1["id"], reel_id="v1")
    reel_id = row["id"]

    # Attempt to exclude from p2
    res = await reels.exclude_reel(reel_id, pipeline_id="p2")
    assert res["ok"] is False
    assert res["error_code"] == "PIPELINE_MISMATCH"

    # Reel remains untouched
    r = await reels.get_reel(reel_id)
    assert r["status"] == "new"


@pytest.mark.asyncio
async def test_exclude_busy_processing_reel_rejected():
    """Verify video currently in 'processing' status cannot be excluded."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")
    _, row, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="v1")
    reel_id = row["id"]

    # Mark as processing
    await reels.update_reel_status(reel_id, "processing")

    res = await reels.exclude_reel(reel_id, pipeline_id="p1")
    assert res["ok"] is False
    assert res["error_code"] == "PROCESSING"

    # Reel is still processing
    r = await reels.get_reel(reel_id)
    assert r["status"] == "processing"


@pytest.mark.asyncio
async def test_exclude_cancels_queued_job():
    """Verify excluding a reel that has a queued job cancels the queue job."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")
    dest = await destinations.create_destination("d1", "p1", channel_id="UC1", connected=True)
    _, row, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="v1")
    reel_id = row["id"]

    # Create publication & queue job
    pub = await publications.create_publication(
        publication_id="pub_1",
        reel_db_id=reel_id,
        destination_id=dest["id"],
        status="queued",
    )
    job = await publish_queue.enqueue_publication_job(
        job_id="job_1",
        pipeline_id="p1",
        destination_id=dest["id"],
        reel_db_id=reel_id,
        publication_id=pub["id"],
    )

    # Exclude reel
    res = await reels.exclude_reel(reel_id, pipeline_id="p1")
    assert res["ok"] is True

    # Check queue job is cancelled
    q_job = await publish_queue.get_job(job["id"])
    assert q_job["status"] == "cancelled"

    # Check publication is cancelled
    p_row = await publications.get_publication(pub["id"])
    assert p_row["status"] == "cancelled"


@pytest.mark.asyncio
async def test_exclude_published_reel_preserves_history():
    """Verify excluding an already-published reel preserves youtube_video_id and publication."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")
    dest = await destinations.create_destination("d1", "p1", channel_id="UC1", connected=True)
    _, row, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="v1")
    reel_id = row["id"]

    # Mark as published
    await reels.mark_reel_published(reel_id, youtube_video_id="YT_VIDEO_123")
    pub = await publications.create_publication(
        publication_id="pub_2",
        destination_id=dest["id"],
        reel_db_id=reel_id,
        status="published",
        youtube_video_id="YT_VIDEO_123",
    )

    # Exclude
    res = await reels.exclude_reel(reel_id, pipeline_id="p1")
    assert res["ok"] is True
    assert res["status"] == "excluded"
    assert res["previous_status"] == "published"

    # Reel still has youtube_video_id
    r = await reels.get_reel(reel_id)
    assert r["youtube_video_id"] == "YT_VIDEO_123"

    # Publication row is completely preserved and still published
    p = await publications.get_publication(pub["id"])
    assert p["status"] == "published"
    assert p["youtube_video_id"] == "YT_VIDEO_123"


@pytest.mark.asyncio
async def test_bulk_exclude_and_bulk_restore():
    """Test bulk exclude and restore across multiple reels."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")

    ids = []
    for i in range(5):
        _, r, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"v{i}", caption=f"Vid {i}")
        ids.append(r["id"])

    # Bulk exclude first 3
    res = await reels.bulk_exclude_reels("p1", ids[:3])
    assert res["ok"] is True
    assert res["excluded"] == 3
    assert len(res["rejected"]) == 0

    # Verify first 3 are excluded, remaining 2 are new
    for rid in ids[:3]:
        r = await reels.get_reel(rid)
        assert r["status"] == "excluded"
    for rid in ids[3:]:
        r = await reels.get_reel(rid)
        assert r["status"] == "new"

    # Bulk restore 2 of the excluded
    res_rest = await reels.bulk_restore_reels("p1", ids[:2])
    assert res_rest["ok"] is True
    assert res_rest["restored"] == 2

    r0 = await reels.get_reel(ids[0])
    r1 = await reels.get_reel(ids[1])
    r2 = await reels.get_reel(ids[2])
    assert r0["status"] == "new"
    assert r1["status"] == "new"
    assert r2["status"] == "excluded"


@pytest.mark.asyncio
async def test_rescan_does_not_reinsert_excluded_video():
    """Verify that when scanner runs again, an excluded video is NOT re-inserted or reset."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")
    _, row, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="tiktok_999")
    reel_id = row["id"]

    # Exclude video
    await reels.exclude_reel(reel_id, pipeline_id="p1")
    r_before = await reels.get_reel(reel_id)
    assert r_before["status"] == "excluded"

    # Simulate scanner re-encountering the same video
    status, existing_row, new_row = await reels.insert_reel_if_new(
        source_id=src["id"],
        reel_id="tiktok_999",
        caption="New Caption from scan",
    )
    assert status in ("ALREADY_EXISTS", "UPDATED_CAPTION")
    assert new_row is None

    # Status must STILL be 'excluded', NOT 'new'
    r_after = await reels.get_reel(reel_id)
    assert r_after["status"] == "excluded"


@pytest.mark.asyncio
async def test_scheduler_ignores_excluded_reels():
    """Verify Auto Scheduler ignores excluded reels and only schedules active reels."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1", auto_publish=True)
    src = await sources.create_source("s1", "p1", "creator1")
    dest = await destinations.create_destination("d1", "p1", channel_id="UC1", connected=True)
    await schedules.get_or_create_schedule(
        pipeline_id="p1",
        timezone="Asia/Ho_Chi_Minh",
        max_daily=5,
    )
    await schedules.set_schedule_enabled("p1", True)

    # Insert 2 reels: 1 excluded, 1 new
    _, r_exc, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="v_exc", duration=30)
    await reels.exclude_reel(r_exc["id"], pipeline_id="p1")

    _, r_valid, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="v_valid", duration=40)

    # Run daily batch
    batch_res = await tiktok_scheduler.execute_daily_batch("p1", force_now=True)
    assert batch_res["ok"] is True
    # Only 1 video should be scheduled (the valid one)
    assert batch_res["videos_enqueued"] == 1

    # Verify the scheduled video is v_valid
    jobs = await publish_queue.list_queue_for_pipeline("p1")
    assert len(jobs) == 1
    assert jobs[0]["reel_db_id"] == r_valid["id"]

    # Excluded reel remains excluded and untouched
    exc_check = await reels.get_reel(r_exc["id"])
    assert exc_check["status"] == "excluded"


@pytest.mark.asyncio
async def test_inventory_filter_separation():
    """Verify in-stock, excluded, and all video counting and separation."""
    await pipelines.create_pipeline(pipeline_id="p1", name="Pipe 1", slug="pipe-1")
    src = await sources.create_source("s1", "p1", "creator1")

    # Insert 3 reels
    _, r1, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="vid_1")
    _, r2, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="vid_2")
    _, r3, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="vid_3")

    # Exclude 1 reel
    await reels.exclude_reel(r2["id"], pipeline_id="p1")

    # Counts
    total = await reels.count_reels(src["id"])
    excluded_cnt = await reels.count_excluded(src["id"])
    unpublished_cnt = await reels.count_unpublished(src["id"])

    assert total == 3
    assert excluded_cnt == 1
    assert unpublished_cnt == 2

    # Query pipeline inventory with status filter
    all_reels = await reels.list_reels_for_pipeline("p1")
    assert len(all_reels) == 3

    excluded_reels = await reels.list_reels_for_pipeline("p1", status="excluded")
    assert len(excluded_reels) == 1
    assert excluded_reels[0]["id"] == r2["id"]

