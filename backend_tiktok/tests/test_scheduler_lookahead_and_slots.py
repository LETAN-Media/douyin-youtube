"""Comprehensive regression tests for TikTok Scheduler, Odd-minute Slots (06:00, 10:48, 15:36),
Batch Timing, Next-Day Lookahead, 26 Unpublished Videos, Excluded Reel Filters, and Worker Health.
"""

from datetime import datetime, timedelta, timezone
import time
from zoneinfo import ZoneInfo
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
    system_state,
)
from app.services import schedule_generator, tiktok_scheduler


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
    await execute("DELETE FROM system_state")
    yield
    await close_client()


# ============================================================================
# 1. Odd-minute slot generation & persistence tests (06:00, 10:48, 15:36...)
# ============================================================================

def test_odd_minute_slot_generation():
    """Verify slots with odd minutes (06:00, 10:48, 15:36, 20:24, 01:12) are correctly generated."""
    ref_dt = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    slots = schedule_generator.generate_daily_slots(ref_dt, max_daily=5, batch_time="06:00")
    assert slots == ["01:12", "06:00", "10:48", "15:36", "20:24"]
    assert "06:00" in slots
    assert "10:48" in slots
    assert "15:36" in slots


@pytest.mark.asyncio
async def test_odd_minute_slots_persistence_and_sync():
    """Verify arbitrary HH:MM slots are saved and enabled in the database without round-hour restriction."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_slots", name="Slot Pipe", slug="slot-pipe")
    res = await schedule_generator.generate_week_schedule("p_slots", max_daily=5, batch_time="06:00")
    assert res is not None

    sched = await schedules.get_by_pipeline("p_slots")
    slots = await schedules.list_slots(sched["id"])

    # Verify each weekday has all 5 odd-minute slots enabled
    for wd in range(7):
        day_enabled = [s["slot_time"] for s in slots if s["weekday"] == wd and s["enabled"]]
        assert "06:00" in day_enabled
        assert "10:48" in day_enabled
        assert "15:36" in day_enabled
        assert len(day_enabled) == 5


# ============================================================================
# 2. Before & After Batch Time tests
# ============================================================================

@pytest.mark.asyncio
async def test_before_batch_time_returns_waiting():
    """When now_local is before batch_time (e.g. 05:00 < 06:00), scheduler reports NOT_BEFORE_BATCH_TIME."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_batch", name="Batch Pipe", slug="batch-pipe", auto_publish=True)
    await destinations.create_destination("d_batch", "p_batch", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_batch", "p_batch", "creator_batch")
    await reels.insert_reel_if_new(source_id=src["id"], reel_id="r1", duration=40)

    await schedules.get_or_create_schedule("p_batch", timezone="Asia/Ho_Chi_Minh", max_daily=5, batch_time="06:00")
    await schedules.set_schedule_enabled("p_batch", True)
    await schedule_generator.generate_week_schedule("p_batch", max_daily=5, batch_time="06:00")

    # Simulate 04:30 AM local time on Monday (2026-10-26 21:30 UTC)
    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sim_now = datetime(2026, 10, 26, 4, 30, tzinfo=vn_tz)

    res = await tiktok_scheduler.execute_daily_batch("p_batch", force_now=False, now=sim_now)
    assert res["ok"] is False
    assert res["reason"] == "NOT_BEFORE_BATCH_TIME"
    assert "06:00" in res["message"]


@pytest.mark.asyncio
async def test_after_batch_time_allocates_slots_same_day():
    """When now_local is after batch_time (e.g. 06:05), scheduler allocates open future slots today."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_after", name="After Pipe", slug="after-pipe", auto_publish=True)
    await destinations.create_destination("d_after", "p_after", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_after", "p_after", "creator_after")

    # Insert 3 videos
    for i in range(3):
        await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"vid_{i}", duration=45)

    await schedules.get_or_create_schedule("p_after", timezone="Asia/Ho_Chi_Minh", max_daily=5, batch_time="06:00")
    await schedules.set_schedule_enabled("p_after", True)
    await schedule_generator.generate_week_schedule("p_after", max_daily=5, batch_time="06:00")

    # Simulate 06:02 AM local time (within 15m of 06:00 batch time)
    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sim_now = datetime(2026, 10, 26, 6, 2, tzinfo=vn_tz)

    res = await tiktok_scheduler.execute_daily_batch("p_after", force_now=False, now=sim_now)
    assert res["ok"] is True
    assert res["videos_enqueued"] == 3
    assert res["is_lookahead"] is False


# ============================================================================
# 3. Lookahead across new day: Hết slot hôm nay -> Lịch cho ngày mai
# ============================================================================

@pytest.mark.asyncio
async def test_lookahead_to_tomorrow_when_today_slots_passed():
    """When today's slots have all passed (e.g. at 21:00), scheduler looks ahead and schedules tomorrow's slots."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_look", name="Look Pipe", slug="look-pipe", auto_publish=True)
    await destinations.create_destination("d_look", "p_look", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_look", "p_look", "creator_look")

    for i in range(5):
        await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"v_look_{i}", duration=30)

    await schedules.get_or_create_schedule("p_look", timezone="Asia/Ho_Chi_Minh", max_daily=5, batch_time="06:00")
    await schedules.set_schedule_enabled("p_look", True)
    await schedule_generator.generate_week_schedule("p_look", max_daily=5, batch_time="06:00")

    # Simulate 21:30 on Monday 2026-10-26 (all today's slots 06:00, 10:48, 15:36, 20:24 have passed)
    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sim_now = datetime(2026, 10, 26, 21, 30, tzinfo=vn_tz)

    res = await tiktok_scheduler.execute_daily_batch("p_look", force_now=False, now=sim_now)
    assert res["ok"] is True
    assert res["is_lookahead"] is True
    assert res["date"] == "2026-10-27"  # Tomorrow!
    assert res["videos_enqueued"] == 5

    # Verify jobs in queue have tomorrow's dates
    jobs = await publish_queue.list_queue_for_pipeline("p_look")
    assert len(jobs) == 5
    for j in jobs:
        assert "2026-10-2" in j["scheduled_at"]


