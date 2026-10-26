"""Regression tests for TikTok Pipeline flow summary metrics:
- 26 active inventory reels (30 total - 4 excluded)
- Exclusion and active inventory separation
- Published video counts with valid YouTube Video ID (no duplicates)
- Queue breakdown: queued/scheduled/processing vs failed vs done/cancelled
- Multi-pipeline tenant isolation
- Cache invalidation upon state changes
"""

import pytest
from app.db.client import close_client, execute, migrate
from app.db.repositories import (
    destinations,
    pipelines,
    publications,
    publish_queue,
    reels,
    sources,
)
from app.routes.flow import pipeline_flow
from app.services.dashboard_cache import clear_all


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
    clear_all()
    yield
    await close_client()


@pytest.mark.asyncio
async def test_inventory_count_26_active_4_excluded():
    """Verify that 30 reels with 4 excluded reports exactly 26 active inventory."""
    pipe = await pipelines.create_pipeline(pipeline_id="p-test", name="Test Pipe", slug="test-pipe")
    src = await sources.create_source("s1", "p-test", "citrachoighelam_19")

    # Insert 30 reels
    reel_ids = []
    for i in range(30):
        _, row, _ = await reels.insert_reel_if_new(
            source_id="s1",
            reel_id=f"reel_{i}",
            caption=f"Video #{i}",
            duration=60,
        )
        reel_ids.append(row["id"])

    # Exclude 4 reels
    for i in range(4):
        await reels.exclude_reel(reel_ids[i], pipeline_id="p-test")

    # Check flow metrics
    flow_data = await pipeline_flow("p-test")
    assert flow_data["inventory"] == 26
    assert flow_data["inventory_count"] == 26
    assert flow_data["summary"]["inventory"] == 26
    assert flow_data["summary"]["total_reels"] == 30
    assert flow_data["summary"]["excluded_count"] == 4
    assert flow_data["summary"]["unpublished"] == 26


@pytest.mark.asyncio
async def test_published_and_failed_queue_metrics():
    """Verify published video count requires valid YouTube Video ID and queue breakdown."""
    pipe = await pipelines.create_pipeline(pipeline_id="p-pub", name="Pub Pipe", slug="pub-pipe")
    src = await sources.create_source("s-pub", "p-pub", "creator_pub")
    dest = await destinations.create_destination(
        destination_id="dest-1",
        pipeline_id="p-pub",
        channel_name="Test Channel",
        channel_id="UC_test",
        connected=True,
    )

    # Insert 5 reels
    created_reels = []
    for i in range(5):
        _, row, _ = await reels.insert_reel_if_new(
            source_id="s-pub",
            reel_id=f"r_{i}",
            caption=f"Reel {i}",
        )
        created_reels.append(row["id"])

    # Reel 0: successfully published with valid youtube_video_id
    await reels.mark_reel_published(created_reels[0], youtube_video_id="yt_vid_001")
    await publications.create_publication(
        publication_id="pub_0",
        reel_db_id=created_reels[0],
        destination_id="dest-1",
        status="published",
        youtube_video_id="yt_vid_001",
    )

    # Reel 1: status published but empty youtube_video_id -> NOT counted as published
    await execute(
        "UPDATE tiktok_reels SET status = 'published', youtube_video_id = '' WHERE id = :id",
        {"id": created_reels[1]},
    )

    # Queue jobs:
    # 1 job failed
    await publish_queue.enqueue_publication_job(
        job_id="job_failed",
        pipeline_id="p-pub",
        destination_id="dest-1",
        reel_db_id=created_reels[2],
        publication_id="pub_2",
    )
    await publish_queue.complete_job("job_failed", status="failed", error="Media error")

    # 1 job queued
    await publish_queue.enqueue_publication_job(
        job_id="job_queued",
        pipeline_id="p-pub",
        destination_id="dest-1",
        reel_db_id=created_reels[3],
        publication_id="pub_3",
    )

    # 1 job done (should not be in queued)
    await publish_queue.enqueue_publication_job(
        job_id="job_done",
        pipeline_id="p-pub",
        destination_id="dest-1",
        reel_db_id=created_reels[4],
        publication_id="pub_4",
    )
    await publish_queue.complete_job("job_done", status="done")

    flow_data = await pipeline_flow("p-pub")
    assert flow_data["inventory"] == 5
    assert flow_data["published"] == 1
    assert flow_data["queued"] == 1
    assert flow_data["failed"] == 1
    assert flow_data["summary"]["published"] == 1
    assert flow_data["summary"]["queued"] == 1
    assert flow_data["summary"]["failed"] == 1


