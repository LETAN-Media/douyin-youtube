"""Regression tests for pipeline_flow_state endpoint (P0 fix).

Verifies:
1. SQLAlchemy case() compiles and executes cleanly on SQLite/libsql without
   'ValueError: Unsupported parameter type' or SQL syntax errors.
2. today_published counts only publications published today (>= today_start UTC).
3. last_published_at returns the correct ISO string for the latest publication.
4. Response structure strictly adheres to the FlowState schema.
5. Works on pipelines with publication data, multiple destinations, and empty pipelines.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import pipeline_flow_state
from app.models import (
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    Publication,
    User,
    VideoJob,
    Workspace,
    WorkspaceMember,
)
from app.tenancy import AuthContext, _current


@contextmanager
def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    try:
        yield engine, db
    finally:
        db.close()
        engine.dispose()


def _set_admin_ctx():
    ctx = AuthContext(
        user_id="test-admin",
        email="admin@test.local",
        is_system_admin=True,
        workspace_ids=[],
        via="test",
    )
    _current.set(ctx)
    return ctx


def test_flow_state_schema_and_counts_with_real_publications():
    """Verify flow_state with active, today-published, yesterday-published, and failed rows."""
    _set_admin_ctx()
    with _session() as (engine, db):
        # 1. Pipeline
        pipeline = Pipeline(
            id="8453c153-3165-481d-88be-9aab00b84577",
            name="JoyBeat Dance",
            slug="joybeat-dance",
            enabled=True,
        )
        db.add(pipeline)
        db.flush()

        # 2. Source & Destination
        source = DouyinSource(
            pipeline_id=pipeline.id,
            platform="douyin",
            name="JoyBeat Official",
            inventory_count=42,
            inventory_sync_status="completed",
        )
        dest = Destination(
            pipeline_id=pipeline.id,
            platform="youtube",
            name="JoyBeat YouTube Channel",
            connected=True,
            enabled=True,
            daily_upload_limit=10,
        )
        db.add_all([source, dest])
        db.flush()

        # 3. Videos
        videos = [
            DouyinVideo(
                pipeline_id=pipeline.id,
                source_id=source.id,
                video_id=f"v-{i}",
                title=f"Dance Video {i}",
                url=f"https://douyin.com/video/{i}",
            )
            for i in range(1, 6)
        ]
        db.add_all(videos)
        db.flush()

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today_start - timedelta(hours=5)
        today_1 = today_start + timedelta(hours=1)
        today_2 = today_start + timedelta(hours=3)

        # 4. Publications:
        # - pub1: published today at 01:00
        # - pub2: published today at 03:00 (latest published)
        # - pub3: published yesterday at 19:00 (must NOT be counted in today_published)
        # - pub4: queued
        # - pub5: failed recently
        pub1 = Publication(
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            douyin_video_id=videos[0].id,
            platform="youtube",
            status="published",
            published_at=today_1,
            created_at=today_1 - timedelta(minutes=10),
        )
        pub2 = Publication(
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            douyin_video_id=videos[1].id,
            platform="youtube",
            status="published",
            published_at=today_2,
            created_at=today_2 - timedelta(minutes=10),
        )
        pub3 = Publication(
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            douyin_video_id=videos[2].id,
            platform="youtube",
            status="published",
            published_at=yesterday,
            created_at=yesterday - timedelta(minutes=10),
        )
        pub4 = Publication(
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            douyin_video_id=videos[3].id,
            platform="youtube",
            status="queued",
            scheduled_at=now + timedelta(hours=2),
            created_at=now - timedelta(minutes=5),
        )
        pub5 = Publication(
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            douyin_video_id=videos[4].id,
            platform="youtube",
            status="failed",
            error="Upload rate limit reached",
            updated_at=now - timedelta(minutes=2),
            created_at=now - timedelta(minutes=10),
        )
        db.add_all([pub1, pub2, pub3, pub4, pub5])
        db.flush()

        # 5. VideoJob for active work
        job = VideoJob(
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            source_video_id=videos[3].video_id,
            source_url="https://douyin.com/video/4",
            status="downloading",
            progress=65,
            attempts=1,
            created_at=now - timedelta(minutes=3),
            updated_at=now - timedelta(seconds=30),
        )
        db.add(job)
        db.commit()

        # Execute pipeline_flow_state
        state = pipeline_flow_state(pipeline.id, db)

        # Assert top-level schema
        assert state["pipeline_id"] == pipeline.id
        assert "summary" in state
        assert "sources" in state
        assert "processors" in state
        assert "destinations" in state
        assert "active_routes" in state

        # Assert Summary schema & values
        summary = state["summary"]
        assert summary["sources"] == 1
        assert summary["inventory_total"] == 5
        assert summary["queue"] == 1  # 1 queued
        assert summary["failed"] == 1  # 1 failed
        assert isinstance(summary["publishing"], int)

        # Assert Sources schema & values
        assert len(state["sources"]) == 1
        s0 = state["sources"][0]
        assert s0["id"] == source.id
        assert s0["name"] == "JoyBeat Official"
        assert s0["inventory_count"] == 42
        assert s0["sync_status"] == "completed"
        assert s0["enabled"] is True

        # Assert Processors
        assert len(state["processors"]) == 4
        proc_keys = [p["key"] for p in state["processors"]]
        assert proc_keys == ["inventory", "ai", "scheduler", "publisher"]
        for p in state["processors"]:
            assert "label" in p and "sub" in p and "state" in p and "detail" in p

        # Assert Destinations: today_published MUST be 2 (pub1 + pub2, not pub3)
        assert len(state["destinations"]) == 1
        d0 = state["destinations"][0]
        assert d0["id"] == dest.id
        assert d0["name"] == "JoyBeat YouTube Channel"
        assert d0["platform"] == "youtube"
        assert d0["today_published"] == 2, f"Expected 2 today publications, got {d0['today_published']}"
        assert d0["daily_upload_limit"] == 10
        assert d0["last_published_at"].startswith("2026-10-21T03:00:00")

        # Assert Routes
        routes = state["active_routes"]
        assert len(routes) >= 2
        # Failed route and active job overlay
        failed_routes = [r for r in routes if r["failed"]]
        assert len(failed_routes) == 1
        assert failed_routes[0]["publication_id"] == pub5.id
        assert failed_routes[0]["error"] == "Upload rate limit reached"


def test_flow_state_empty_pipeline():
    """Verify empty pipeline produces valid schema without divide-by-zero or SQL crash."""
    _set_admin_ctx()
    with _session() as (engine, db):
        pipeline = Pipeline(
            name="Empty Pipeline",
            slug="empty-pipeline",
            enabled=False,
        )
        db.add(pipeline)
        db.commit()

        state = pipeline_flow_state(pipeline.id, db)

        assert state["pipeline_id"] == pipeline.id
        assert state["summary"]["sources"] == 0
        assert state["summary"]["inventory_total"] == 0
        assert state["summary"]["queue"] == 0
        assert state["summary"]["publishing"] == 0
        assert state["summary"]["failed"] == 0
        assert state["sources"] == []
        assert state["destinations"] == []
        assert state["active_routes"] == []
        assert len(state["processors"]) == 4


def test_flow_state_multi_destinations_stats_isolation():
    """Verify today_cnt and last_pub are grouped per destination cleanly."""
    _set_admin_ctx()
    with _session() as (engine, db):
        pipeline = Pipeline(name="Multi Dest", slug="multi-dest", enabled=True)
        db.add(pipeline)
        db.flush()

        d1 = Destination(pipeline_id=pipeline.id, platform="youtube", name="YouTube Channel")
        d2 = Destination(pipeline_id=pipeline.id, platform="tiktok", name="TikTok Account")
        db.add_all([d1, d2])
        db.flush()

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # d1 has 3 today publications on distinct videos
        # d2 has 0 today publications (only 1 yesterday)
        v1 = DouyinVideo(pipeline_id=pipeline.id, video_id="vm-1", title="V1", url="https://douyin.com/1")
        v2 = DouyinVideo(pipeline_id=pipeline.id, video_id="vm-2", title="V2", url="https://douyin.com/2")
        v3 = DouyinVideo(pipeline_id=pipeline.id, video_id="vm-3", title="V3", url="https://douyin.com/3")
        v4 = DouyinVideo(pipeline_id=pipeline.id, video_id="vm-4", title="V4", url="https://douyin.com/4")
        db.add_all([v1, v2, v3, v4])
        db.flush()

        db.add_all([
            Publication(
                pipeline_id=pipeline.id,
                destination_id=d1.id,
                douyin_video_id=v1.id,
                platform="youtube",
                status="published",
                published_at=today_start + timedelta(hours=1),
            ),
            Publication(
                pipeline_id=pipeline.id,
                destination_id=d1.id,
                douyin_video_id=v2.id,
                platform="youtube",
                status="published",
                published_at=today_start + timedelta(hours=2),
            ),
            Publication(
                pipeline_id=pipeline.id,
                destination_id=d1.id,
                douyin_video_id=v3.id,
                platform="youtube",
                status="published",
                published_at=today_start + timedelta(hours=3),
            ),
            Publication(
                pipeline_id=pipeline.id,
                destination_id=d2.id,
                douyin_video_id=v4.id,
                platform="tiktok",
                status="published",
                published_at=today_start - timedelta(days=1),
            ),
        ])
        db.commit()

        state = pipeline_flow_state(pipeline.id, db)
        by_dest_name = {d["name"]: d for d in state["destinations"]}

        assert by_dest_name["YouTube Channel"]["today_published"] == 3
        assert by_dest_name["TikTok Account"]["today_published"] == 0
        assert by_dest_name["YouTube Channel"]["last_published_at"].startswith(
            (today_start + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        )
        assert by_dest_name["TikTok Account"]["last_published_at"].startswith(
            (today_start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        )