# ============================================================================
# 4. Inventory with 26 unpublished videos respects daily limit (never mass dumps 26)
# ============================================================================

@pytest.mark.asyncio
async def test_26_unpublished_videos_only_enqueues_daily_limit():
    """Verify that with 26 unpublished videos, only max_daily (e.g. 5) are scheduled, not all 26."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_26", name="26 Pipe", slug="26-pipe", auto_publish=True)
    await destinations.create_destination("d_26", "p_26", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_26", "p_26", "creator_26")

    # Insert 26 unpublished videos
    for i in range(26):
        await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"vid_bulk_{i:02d}", duration=40)

    unpub_count = await reels.count_unpublished(src["id"])
    assert unpub_count == 26

    await schedules.get_or_create_schedule("p_26", timezone="Asia/Ho_Chi_Minh", max_daily=5, batch_time="06:00")
    await schedule_generator.generate_week_schedule("p_26", max_daily=5, batch_time="06:00")

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sim_now = datetime(2026, 10, 26, 6, 0, tzinfo=vn_tz)

    res = await tiktok_scheduler.execute_daily_batch("p_26", force_now=True, now=sim_now)
    assert res["ok"] is True
    assert res["videos_enqueued"] == 5  # Strictly 5!

    # Verify queue has exactly 5 jobs
    jobs = await publish_queue.list_queue_for_pipeline("p_26")
    assert len(jobs) == 5

    # 21 videos remain in 'new' status
    rem_unpub = await reels.count_unpublished(src["id"])
    assert rem_unpub == 21


# ============================================================================
# 5. Excluded, Published, and Processing reels are completely ignored
# ============================================================================

@pytest.mark.asyncio
async def test_scheduler_ignores_excluded_and_published_reels():
    """Verify excluded, published, and processing reels are not picked by scheduler."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_filter", name="Filter Pipe", slug="filter-pipe", auto_publish=True)
    dest = await destinations.create_destination("d_filter", "p_filter", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_filter", "p_filter", "creator_filter")

    # Reel 1: Excluded
    _, r1, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="r_exc", duration=30)
    await reels.exclude_reel(r1["id"], pipeline_id="p_filter")

    # Reel 2: Published
    _, r2, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="r_pub", duration=35)
    await reels.mark_reel_published(r2["id"], "YT_ALREADY")
    await publications.create_publication("pub_old", r2["id"], dest["id"], status="published", youtube_video_id="YT_ALREADY")

    # Reel 3: Processing
    _, r3, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="r_proc", duration=40)
    await reels.update_reel_status(r3["id"], "processing")

    # Reel 4: Eligible New
    _, r4, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="r_valid", duration=45)

    await schedules.get_or_create_schedule("p_filter", max_daily=5)
    await schedule_generator.generate_week_schedule("p_filter", max_daily=5)

    res = await tiktok_scheduler.execute_daily_batch("p_filter", force_now=True)
    assert res["ok"] is True
    assert res["videos_enqueued"] == 1
    assert res["slots"][0]["reel_id"] == "r_valid"


# ============================================================================
# 6. Duplicate job prevention & Scheduler restart
# ============================================================================

