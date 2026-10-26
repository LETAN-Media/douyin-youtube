import asyncio
import os
import sys
from pathlib import Path

# Set env vars BEFORE importing app modules (settings loads at import time)
TEST_DB_PATH = Path("/tmp/tiktok_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"

os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
os.environ.setdefault("TURSO_DATABASE_URL", TEST_DB_URL)
os.environ.setdefault("TURSO_TOKEN", "test_token")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.client import migrate, get_client, execute, close_client
from app.db.repositories import pipelines, reels, scan_runs, sources, publications, destinations, publish_queue


def teardown() -> None:
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def reset_client() -> None:
    from app.db import client as db_client

    db_client._client = None


async def test_migration_runs() -> None:
    try:
        await migrate()
        indexes = await get_client().execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_tiktok_reels_source_status_discovered'"
        )
        assert indexes.rows
    finally:
        teardown()


async def test_migration_idempotent() -> None:
    try:
        await migrate()
        await migrate()
    finally:
        teardown()


async def test_pipeline_repository() -> None:
    try:
        await migrate()
        pipeline = await pipelines.create_pipeline(
            pipeline_id="pipeline-1",
            name="Test Pipeline",
            slug="test-pipeline",
        )
        assert pipeline["id"] == "pipeline-1"
        assert pipeline["name"] == "Test Pipeline"
        assert pipeline["auto_publish"] == 1
        fetched = await pipelines.get_pipeline("pipeline-1")
        assert fetched is not None
        assert fetched["name"] == "Test Pipeline"
        all_pipelines = await pipelines.list_pipelines()
        assert len(all_pipelines) == 1
    finally:
        teardown()


async def test_source_repository() -> None:
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        source = await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            username="tiktok_user",
            display_name="Test User",
        )
        assert source["username"] == "tiktok_user"
        assert source["pipeline_id"] == "pipeline-1"
        fetched = await sources.get_source("source-1")
        assert fetched is not None
        assert fetched["username"] == "tiktok_user"
        all_sources = await sources.list_sources("pipeline-1")
        assert len(all_sources) == 1
    finally:
        teardown()


async def test_reel_dedupe() -> None:
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            username="tiktok_user",
        )
        status1, data1, _ = await reels.insert_reel_if_new(
            reel_db_id="reel-1",
            source_id="source-1",
            reel_id="tt-12345",
            reel_url="https://www.tiktok.com/@user/video/12345",
            caption="First reel",
        )
        assert status1 == "INSERTED"
        assert data1["reel_id"] == "tt-12345"

        status2, data2, _ = await reels.insert_reel_if_new(
            reel_db_id="reel-2",
            source_id="source-1",
            reel_id="tt-12345",
            reel_url="https://www.tiktok.com/@user/video/12345",
            caption="First reel",
        )
        assert status2 == "ALREADY_EXISTS"
        assert data2["reel_id"] == "tt-12345"

        status3, _, _ = await reels.insert_reel_if_new(
            reel_db_id="reel-3",
            source_id="source-2",
            reel_id="tt-12345",
        )
        assert status3 == "INSERTED"
    finally:
        teardown()


async def test_reel_lifecycle() -> None:
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            username="tiktok_user",
        )
        await reels.insert_reel_if_new(
            reel_db_id="reel-1",
            source_id="source-1",
            reel_id="tt-12345",
        )
        fetched = await reels.get_reel("reel-1")
        assert fetched is not None
        assert fetched["status"] == "new"

        await reels.update_reel_status("reel-1", "published")
        updated = await reels.get_reel("reel-1")
        assert updated["status"] == "published"
        assert await reels.count_published("source-1") == 1
        assert await reels.count_unpublished("source-1") == 0
    finally:
        teardown()


async def test_publish_queue_claim() -> None:
    """Enqueue a job, claim it, verify the worker_id field is set."""
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test", slug="test-1")
        await sources.create_source(
            source_id="source-1", pipeline_id="pipeline-1", username="user"
        )
        await reels.insert_reel_if_new(
            reel_db_id="reel-1", source_id="source-1", reel_id="tt-1"
        )
        await destinations.create_destination(
            destination_id="dest-1", pipeline_id="pipeline-1",
            channel_id="yt-1", channel_name="Test",
        )
        await publications.create_publication(
            publication_id="pub-1", reel_db_id="reel-1",
            destination_id="dest-1", status="queued",
        )
        await publish_queue.enqueue_publication_job(
            job_id="job-1", pipeline_id="p1", destination_id="dest-1",
            reel_db_id="reel-1", publication_id="pub-1", priority=0,
        )
        claimed = await publish_queue.claim_next_job("worker-1")
        assert claimed is not None
        assert claimed["publication_id"] == "pub-1"
        assert claimed["worker_id"] == "worker-1"
        # Second claim should return None
        claimed2 = await publish_queue.claim_next_job("worker-2")
        assert claimed2 is None
    finally:
        teardown()


def run_tests() -> None:
    tests = [
        ("migration runs", test_migration_runs),
        ("migration idempotent", test_migration_idempotent),
        ("pipeline repository", test_pipeline_repository),
        ("source repository", test_source_repository),
        ("reel dedupe", test_reel_dedupe),
        ("reel lifecycle", test_reel_lifecycle),
        ("publish queue claim", test_publish_queue_claim),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        reset_client()
        try:
            asyncio.run(fn())
            print(f"PASS {name}")
            passed += 1
        except Exception as e:
            import traceback

            print(f"FAIL {name}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