@pytest.mark.asyncio
async def test_multi_pipeline_tenant_isolation():
    """Verify metrics for pipeline A and pipeline B do not leak into each other."""
    # Pipeline A: 10 active reels, 1 failed job
    await pipelines.create_pipeline(pipeline_id="pipe-A", name="Pipe A", slug="pipe-a")
    src_a = await sources.create_source("src-a", "pipe-A", "user_a")
    for i in range(10):
        await reels.insert_reel_if_new(source_id="src-a", reel_id=f"a_{i}", caption=f"Caption A {i}")
    await publish_queue.enqueue_publication_job("job-a-1", "pipe-A", "dest-a", "a_0", "pub-a-0")
    await publish_queue.complete_job("job-a-1", status="failed", error="Error A")

    # Pipeline B: 5 active reels, 2 queued jobs, 0 failed
    await pipelines.create_pipeline(pipeline_id="pipe-B", name="Pipe B", slug="pipe-b")
    src_b = await sources.create_source("src-b", "pipe-B", "user_b")
    for i in range(5):
        await reels.insert_reel_if_new(source_id="src-b", reel_id=f"b_{i}", caption=f"Caption B {i}")
    await publish_queue.enqueue_publication_job("job-b-1", "pipe-B", "dest-b", "b_0", "pub-b-0")
    await publish_queue.enqueue_publication_job("job-b-2", "pipe-B", "dest-b", "b_1", "pub-b-1")

    # Verify Pipe A
    flow_a = await pipeline_flow("pipe-A")
    assert flow_a["inventory"] == 10
    assert flow_a["failed"] == 1
    assert flow_a["queued"] == 0
    assert flow_a["published"] == 0

    # Verify Pipe B
    flow_b = await pipeline_flow("pipe-B")
    assert flow_b["inventory"] == 5
    assert flow_b["failed"] == 0
    assert flow_b["queued"] == 2
    assert flow_b["published"] == 0


@pytest.mark.asyncio
async def test_cache_invalidation_on_reel_exclude_and_restore():
    """Verify that excluding or restoring reels invalidates flow cache immediately."""
    from app.routes.inventory import delete_reel, restore_reel

    pipe = await pipelines.create_pipeline(pipeline_id="pipe-cache", name="Cache Pipe", slug="cache-pipe")
    await sources.create_source("src-cache", "pipe-cache", "user_cache")

    _, r1, _ = await reels.insert_reel_if_new(source_id="src-cache", reel_id="c_1", caption="Video C1")
    _, r2, _ = await reels.insert_reel_if_new(source_id="src-cache", reel_id="c_2", caption="Video C2")

    # 1. First fetch -> cache 2
    f1 = await pipeline_flow("pipe-cache")
    assert f1["inventory"] == 2

    # 2. Exclude r1 via inventory endpoint
    await delete_reel(r1["id"], pipeline_id="pipe-cache")

    # 3. Next fetch must immediately reflect 1 without stale cache
    f2 = await pipeline_flow("pipe-cache")
    assert f2["inventory"] == 1
    assert f2["summary"]["excluded_count"] == 1

    # 4. Restore r1 via inventory endpoint
    await restore_reel(r1["id"], pipeline_id="pipe-cache")

    # 5. Next fetch must immediately reflect 2
    f3 = await pipeline_flow("pipe-cache")
    assert f3["inventory"] == 2
    assert f3["summary"]["excluded_count"] == 0
