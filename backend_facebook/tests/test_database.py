import asyncio
import os
import sys
from pathlib import Path

from app.db.client import migrate
from app.db.repositories import pipelines, reels, scan_runs, sources, publications, destinations

TEST_DB_PATH = Path("/tmp/backend_facebook_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}?mode=rwc"


def setup_env() -> None:
    os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
    os.environ.setdefault("TURSO_DATABASE_URL", TEST_DB_URL)
    os.environ.setdefault("TURSO_AUTH_TOKEN", "test_token")


def teardown() -> None:
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


async def test_migration_runs() -> None:
    setup_env()
    try:
        await migrate()
    finally:
        teardown()


async def test_migration_idempotent() -> None:
    setup_env()
    try:
        await migrate()
        await migrate()
    finally:
        teardown()


async def test_migration_partial_state_recovers() -> None:
    """Simulate production partial state: columns exist but version rows missing."""
    from app.db.client import get_client

    setup_env()
    try:
        await migrate()
        client = get_client()
        # drop one version row but keep the column (partial-state simulation)
        await client.execute("DELETE FROM schema_migrations WHERE version = '20241003_04'")
        await migrate()  # must not fail with duplicate-column
        rows = await client.execute("SELECT version FROM schema_migrations ORDER BY id")
        versions = [r[0] for r in rows.rows]
        assert set(versions) == {"20241003_01", "20241003_02", "20241003_03", "20241003_04", "20241003_05"}
        await migrate()  # fully idempotent afterwards
    finally:
        teardown()


async def test_pipeline_repository() -> None:
    setup_env()
    try:
        await migrate()
        pipeline = await pipelines.create_pipeline(
            pipeline_id="pipeline-1",
            name="Test Pipeline",
            slug="test-pipeline",
        )
        assert pipeline["id"] == "pipeline-1"
        assert pipeline["name"] == "Test Pipeline"
        assert pipeline["slug"] == "test-pipeline"
        assert pipeline["enabled"] is True
        fetched = await pipelines.get_pipeline("pipeline-1")
        assert fetched is not None
        assert fetched["name"] == "Test Pipeline"
        all_pipelines = await pipelines.list_pipelines()
        assert len(all_pipelines) == 1
    finally:
        teardown()


async def test_source_repository() -> None:
    setup_env()
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        source = await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            page_id="123",
            page_name="Test Page",
            reels_url="https://facebook.com/test",
        )
        assert source["page_name"] == "Test Page"
        assert source["pipeline_id"] == "pipeline-1"
        fetched = await sources.get_source("source-1")
        assert fetched is not None
        assert fetched["page_id"] == "123"
        all_sources = await sources.list_sources("pipeline-1")
        assert len(all_sources) == 1
    finally:
        teardown()


async def test_reel_dedupe() -> None:
    setup_env()
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            page_id="123",
            page_name="Test Page",
        )
        status1, data1 = await reels.insert_reel_if_new(
            reel_db_id="reel-1",
            source_id="source-1",
            reel_id="fb-123",
            reel_url="https://facebook.com/reel/1",
            caption="First reel",
        )
        assert status1 == "INSERTED"
        assert data1["reel_id"] == "fb-123"
        status2, data2 = await reels.insert_reel_if_new(
            reel_db_id="reel-1",
            source_id="source-1",
            reel_id="fb-123",
            reel_url="https://facebook.com/reel/1",
            caption="First reel",
        )
        assert status2 == "ALREADY_EXISTS"
        assert data2["reel_id"] == "fb-123"
        status3, data3 = await reels.insert_reel_if_new(
            reel_db_id="reel-2",
            source_id="source-2",
            reel_id="fb-123",
            reel_url="https://facebook.com/reel/1",
            caption="First reel",
        )
        assert status3 == "INSERTED"
        assert data3["source_id"] == "source-2"
    finally:
        teardown()


async def test_reel_lifecycle() -> None:
    setup_env()
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            page_id="123",
            page_name="Test Page",
        )
        await reels.insert_reel_if_new(
            reel_db_id="reel-1",
            source_id="source-1",
            reel_id="fb-123",
        )
        fetched = await reels.get_reel("reel-1")
        assert fetched is not None
        assert fetched["status"] == "new"
        all_reels = await reels.list_reels("source-1")
        assert len(all_reels) == 1
        unpublished = await reels.list_unpublished_reels("source-1")
        assert len(unpublished) == 1
        total = await reels.count_reels("source-1")
        assert total == 1
        unpublished_count = await reels.count_unpublished("source-1")
        assert unpublished_count == 1
        published_count = await reels.count_published("source-1")
        assert published_count == 0
        await reels.update_reel_status("reel-1", "published")
        updated = await reels.get_reel("reel-1")
        assert updated is not None
        assert updated["status"] == "published"
        unpublished = await reels.list_unpublished_reels("source-1")
        assert len(unpublished) == 0
        published_count = await reels.count_published("source-1")
        assert published_count == 1
        fetched_after = await reels.get_reel("reel-1")
        assert fetched_after is not None
        assert fetched_after["status"] == "published"
    finally:
        teardown()


async def test_publication_unique_constraint() -> None:
    setup_env()
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            page_id="123",
            page_name="Test Page",
        )
        await reels.insert_reel_if_new(
            reel_db_id="reel-1",
            source_id="source-1",
            reel_id="fb-123",
        )
        await destinations.create_destination(
            destination_id="dest-1",
            pipeline_id="pipeline-1",
            channel_id="yt-123",
            channel_name="Test Channel",
        )
        await publications.create_publication(
            publication_id="pub-1",
            reel_db_id="reel-1",
            destination_id="dest-1",
            status="queued",
        )
        fetched = await publications.get_publication("pub-1")
        assert fetched is not None
        assert fetched["status"] == "queued"
        all_pubs = await publications.list_publications("dest-1")
        assert len(all_pubs) == 1
    finally:
        teardown()


async def test_scan_run_repository() -> None:
    setup_env()
    try:
        await migrate()
        await pipelines.create_pipeline(pipeline_id="pipeline-1", name="Test Pipeline", slug="test-pipeline")
        await sources.create_source(
            source_id="source-1",
            pipeline_id="pipeline-1",
            page_id="123",
            page_name="Test Page",
        )
        scan_run = await scan_runs.create_scan_run(
            scan_run_id="scan-1",
            source_id="source-1",
        )
        assert scan_run["status"] == "running"
        fetched = await scan_runs.get_scan_run("scan-1")
        assert fetched is not None
        await scan_runs.complete_scan_run(
            scan_run_id="scan-1",
            discovered_count=10,
            inserted_count=5,
            existing_count=5,
            status="completed",
        )
        updated = await scan_runs.get_scan_run("scan-1")
        assert updated is not None
        assert updated["discovered_count"] == 10
        assert updated["inserted_count"] == 5
        assert updated["status"] == "completed"
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
        ("publication unique", test_publication_unique_constraint),
        ("scan run repository", test_scan_run_repository),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            asyncio.run(fn())
            print(f"PASS {name}")
            passed += 1
        except Exception as e:
            print(f"FAIL {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
