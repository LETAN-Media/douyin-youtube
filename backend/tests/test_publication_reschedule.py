"""Reschedule contract tests.

Covers the rules from the Douyin Publications reschedule spec: past/future
times, UTC vs GMT+7 input, published/failed/scheduled/in-flight rows, slot
collision, daily limit, minimum interval, queue/scheduler consistency and the
native YouTube schedule handoff. Runs on in-memory SQLite; no uploads, no
network, no production data.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import worker
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Destination, DouyinVideo, Pipeline, Publication, VideoJob
from app.scheduler import promote_due_publications

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC = timezone.utc


def _engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def db():
    engine = _engine()
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db):
    c = TestClient(app)
    c.headers.update({"X-Admin-Token": settings.admin_token})
    return c


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def local_slot(days: int = 1, hour: int = 10, minute: int = 0) -> datetime:
    """Wall-clock slot in Asia/Ho_Chi_Minh, N days from now."""
    base = datetime.now(TZ) + timedelta(days=days)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def stored_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def make_pipeline(db, **kw) -> Pipeline:
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("name", "Pipe")
    kw.setdefault("slug", f"pipe-{uuid4().hex[:8]}")
    kw.setdefault("enabled", True)
    kw.setdefault("daily_upload_limit", 4)
    kw.setdefault("upload_slots", ["10:00", "14:00", "18:00", "22:00"])
    kw.setdefault("timezone", "Asia/Ho_Chi_Minh")
    pipeline = Pipeline(**kw)
    db.add(pipeline)
    db.commit()
    return pipeline


def make_destination(db, pipeline: Pipeline, **kw) -> Destination:
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("platform", "youtube")
    kw.setdefault("name", "Kênh Test")
    kw.setdefault("enabled", True)
    kw.setdefault("connected", True)
    kw.setdefault("credentials", json.dumps({"ok": True}))
    kw.setdefault("schedule_override_enabled", True)
    kw.setdefault("daily_upload_limit", 4)
    kw.setdefault("upload_slots", ["10:00", "14:00", "18:00", "22:00"])
    kw.setdefault("timezone", "Asia/Ho_Chi_Minh")
    kw.setdefault("publishing_start_time", "08:00")
    kw.setdefault("publishing_end_time", "23:00")
    kw.setdefault("auto_distribute_upload_slots", False)
    kw.setdefault("min_upload_interval_minutes", 1)
    destination = Destination(pipeline_id=pipeline.id, **kw)
    db.add(destination)
    db.commit()
    return destination


def make_video(db, pipeline: Pipeline) -> DouyinVideo:
    video = DouyinVideo(
        id=str(uuid4()),
        pipeline_id=pipeline.id,
        source_id=None,
        video_id=f"v-{uuid4().hex[:8]}",
        title="Video test",
        description="Mô tả",
        url="https://www.douyin.com/video/1",
        status="scheduled",
    )
    db.add(video)
    db.commit()
    return video


def make_publication(db, pipeline, destination, video, when=None, **kw) -> Publication:
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("platform", "youtube")
    kw.setdefault("status", "scheduled")
    kw.setdefault("scheduled_at", when)
    publication = Publication(
        pipeline_id=pipeline.id,
        destination_id=destination.id,
        douyin_video_id=video.id,
        **kw,
    )
    db.add(publication)
    db.commit()
    return publication


def reschedule(client, publication: Publication, when: datetime):
    return client.post(
        f"/api/publications/{publication.id}/reschedule",
        json={"scheduled_at": when.isoformat()},
    )


def slot_key(destination: Destination, when: datetime) -> str:
    return f"{destination.id}:{as_utc(when).replace(second=0, microsecond=0).isoformat()}"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_future_time_accepted_and_stored_in_utc(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    db.add(
        VideoJob(
            pipeline_id=pipeline.id,
            destination_id=destination.id,
            publication_id=publication.id,
            source_url="https://www.douyin.com/video/1",
            status="pending",
        )
    )
    db.commit()
    target = as_utc(local_slot(3, 18))

    response = reschedule(client, publication, target)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    assert datetime.fromisoformat(body["scheduled_at"]) == target
    db.expire_all()
    saved = db.get(Publication, publication.id)
    assert stored_utc(saved.scheduled_at) == target


def test_gmt7_input_is_converted_to_utc(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    db.add(
        VideoJob(
            pipeline_id=pipeline.id,
            destination_id=destination.id,
            publication_id=publication.id,
            source_url="https://www.douyin.com/video/1",
            status="pending",
        )
    )
    db.commit()
    local_target = local_slot(4, 20, 30)  # 20:30 GMT+7 == 13:30 UTC

    response = reschedule(client, publication, local_target)

    assert response.status_code == 200, response.text
    saved = datetime.fromisoformat(response.json()["scheduled_at"])
    assert saved == local_target.astimezone(UTC)
    assert saved.tzinfo is not None


def test_failed_publication_becomes_queued_without_new_job(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(1)),
        status="failed",
        error="upload lỗi",
    )
    failed_job = VideoJob(
        pipeline_id=pipeline.id,
        destination_id=destination.id,
        publication_id=publication.id,
        source_url="https://www.douyin.com/video/1",
        status="failed",
        schedule_slot_key=slot_key(destination, local_slot(1)),
    )
    db.add(failed_job)
    db.commit()
    target = as_utc(local_slot(3, 14))

    response = reschedule(client, publication, target)

    assert response.status_code == 200, response.text
    db.expire_all()
    saved = db.get(Publication, publication.id)
    assert saved.status == "queued"
    assert stored_utc(saved.scheduled_at) == target
    jobs = db.execute(
        select(VideoJob).where(VideoJob.publication_id == publication.id)
    ).scalars().all()
    # Never resurrect a failed upload or create a duplicate job.
    assert len(jobs) == 1
    assert jobs[0].status == "failed"


def test_scheduler_creates_exactly_one_job_for_new_slot(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(1)),
        status="failed",
        error="upload lỗi",
    )
    db.add(
        VideoJob(
            pipeline_id=pipeline.id,
            destination_id=destination.id,
            publication_id=publication.id,
            source_url="https://www.douyin.com/video/1",
            status="failed",
        )
    )
    db.commit()
    target = as_utc(local_slot(2, 18))

    assert reschedule(client, publication, target).status_code == 200

    created = promote_due_publications(db, destination, target + timedelta(minutes=1))
    assert created == 1
    db.expire_all()
    jobs = db.execute(
        select(VideoJob).where(VideoJob.publication_id == publication.id)
    ).scalars().all()
    pending = [job for job in jobs if job.status == "pending"]
    assert len(pending) == 1
    assert pending[0].schedule_slot_key == slot_key(destination, target)
    assert db.get(Publication, publication.id).status == "scheduled"
    # A second scheduler pass must not duplicate the job.
    assert promote_due_publications(db, destination, target + timedelta(minutes=2)) == 0


def test_pending_job_reservation_moves_to_new_slot(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    old_key = slot_key(destination, local_slot(1))
    job = VideoJob(
        pipeline_id=pipeline.id,
        destination_id=destination.id,
        publication_id=publication.id,
        source_url="https://www.douyin.com/video/1",
        status="pending",
        schedule_slot_key=old_key,
    )
    db.add(job)
    db.commit()
    target = as_utc(local_slot(3, 22))

    assert reschedule(client, publication, target).status_code == 200

    db.expire_all()
    saved_job = db.get(VideoJob, job.id)
    assert saved_job.status == "pending"
    assert saved_job.schedule_slot_key == slot_key(destination, target)
    assert saved_job.schedule_slot_key != old_key
    assert stored_utc(saved_job.youtube_publish_at) == target


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------

def test_published_publication_rejected(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    before = as_utc(local_slot(-1))
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        before,
        status="published",
        published_at=before,
        external_post_id="yt-published",
    )

    response = reschedule(client, publication, as_utc(local_slot(2, 18)))

    assert response.status_code == 409
    assert "PUBLICATION_ALREADY_PUBLISHED" in response.json()["detail"]
    db.expire_all()
    saved = db.get(Publication, publication.id)
    assert saved.status == "published"
    assert stored_utc(saved.scheduled_at) == before


def test_uploading_publication_rejected(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(1)),
        status="uploading",
    )

    response = reschedule(client, publication, as_utc(local_slot(2, 18)))

    assert response.status_code == 409
    assert "PUBLICATION_IN_PROGRESS" in response.json()["detail"]


def test_uploading_job_rejected(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    db.add(
        VideoJob(
            pipeline_id=pipeline.id,
            destination_id=destination.id,
            publication_id=publication.id,
            source_url="https://www.douyin.com/video/1",
            status="uploading",
        )
    )
    db.commit()

    response = reschedule(client, publication, as_utc(local_slot(2, 18)))

    assert response.status_code == 409
    assert "PUBLICATION_IN_PROGRESS" in response.json()["detail"]


def test_past_time_rejected(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )

    response = reschedule(client, publication, datetime.now(UTC) - timedelta(hours=1))

    assert response.status_code == 400
    assert "INVALID_SCHEDULE_TIME" in response.json()["detail"]


def test_naive_datetime_rejected(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    naive = as_utc(local_slot(2, 18)).replace(tzinfo=None).isoformat()

    response = client.post(
        f"/api/publications/{publication.id}/reschedule",
        json={"scheduled_at": naive},
    )

    assert response.status_code == 400
    assert "INVALID_SCHEDULE_TIME" in response.json()["detail"]


def test_slot_collision_reports_next_free_slot(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    other_target = as_utc(local_slot(2, 10))
    other = make_publication(
        db, pipeline, destination, make_video(db, pipeline), other_target
    )

    response = reschedule(client, publication, other_target)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "SLOT_COLLISION" in detail
    assert "Gợi ý giờ trống tiếp theo" in detail
    db.expire_all()
    assert stored_utc(db.get(Publication, other.id).scheduled_at) == other_target
    assert stored_utc(db.get(Publication, publication.id).scheduled_at) == as_utc(
        local_slot(1)
    )


def test_daily_limit_blocks_reschedule(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(
        db,
        pipeline,
        daily_upload_limit=2,
        upload_slots=["10:00", "18:00"],
    )
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(2, 10))
    )
    make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(2, 18))
    )

    response = reschedule(client, publication, as_utc(local_slot(2, 12)))

    assert response.status_code == 409
    assert "DAILY_LIMIT_REACHED" in response.json()["detail"]


def test_minimum_interval_blocks_reschedule(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline, min_upload_interval_minutes=30)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(2, 10))
    )

    response = reschedule(client, publication, as_utc(local_slot(2, 10, 15)))

    assert response.status_code == 409
    assert "MIN_INTERVAL_VIOLATION" in response.json()["detail"]


def test_uploaded_without_native_schedule_rejected(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(1)),
        external_post_id="yt-123",
        youtube_scheduled=False,
    )

    response = reschedule(client, publication, as_utc(local_slot(2, 18)))

    assert response.status_code == 409
    assert "YOUTUBE_RESCHEDULE_UNSUPPORTED" in response.json()["detail"]
    db.expire_all()
    assert stored_utc(db.get(Publication, publication.id).scheduled_at) == as_utc(
        local_slot(1)
    )


# ---------------------------------------------------------------------------
# Native YouTube schedule + options endpoint + worker queue sync
# ---------------------------------------------------------------------------

def test_youtube_native_schedule_updated_through_api(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(1)),
        external_post_id="yt-123",
        youtube_scheduled=True,
        youtube_publish_mode="scheduled",
    )
    calls: list[tuple[str, str, datetime]] = []

    def fake_update(_db, destination_id, video_id, new_at):
        calls.append((destination_id, video_id, as_utc(new_at)))

    target = as_utc(local_slot(2, 22))
    with patch("app.youtube.update_video_schedule", fake_update):
        response = reschedule(client, publication, target)

    assert response.status_code == 200, response.text
    assert calls == [(destination.id, "yt-123", target)]
    db.expire_all()
    saved = db.get(Publication, publication.id)
    assert stored_utc(saved.youtube_publish_at) == target
    assert saved.youtube_schedule_timezone == "Asia/Ho_Chi_Minh"
    assert saved.youtube_scheduled is True


def test_youtube_failure_is_reported_not_silently_saved(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(1)),
        external_post_id="yt-123",
        youtube_scheduled=True,
    )

    def failing_update(_db, _destination_id, _video_id, _new_at):
        raise RuntimeError("invalidPublishAt")

    target = as_utc(local_slot(2, 22))
    with patch("app.youtube.update_video_schedule", failing_update):
        response = reschedule(client, publication, target)

    assert response.status_code == 502
    assert "YOUTUBE_RESCHEDULE_FAILED" in response.json()["detail"]
    db.expire_all()
    assert stored_utc(db.get(Publication, publication.id).scheduled_at) == as_utc(
        local_slot(1)
    )


def test_reschedule_options_expose_timezone_and_suggestion(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(-2))
    )

    response = client.get(f"/api/publications/{publication.id}/reschedule-options")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Asia/Ho_Chi_Minh"
    assert "GMT+7" in body["timezone_label"]
    assert body["can_reschedule"] is True
    suggested = datetime.fromisoformat(body["suggested_at"])
    assert suggested > datetime.now(UTC) + timedelta(minutes=5)
    assert suggested.astimezone(TZ).minute in {0, 30}
    assert body["next_free_slots"]
    assert body["scheduled_at_label"].endswith("(GMT+7)")


def test_options_flag_published_publication(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db,
        pipeline,
        destination,
        make_video(db, pipeline),
        as_utc(local_slot(-1)),
        status="published",
    )

    response = client.get(f"/api/publications/{publication.id}/reschedule-options")

    assert response.status_code == 200
    body = response.json()
    assert body["can_reschedule"] is False
    assert "Published" in body["block_reason"]


def test_worker_holds_job_until_new_slot_is_due(db, client):
    pipeline = make_pipeline(db)
    destination = make_destination(db, pipeline)
    publication = make_publication(
        db, pipeline, destination, make_video(db, pipeline), as_utc(local_slot(1))
    )
    job = VideoJob(
        pipeline_id=pipeline.id,
        destination_id=destination.id,
        publication_id=publication.id,
        source_url="https://www.douyin.com/video/1",
        status="pending",
    )
    db.add(job)
    db.commit()
    target = as_utc(local_slot(2, 18))
    assert reschedule(client, publication, target).status_code == 200

    Session = sessionmaker(bind=db.get_bind())
    with patch.object(worker, "SessionLocal", Session), patch.object(
        worker, "_upload_policy_block", return_value=None
    ):
        # Future slot: no upload yet.
        assert worker.claim_job() is None

        saved = db.get(Publication, publication.id)
        saved.scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        assert worker.claim_job() == job.id
