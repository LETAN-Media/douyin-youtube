"""Pipeline deletion: scoped purge, busy guard, permissions, rollback.

Runs entirely against in-memory SQLite (get_db overridden). No production
pipeline is touched, no YouTube API is called.
"""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.pipeline_deletion as deletion
from app import auth as auth_lib
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import (
    AppSetting,
    Destination,
    DouyinScanJob,
    DouyinSource,
    DouyinVideo,
    OAuthState,
    Pipeline,
    PipelineSource,
    Publication,
    User,
    VideoJob,
    Workspace,
    WorkspaceMember,
    YouTubeChannelAnalyticsDaily,
    YouTubeChannelDNA,
    YouTubeComment,
    YouTubeContentFingerprint,
    YouTubeDailyPublishOverride,
    YouTubeDNASuggestion,
    YouTubePerformanceSnapshot,
    YouTubeResearchItem,
    YouTubeResearchRun,
    YouTubeVideoAnalyticsDaily,
)

UTC = timezone.utc


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        # One session per request, like production; the test keeps its own.
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def client(session_factory):
    c = TestClient(app)
    c.headers.update({"X-Admin-Token": settings.admin_token})
    return c


def make_pipeline(db, slug=None, **kw) -> Pipeline:
    slug = slug or f"pipe-{uuid4().hex[:8]}"
    kw.setdefault("name", slug)
    kw.setdefault("enabled", True)
    pipeline = Pipeline(slug=slug, **kw)
    db.add(pipeline)
    db.commit()
    return pipeline