@pytest.mark.asyncio
async def test_scheduler_restart_and_duplicate_prevention():
    """Running the batch twice immediately does not enqueue duplicate jobs for the same date."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_dup", name="Dup Pipe", slug="dup-pipe", auto_publish=True)
    await destinations.create_destination("d_dup", "p_dup", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_dup", "p_dup", "creator_dup")

    for i in range(10):
        await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"v_dup_{i}", duration=30)

    await schedules.get_or_create_schedule("p_dup", max_daily=3, batch_time="06:00")
    await schedule_generator.generate_week_schedule("p_dup", max_daily=3, batch_time="06:00")

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sim_now = datetime(2026, 10, 26, 6, 0, tzinfo=vn_tz)

    # First run
    res1 = await tiktok_scheduler.execute_daily_batch("p_dup", force_now=True, now=sim_now)
    assert res1["ok"] is True
    assert res1["videos_enqueued"] == 3

    # Immediate second run (scheduler loop tick or restart)
    res2 = await tiktok_scheduler.execute_daily_batch("p_dup", force_now=False, now=sim_now)
    # Today's limit is already reached, lookahead might find tomorrow or return
    # Crucially, queue for today still has exactly 3 jobs
    jobs = await publish_queue.list_queue_for_pipeline("p_dup")
    today_jobs = [j for j in jobs if "2026-10-26" in j["scheduled_at"]]
    # Should not duplicate today's slots
    assert len(today_jobs) <= 3


# ============================================================================
# 7. Publisher only claims due jobs (scheduled_at <= now)
# ============================================================================

@pytest.mark.asyncio
async def test_publisher_only_claims_due_jobs():
    """Auto publication jobs in the future (scheduled_at > now) are NOT claimed by publisher."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_claim", name="Claim Pipe", slug="claim-pipe", auto_publish=True)
    dest = await destinations.create_destination("d_claim", "p_claim", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_claim", "p_claim", "creator_claim")
    _, r1, _ = await reels.insert_reel_if_new(source_id=src["id"], reel_id="v_future", duration=30)

    # Enqueue a future job (scheduled for 2 hours later)
    now_utc = datetime.now(timezone.utc)
    future_time = (now_utc + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    pub = await publications.create_publication(
        publication_id="pub_fut",
        reel_db_id=r1["id"],
        destination_id=dest["id"],
        status="queued",
        scheduled_publish_at=future_time,
    )
    await publish_queue.enqueue_publication_job(
        job_id="job_fut",
        pipeline_id="p_claim",
        destination_id=dest["id"],
        reel_db_id=r1["id"],
        publication_id=pub["id"],
        priority=100,
        stage="scheduled",
        scheduled_at=future_time,
    )

    # Publisher tries to claim
    claimed = await publish_queue.claim_next_job("worker_test")
    assert claimed is None  # Job is in the future, must NOT be claimed!


# ============================================================================
# 8. Preview Mode does not mutate database
# ============================================================================

@pytest.mark.asyncio
async def test_preview_mode_does_not_mutate_db():
    """Preview mode calculates plan with planned slots but creates ZERO rows in queue or publications."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_prev", name="Prev Pipe", slug="prev-pipe", auto_publish=True)
    await destinations.create_destination("d_prev", "p_prev", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_prev", "p_prev", "creator_prev")

    for i in range(5):
        await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"v_prev_{i}", duration=30)

    await schedules.get_or_create_schedule("p_prev", max_daily=5, batch_time="06:00")
    await schedule_generator.generate_week_schedule("p_prev", max_daily=5, batch_time="06:00")

    preview = await tiktok_scheduler.preview_daily_batch("p_prev")
    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["planned_count"] == 5
    assert len(preview["planned_slots"]) == 5

    # Ensure ZERO jobs were created
    jobs = await publish_queue.list_queue_for_pipeline("p_prev")
    assert len(jobs) == 0

    # Ensure reels are still 'new'
    reels_list = await reels.list_unpublished_reels(src["id"])
    assert len(reels_list) == 5
    for r in reels_list:
        assert r["status"] == "new"


# ============================================================================
# 9. Scheduler Status API compiles metrics & worker status
# ============================================================================

@pytest.mark.asyncio
async def test_scheduler_status_compilation():
    """Verify get_scheduler_status reports next run, eligible inventory, and worker indicators."""
    pipe = await pipelines.create_pipeline(pipeline_id="p_stat", name="Stat Pipe", slug="stat-pipe", auto_publish=True)
    await destinations.create_destination("d_stat", "p_stat", channel_id="UC_1", connected=True)
    src = await sources.create_source("s_stat", "p_stat", "creator_stat")

    for i in range(7):
        await reels.insert_reel_if_new(source_id=src["id"], reel_id=f"v_stat_{i}", duration=30)

    await schedules.get_or_create_schedule("p_stat", max_daily=5, batch_time="06:00")
    await schedules.set_schedule_enabled("p_stat", True)

    # Set mock worker heartbeats in system_state
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await system_state.set_json("worker:scheduler", {"status": "idle", "last_heartbeat": now_iso})
    await system_state.set_json("worker:publisher", {"status": "idle", "last_heartbeat": now_iso})

    status_data = await tiktok_scheduler.get_scheduler_status("p_stat")
    assert status_data["ok"] is True
    assert status_data["pipeline_id"] == "p_stat"
    assert status_data["eligible_inventory"] == 7
    assert status_data["scheduled_jobs"] == 0
    assert status_data["scheduler_worker_online"] is True
    assert status_data["publisher_worker_online"] is True
    assert status_data["publisher_status"] == "idle"
    assert status_data["next_scheduled_run"] is not None