def populate(db, pipeline: Pipeline) -> dict[str, list[str]]:
    """Create every pipeline-scoped row type and return the created ids."""
    destination = Destination(
        pipeline_id=pipeline.id,
        workspace_id=pipeline.workspace_id,
        platform="youtube",
        name=f"Channel {pipeline.slug}",
        enabled=True,
        connected=True,
        credentials=json.dumps({"refresh_token": "test"}),
    )
    source = DouyinSource(
        pipeline_id=pipeline.id,
        workspace_id=pipeline.workspace_id,
        name=f"Source {pipeline.slug}",
        profile_url=f"https://www.douyin.com/user/{pipeline.slug}",
        enabled=True,
    )
    db.add_all([destination, source])
    db.flush()

    video = DouyinVideo(
        pipeline_id=pipeline.id,
        workspace_id=pipeline.workspace_id,
        source_id=source.id,
        video_id=f"video-{pipeline.slug}",
        title="Video",
        description="Mô tả",
        url="https://www.douyin.com/video/1",
        status="scheduled",
    )
    db.add(video)
    db.flush()
    publication = Publication(
        pipeline_id=pipeline.id,
        workspace_id=pipeline.workspace_id,
        douyin_video_id=video.id,
        destination_id=destination.id,
        platform="youtube",
        status="queued",
        title="Publication",
        external_post_id=f"yt-{pipeline.slug}",
        external_url=f"https://youtu.be/{pipeline.slug}",
    )
    db.add(publication)
    db.flush()
    job = VideoJob(
        pipeline_id=pipeline.id,
        workspace_id=pipeline.workspace_id,
        destination_id=destination.id,
        publication_id=publication.id,
        source_url="https://www.douyin.com/video/1",
        status="pending",
    )
    db.add(job)
    db.flush()

    db.add_all(
        [
            DouyinScanJob(
                pipeline_id=pipeline.id,
                workspace_id=pipeline.workspace_id,
                source_id=source.id,
                status="completed",
            ),
            PipelineSource(
                pipeline_id=pipeline.id,
                workspace_id=pipeline.workspace_id,
                platform="douyin",
            ),
            OAuthState(
                state=f"state-{pipeline.slug}",
                pipeline_id=pipeline.id,
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            YouTubeChannelDNA(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                primary_niche="test",
            ),
            YouTubeContentFingerprint(
                publication_id=publication.id,
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
            ),
            YouTubeComment(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                video_id=f"yt-{pipeline.slug}",
                youtube_comment_id=f"comment-{pipeline.slug}",
            ),
            YouTubeDailyPublishOverride(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                date="2026-01-01",
            ),
            YouTubeChannelAnalyticsDaily(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                date="2026-01-01",
            ),
            YouTubeVideoAnalyticsDaily(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                video_id=f"yt-{pipeline.slug}",
                date="2026-01-01",
            ),
            YouTubePerformanceSnapshot(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                video_id=f"yt-{pipeline.slug}",
                checkpoint="1h",
            ),
            YouTubeDNASuggestion(
                destination_id=destination.id,
                workspace_id=pipeline.workspace_id,
                kind="suggest_core_hashtag",
            ),
            AppSetting(
                key=f"youtube_upload_attempt:{job.id}",
                value=json.dumps({"phase": "finalized"}),
            ),
            AppSetting(
                key=f"youtube_upload_publication:{publication.id}",
                value=job.id,
            ),
        ]
    )
    run = YouTubeResearchRun(
        destination_id=destination.id,
        workspace_id=pipeline.workspace_id,
    )
    db.add(run)
    db.flush()
    db.add(
        YouTubeResearchItem(
            run_id=run.id,
            destination_id=destination.id,
            workspace_id=pipeline.workspace_id,
        )
    )
    db.commit()
    return {
        "pipeline": [pipeline.id],
        "destination": [destination.id],
        "source": [source.id],
        "video": [video.id],
        "publication": [publication.id],
        "job": [job.id],
        "run": [run.id],
    }


def count_refs(db, ids: dict[str, list[str]]) -> dict[str, int]:
    """Remaining rows referencing the captured ids, across all model tables."""
    checks = {
        "destinations": (Destination, "id", ids["destination"]),
        "douyin_sources": (DouyinSource, "id", ids["source"]),
        "douyin_videos": (DouyinVideo, "id", ids["video"]),
        "publications": (Publication, "id", ids["publication"]),
        "video_jobs": (VideoJob, "id", ids["job"]),
        "douyin_scan_jobs": (DouyinScanJob, "pipeline_id", ids["pipeline"]),
        "pipeline_sources": (PipelineSource, "pipeline_id", ids["pipeline"]),
        "oauth_states": (OAuthState, "pipeline_id", ids["pipeline"]),
        "youtube_channel_dna": (YouTubeChannelDNA, "destination_id", ids["destination"]),
        "youtube_content_fingerprints": (
            YouTubeContentFingerprint,
            "destination_id",
            ids["destination"],
        ),
        "youtube_comments": (YouTubeComment, "destination_id", ids["destination"]),
        "youtube_daily_publish_overrides": (
            YouTubeDailyPublishOverride,
            "destination_id",
            ids["destination"],
        ),
        "youtube_channel_analytics_daily": (
            YouTubeChannelAnalyticsDaily,
            "destination_id",
            ids["destination"],
        ),
        "youtube_video_analytics_daily": (
            YouTubeVideoAnalyticsDaily,
            "destination_id",
            ids["destination"],
        ),
        "youtube_performance_snapshots": (
            YouTubePerformanceSnapshot,
            "destination_id",
            ids["destination"],
        ),
        "youtube_dna_suggestions": (
            YouTubeDNASuggestion,
            "destination_id",
            ids["destination"],
        ),
        "youtube_research_runs": (
            YouTubeResearchRun,
            "destination_id",
            ids["destination"],
        ),
        "youtube_research_items": (
            YouTubeResearchItem,
            "destination_id",
            ids["destination"],
        ),
    }
    result: dict[str, int] = {}
    for table, (model, column, values) in checks.items():
        if not values:
            continue
        total = db.execute(
            select(func.count()).select_from(model).where(
                getattr(model, column).in_(values)
            )
        ).scalar_one_or_none() or 0
        if total:
            result[table] = int(total)
    return result


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_delete_empty_pipeline(db, client):
    pipeline = make_pipeline(db)
    other = make_pipeline(db)

    response = client.delete(f"/api/pipelines/{pipeline.id}")

    assert response.status_code == 204, response.text
    db.expunge_all()
    assert db.get(Pipeline, pipeline.id) is None
    assert db.get(Pipeline, other.id) is not None


def test_delete_pipeline_with_all_related_data(db, client, monkeypatch):
    pipeline = make_pipeline(db)
    ids = populate(db, pipeline)
    other = make_pipeline(db)
    other_ids = populate(db, other)
    before = count_refs(db, other_ids)
    assert before  # other pipeline has rows

    # Deleting a pipeline must never call YouTube.
    monkeypatch.setattr(
        "app.youtube.update_video_schedule",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("YouTube called")),
    )
    monkeypatch.setattr(
        "app.youtube.publish_video_now",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("YouTube called")),
    )

    response = client.delete(f"/api/pipelines/{pipeline.id}")

    assert response.status_code == 204, response.text
    db.expunge_all()
    assert db.get(Pipeline, pipeline.id) is None
    assert count_refs(db, ids) == {}
    # No upload reconciliation marker survives for the deleted job/publication.
    for key in (
        f"youtube_upload_attempt:{ids['job'][0]}",
        f"youtube_upload_publication:{ids['publication'][0]}",
    ):
        assert db.get(AppSetting, key) is None
    # The other pipeline is untouched.
    assert db.get(Pipeline, other.id) is not None
    assert count_refs(db, other_ids) == before


def test_second_delete_returns_404(db, client):
    pipeline = make_pipeline(db)

    assert client.delete(f"/api/pipelines/{pipeline.id}").status_code == 204
    second = client.delete(f"/api/pipelines/{pipeline.id}")

    assert second.status_code == 404


# ---------------------------------------------------------------------------
# In-flight guards
# ---------------------------------------------------------------------------

def test_upload_in_progress_blocks_delete(db, client):
    pipeline = make_pipeline(db)
    ids = populate(db, pipeline)
    job = db.get(VideoJob, ids["job"][0])
    job.status = "uploading"
    db.commit()

    response = client.delete(f"/api/pipelines/{pipeline.id}")

    assert response.status_code == 409
    assert "PIPELINE_BUSY" in response.json()["detail"]
    db.expunge_all()
    saved = db.get(Pipeline, pipeline.id)
    assert saved is not None
    # Scheduler stop is rolled back so nothing is left half-disabled.
    assert saved.enabled is True
    assert count_refs(db, ids)  # all management/reconciliation data still there
    assert db.get(VideoJob, ids["job"][0]).status == "uploading"


def test_unknown_upload_outcome_blocks_delete(db, client):
    pipeline = make_pipeline(db)
    ids = populate(db, pipeline)
    db.get(VideoJob, ids["job"][0]).status = "upload_unknown"
    db.commit()

    response = client.delete(f"/api/pipelines/{pipeline.id}")

    assert response.status_code == 409
    assert "PIPELINE_BUSY" in response.json()["detail"]


def test_processing_publication_blocks_delete(db, client):
    pipeline = make_pipeline(db)
    ids = populate(db, pipeline)
    publication = db.get(Publication, ids["publication"][0])
    publication.status = "processing"
    db.commit()

    response = client.delete(f"/api/pipelines/{pipeline.id}")

    assert response.status_code == 409
    assert "PIPELINE_BUSY" in response.json()["detail"]
    assert db.get(Publication, ids["publication"][0]) is not None


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def _user_session(db, workspace_id: str, role: str) -> tuple[dict[str, str], str]:
    user = User(
        email=f"{uuid4().hex[:8]}@test.local",
        password_hash=auth_lib.hash_password("test-pass-123"),
        display_name="Test User",
        status="active",
    )
    db.add(user)
    db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user.id,
            role=role,
        )
    )
    db.commit()
    _, token = auth_lib.create_user_session(db, user, ttl_seconds=3600)
    return {"X-Session-Token": token}, user.id


def test_other_workspace_pipeline_is_not_found(db, client):
    workspace_a = Workspace(name="A")
    workspace_b = Workspace(name="B")
    db.add_all([workspace_a, workspace_b])
    db.commit()
    pipeline = make_pipeline(db, workspace_id=workspace_b.id)
    headers, _ = _user_session(db, workspace_a.id, "owner")

    response = client.delete(f"/api/pipelines/{pipeline.id}", headers=headers)

    assert response.status_code == 404
    assert db.get(Pipeline, pipeline.id) is not None


def test_member_role_cannot_delete_pipeline(db, client):
    workspace = Workspace(name="Members")
    db.add(workspace)
    db.commit()
    pipeline = make_pipeline(db, workspace_id=workspace.id)
    headers, _ = _user_session(db, workspace.id, "member")

    response = client.delete(f"/api/pipelines/{pipeline.id}", headers=headers)

    assert response.status_code == 403
    assert "PIPELINE_DELETE_FORBIDDEN" in response.json()["detail"]
    assert db.get(Pipeline, pipeline.id) is not None


def test_owner_can_delete_own_pipeline(db, client):
    workspace = Workspace(name="Owners")
    db.add(workspace)
    db.commit()
    pipeline = make_pipeline(db, workspace_id=workspace.id)
    populate(db, pipeline)
    headers, _ = _user_session(db, workspace.id, "owner")

    response = client.delete(f"/api/pipelines/{pipeline.id}", headers=headers)

    assert response.status_code == 204, response.text
    db.expunge_all()
    assert db.get(Pipeline, pipeline.id) is None


# ---------------------------------------------------------------------------
# Transaction safety
# ---------------------------------------------------------------------------

def test_failure_mid_purge_rolls_back_everything(db, client, monkeypatch):
    pipeline = make_pipeline(db)
    ids = populate(db, pipeline)
    before = count_refs(db, ids)
    assert before
    real_purge = deletion._purge

    def explode(db_session, pipeline_obj, tables=None):
        # Delete rows inside the open transaction, then fail.
        real_purge(db_session, pipeline_obj, tables=tables)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(deletion, "_purge", explode)

    response = client.delete(f"/api/pipelines/{pipeline.id}")

    assert response.status_code == 500
    assert "PIPELINE_DELETE_FAILED" in response.json()["detail"]
    db.expunge_all()
    saved = db.get(Pipeline, pipeline.id)
    assert saved is not None
    assert saved.enabled is True
    # Every row is back: the purge was rolled back, nothing half-deleted.
    assert count_refs(db, ids) == before


def test_delete_does_not_touch_other_workspace_rows(db, client):
    workspace_a = Workspace(name="WA")
    workspace_b = Workspace(name="WB")
    db.add_all([workspace_a, workspace_b])
    db.commit()
    pipeline_a = make_pipeline(db, workspace_id=workspace_a.id)
    ids_a = populate(db, pipeline_a)
    pipeline_b = make_pipeline(db, workspace_id=workspace_b.id)
    ids_b = populate(db, pipeline_b)
    before_b = count_refs(db, ids_b)

    assert client.delete(f"/api/pipelines/{pipeline_a.id}").status_code == 204

    db.expunge_all()
    assert count_refs(db, ids_a) == {}
    assert count_refs(db, ids_b) == before_b
    assert db.get(Workspace, workspace_a.id) is not None
    assert db.get(Workspace, workspace_b.id) is not None
