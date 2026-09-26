"""Tests for the fixed rule: max 4 Shorts/day/channel.

Spec mapping: Test 1..10. No real publishes, no RapidAPI, no prod DB
(get_db dependency is overridden to sqlite; resolve_douyin_input mocked).
"""
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Destination, DouyinVideo, Pipeline, Publication, VideoJob
from app.scheduler import (
    allocate_publication,
    count_day_usage,
    count_published_day,
    find_next_available_slot,
    get_capacity,
    promote_due_publications,
    schedule_for_destination,
    shorts_daily_limit,
)

ADMIN = {"X-Admin-Token": "test-admin-token"}


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
    # get_db override so TestClient never touches prod.
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()
    engine.dispose()


@pytest.fixture()
def tclient(db):
    client = TestClient(app)
    client.headers.update({"X-Admin-Token": settings.admin_token})
    yield client


def make_pipeline(db, **kw):
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("name", "Pipe")
    kw.setdefault("slug", f"pipe-{uuid4().hex[:8]}")
    kw.setdefault("enabled", True)
    kw.setdefault("daily_upload_limit", 4)
    kw.setdefault("upload_slots", ["10:00", "14:00", "18:00", "22:00"])
    kw.setdefault("timezone", "Asia/Ho_Chi_Minh")
    p = Pipeline(**kw)
    db.add(p)
    db.commit()
    return p


def make_destination(db, pipeline, name="Chan", **kw):
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("platform", "youtube")
    kw.setdefault("name", name)
    kw.setdefault("enabled", True)
    kw.setdefault("connected", True)
    kw.setdefault("credentials", '{"ok": true}')
    kw.setdefault("daily_upload_limit", 4)
    kw.setdefault("timezone", "Asia/Ho_Chi_Minh")
    kw.setdefault("upload_slots", ["10:00", "14:00", "18:00", "22:00"])
    d = Destination(pipeline_id=pipeline.id, **kw)
    db.add(d)
    db.commit()
    return d


def make_video(db, pipeline, vid=None, **kw):
    vid = vid or f"vid-{uuid4().hex[:8]}"
    v = DouyinVideo(
        pipeline_id=pipeline.id,
        video_id=vid,
        title=f"Title {vid}",
        description="desc",
        url=f"https://v.douyin.com/{vid}/",
        status="inventory",
        **kw,
    )
    db.add(v)
    db.commit()
    return v


def make_published(db, pipeline, dest, video, published_at):
    pub = Publication(
        pipeline_id=pipeline.id,
        douyin_video_id=video.id,
        destination_id=dest.id,
        platform="youtube",
        publication_mode="auto",
        status="published",
        scheduled_at=published_at,
        published_at=published_at,
        external_post_id=f"yt-{uuid4().hex[:8]}",
    )
    db.add(pub)
    db.commit()
    return pub


def fake_resolver_factory():
    seen = {}

    def _resolve(text):
        text = (text or "").strip()
        if "bad-url" in text:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="Không tìm thấy link")
        if text not in seen:
            seen[text] = f"vid-{len(seen)}"
        vid = seen[text]
        return {
            "type": "video",
            "source_url": text if text.startswith("http") else f"https://v.douyin.com/{vid}/",
            "video_id": vid,
            "caption": f"Caption {vid}",
            "thumbnail": None,
        }

    return _resolve


# Midnight ICT Sep 26 2026 == Sep 25 17:00 UTC: all 4 slots ahead.
T0 = datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc)


def _day_counts(db, dest):
    rows = db.execute(
        select(Publication.scheduled_at, func.count(Publication.id))
        .where(Publication.destination_id == dest.id)
        .where(Publication.status.in_(["queued", "scheduled"]))
        .group_by(Publication.scheduled_at)
    ).all()
    out = {}
    for ts, n in rows:
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        from zoneinfo import ZoneInfo

        day = ts.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
        out[day] = out.get(day, 0) + n
    return out


def test_case_a_exact_split_zero_of_four(db):
    """0/4 + 10 videos -> 4 / 4 / 2 across days, FIFO order kept."""
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    vids = [make_video(db, pipe) for _ in range(10)]
    days = []
    for v in vids:
        got = allocate_publication(db, dest, pipe, v, T0)
        assert got is not None
        _, _, day = got
        days.append(day.isoformat())
    assert days == sorted(days), "FIFO order across days"
    counts = _day_counts(db, dest)
    assert counts == {
        "2026-09-26": 4,
        "2026-09-27": 4,
        "2026-09-28": 2,
    }


def test_case_b_one_of_four(db):
    """1 published + 10 videos -> +3 today, 4 tomorrow, 3 next."""
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    v0 = make_video(db, pipe)
    make_published(
        db, pipe, dest, v0, datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
    )
    for _ in range(10):
        v = make_video(db, pipe)
        assert allocate_publication(db, dest, pipe, v, T0) is not None
    counts = _day_counts(db, dest)
    assert counts == {
        "2026-09-26": 3,
        "2026-09-27": 4,
        "2026-09-28": 3,
    }


def test_case_c_three_of_four_plus_two(db):
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    for i in range(3):
        make_published(
            db, pipe, dest, make_video(db, pipe),
            datetime(2026, 9, 26, 1 + i, 0, tzinfo=timezone.utc),
        )
    for _ in range(2):
        assert allocate_publication(db, dest, pipe, make_video(db, pipe), T0) is not None
    counts = _day_counts(db, dest)
    assert counts.get("2026-09-26") == 1
    assert counts.get("2026-09-27") == 1


def test_case_d_full_day_goes_future(db):
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    for i in range(4):
        make_published(
            db, pipe, dest, make_video(db, pipe),
            datetime(2026, 9, 26, i, 0, tzinfo=timezone.utc),
        )
    for _ in range(10):
        assert allocate_publication(db, dest, pipe, make_video(db, pipe), T0) is not None
    counts = _day_counts(db, dest)
    assert counts.get("2026-09-26", 0) == 0
    assert sum(counts.values()) == 10
    assert max(counts.values()) <= 4
    assert counts.get("2026-09-27") == 4


def test_case_e_scheduled_counts_reserve_but_publish_rules(db):
    """2 published + 2 scheduled-for-today -> scheduler adds nothing."""
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe, timezone="UTC",
                            upload_slots=["08:00", "11:00", "14:00", "17:00"])
    src_videos = [make_video(db, pipe) for _ in range(2)]
    for i, v in enumerate(src_videos):
        make_published(
            db, pipe, dest, v,
            datetime(2026, 9, 14, 8 + i, 0, tzinfo=timezone.utc),
        )
    # Two reserved for later today, no jobs yet.
    for i in range(2):
        v = make_video(db, pipe)
        allocate_publication(
            db, dest, pipe, v,
            datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc),
        )
    from zoneinfo import ZoneInfo

    day = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc).astimezone(
        ZoneInfo("UTC")
    ).date()
    pub, sch = count_day_usage(db, dest, day)
    assert (pub, sch) == (2, 2)
    # Scheduler must not schedule a 5th (manual immediate would 409 too).
    before = db.execute(
        select(func.count(Publication.id)).where(
            Publication.destination_id == dest.id,
            Publication.status.in_(["queued", "scheduled"]),
        )
    ).scalar_one()
    schedule_for_destination(
        db, dest, now=datetime(2026, 9, 14, 12, 5, tzinfo=timezone.utc)
    )
    after = db.execute(
        select(func.count(Publication.id)).where(
            Publication.destination_id == dest.id,
            Publication.status.in_(["queued", "scheduled"]),
        )
    ).scalar_one()
    assert after == before


def test_case_h_17_urls_44441(db):
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    for _ in range(17):
        assert allocate_publication(db, dest, pipe, make_video(db, pipe), T0) is not None
    counts = _day_counts(db, dest)
    assert sorted(counts.values()) == [1, 4, 4, 4, 4]
    assert sum(counts.values()) == 17


def test_case_g_failed_releases_and_retry_keeps_slot(db):
    """Failed pub frees its slot; retry keeps original slot, no job until due."""
    from app.main import retry_publication  # noqa

    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    v = make_video(db, pipe)
    pub, slot, day = allocate_publication(db, dest, pipe, v, T0)
    assert day.isoformat() == "2026-09-26"
    # Simulate a failed attempt on that slot.
    pub.status = "failed"
    pub.error = "boom"
    db.commit()
    # Slot freed -> a new video can take the same day.
    v2 = make_video(db, pipe)
    got = allocate_publication(db, dest, pipe, v2, T0)
    assert got is not None and got[2].isoformat() == "2026-09-26"
    # Retry of the failed pub keeps its original slot, stays queued
    # (future slot -> no immediate job).
    pub.status = "failed"
    db.commit()
    with patch("app.main._utcnow", return_value=T0):
        retry_publication(pub.id, db)
    db.refresh(pub)
    assert pub.status == "queued"
    assert pub.scheduled_at is not None
    assert pub.scheduled_at.replace(tzinfo=timezone.utc) == slot
    jobs = db.execute(
        select(VideoJob).where(VideoJob.publication_id == pub.id)
    ).scalars().all()
    assert jobs == []


def test_promote_fifo_and_cap(db):
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    pubs = []
    for _ in range(4):
        v = make_video(db, pipe)
        pub, _, _ = allocate_publication(db, dest, pipe, v, T0)
        pubs.append(pub)
    # 14:05 ICT Sep 26: first two slots (10:00, 14:00 ICT) due -> FIFO.
    now = datetime(2026, 9, 26, 7, 5, tzinfo=timezone.utc)
    n = promote_due_publications(db, dest, now)
    assert n == 2
    jobs = db.execute(
        select(VideoJob).where(VideoJob.destination_id == dest.id)
        .order_by(VideoJob.created_at.asc())
    ).scalars().all()
    assert len(jobs) == 2
    assert jobs[0].publication_id == pubs[0].id
    assert jobs[1].publication_id == pubs[1].id
    # Second call promotes nothing new (idempotent).
    assert promote_due_publications(db, dest, now) == 0


def test_case_f_concurrent_promote_single_slot(db):
    """Two workers racing promote() create exactly one job (slot_key unique)."""
    import tempfile, os

    path = tempfile.mktemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    setup = factory()
    pipe = make_pipeline(setup, slug=f"p-{uuid4().hex[:8]}")
    dest = make_destination(setup, pipe)
    dest_id = dest.id
    v = make_video(setup, pipe)
    pub, _, _ = allocate_publication(setup, dest, pipe, v, T0)
    pub_id = pub.id
    setup.close()

    # 10:05 ICT Sep 26: the single queued slot is due for both workers.
    now = datetime(2026, 9, 26, 3, 5, tzinfo=timezone.utc)
    barrier = threading.Barrier(2)
    results = []

    def _run():
        s = factory()
        try:
            barrier.wait(timeout=10)
            results.append(promote_due_publications(s, s.get(Destination, dest_id), now))
        finally:
            s.close()

    t1, t2 = threading.Thread(target=_run), threading.Thread(target=_run)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    check = factory()
    try:
        jobs = check.execute(
            select(VideoJob).where(VideoJob.publication_id == pub_id)
        ).scalars().all()
        assert len(jobs) == 1
        assert sorted(results) == [0, 1]
    finally:
        check.close()
        engine.dispose()
        if os.path.exists(path):
            os.unlink(path)


# ---------------- API-level tests (Tests 1-6, 9-10) ----------------

def _api_setup(db):
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    return pipe, dest


def test_api_import_10_at_empty_channel(tclient, db):
    pipe, dest = _api_setup(db)
    urls = [f"https://v.douyin.com/x{i}/" for i in range(10)]
    with patch("app.main.resolve_douyin_input", side_effect=fake_resolver_factory()):
        res = tclient.post(
            f"/api/channels/{dest.id}/import-urls", json={"urls": urls}
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 10
    assert body["rejected"] == 0
    assert body["scheduled_today"] + body["scheduled_future"] == 10
    assert body["scheduled_today"] <= 4
    for counts in [body["days"].values()]:
        assert all(n <= 4 for n in body["days"].values())
    # FIFO: scheduled_at non-decreasing in input order.
    times = [it["scheduled_at"] for it in body["items"]]
    assert times == sorted(times)
    # All persisted.
    assert db.execute(
        select(func.count(DouyinVideo.id)).where(DouyinVideo.pipeline_id == pipe.id)
    ).scalar_one() == 10


def test_api_import_dedupe_and_reject(tclient, db):
    pipe, dest = _api_setup(db)
    urls = [
        "https://v.douyin.com/a/",
        "https://v.douyin.com/a/",  # duplicate -> same video, no new slot
        "https://v.douyin.com/bad-url/",
        "",
    ]
    with patch("app.main.resolve_douyin_input", side_effect=fake_resolver_factory()):
        res = tclient.post(
            f"/api/channels/{dest.id}/import-urls", json={"urls": urls}
        )
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == 2
    assert body["rejected"] == 2  # bad-url raises, "" is empty
    statuses = [it["status"] for it in body["items"]]
    assert statuses.count("duplicate") == 1
    assert len(body["items"]) == 4


def test_api_capacity_endpoint(tclient, db):
    pipe, dest = _api_setup(db)
    res = tclient.get(f"/api/channels/{dest.id}/schedule-capacity")
    assert res.status_code == 200
    body = res.json()
    assert body["daily_limit"] == 4
    assert body["published_today"] == 0
    assert body["remaining_today"] == 4
    assert body["timezone"] == "Asia/Ho_Chi_Minh"


def test_api_manual_409_and_override_flow(tclient, db):
    """Tests 4-6: 4/4 -> 409 + override_required -> override -> publish ok."""
    from app.models import YouTubeDailyPublishOverride

    pipe, dest = _api_setup(db)
    now = datetime.now(timezone.utc)
    for i in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)
    payload = {
        "source_url": "https://v.douyin.com/manual1/",
        "source_title": "t",
        "video_id": "manual1",
        "destination_ids": [dest.id],
        "metadata_mode": "same",
        "title": "T",
        "description": "D",
        "privacy_status": "public",
    }
    res = tclient.post("/api/manual/publish", json=payload)
    assert res.status_code == 409, res.text
    body = res.json()["detail"]
    assert body["code"] == "DAILY_LIMIT_REACHED"
    assert body["daily_limit"] == 4
    assert body["published_today"] == 4
    assert body["remaining"] == 0
    assert body["override_required"] is True

    # queue_if_full keeps it queued instead.
    res2 = tclient.post(
        "/api/manual/publish", json={**payload, "queue_if_full": True}
    )
    assert res2.status_code == 202, res2.text

    # No auto-override exists.
    assert db.execute(
        select(func.count(YouTubeDailyPublishOverride.id))
    ).scalar_one() == 0

    # User confirms -> override -> publish accepted (5/4).
    ores = tclient.post(
        f"/api/channels/{dest.id}/overrides",
        json={"extra_allowed": 1, "reason": "user confirmed", "source": "ui_confirmation"},
    )
    assert ores.status_code == 201
    res3 = tclient.post(
        "/api/manual/publish",
        json={**payload, "video_id": "manual2", "source_url": "https://v.douyin.com/manual2/"},
    )
    assert res3.status_code == 202, res3.text

    # Scheduler must not auto-publish a 6th.
    schedule_for_destination(db, dest, now=now)
    pending = db.execute(
        select(func.count(VideoJob.id)).where(VideoJob.destination_id == dest.id)
    ).scalar_one()
    assert pending <= 2  # only the two manual jobs exist


def test_api_inventory_publish_409(tclient, db):
    pipe, dest = _api_setup(db)
    now = datetime.now(timezone.utc)
    for i in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)
    v = make_video(db, pipe)
    res = tclient.post(
        f"/api/pipelines/{pipe.id}/inventory/{v.id}/publish",
        json={"destination_id": dest.id},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["override_required"] is True
    # queue_if_full instead.
    res2 = tclient.post(
        f"/api/pipelines/{pipe.id}/inventory/{v.id}/publish",
        json={"destination_id": dest.id, "queue_if_full": True},
    )
    assert res2.status_code == 201


def test_api_isolation_two_channels(tclient, db):
    """Test 9: A=4/4 blocked, B=1/4 still has slots."""
    pipe, dest_a = _api_setup(db)
    dest_b = make_destination(db, pipe, name="ChanB")
    now = datetime.now(timezone.utc)
    for i in range(4):
        make_published(db, pipe, dest_a, make_video(db, pipe), now)
    make_published(db, pipe, dest_b, make_video(db, pipe), now)
    ca = tclient.get(f"/api/channels/{dest_a.id}/schedule-capacity").json()
    cb = tclient.get(f"/api/channels/{dest_b.id}/schedule-capacity").json()
    assert (ca["used_today"], ca["remaining_today"]) == (4, 0)
    assert cb["published_today"] == 1 and cb["remaining_today"] == 3
    # B accepts immediate publish; A 409s.
    base = {
        "metadata_mode": "same", "title": "T", "description": "D",
        "privacy_status": "public",
    }
    rb = tclient.post(
        "/api/manual/publish",
        json={**base, "source_url": "https://v.douyin.com/b1/",
              "video_id": "b1", "destination_ids": [dest_b.id]},
    )
    assert rb.status_code == 202, rb.text
    ra = tclient.post(
        "/api/manual/publish",
        json={**base, "source_url": "https://v.douyin.com/a1/",
              "video_id": "a1", "destination_ids": [dest_a.id]},
    )
    assert ra.status_code == 409


def test_api_rollover_next_day(tclient, db):
    """Test 10: yesterday's pubs don't count; future queue promotes."""
    pipe, dest = _api_setup(db)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), two_days_ago)
    cap = tclient.get(f"/api/channels/{dest.id}/schedule-capacity").json()
    assert cap["published_today"] == 0
    assert cap["remaining_today"] == 4
    # Overnight queued items promote when their day arrives.
    vids = [make_video(db, pipe) for _ in range(3)]
    for v in vids:
        allocate_publication(db, dest, pipe, v, two_days_ago)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert promote_due_publications(db, dest, future) >= 0
    # Manual publish works again today.
    res = tclient.post(
        "/api/manual/publish",
        json={"source_url": "https://v.douyin.com/r1/", "video_id": "r1",
              "destination_ids": [dest.id], "metadata_mode": "same",
              "title": "T", "description": "D", "privacy_status": "public"},
    )
    assert res.status_code == 202, res.text


def test_short_daily_limit_config(db):
    pipe = make_pipeline(db, daily_upload_limit=2)
    dest = make_destination(db, pipe, daily_upload_limit=2)
    assert shorts_daily_limit(dest) == 2
    dest.daily_upload_limit = 10
    assert shorts_daily_limit(dest) == 4
    assert count_published_day(db, dest, datetime.now(timezone.utc).date()) == 0


# ===========================================================================
# SPEC MAPPING TEST SUITE (Tests 1 through 10)
# ===========================================================================

def test_1_zero_of_four_plus_10_urls(tclient, db):
    """Test 1: 0/4 + add 10 URLs -> tối đa 4 publish hôm nay, 6 queue."""
    pipe, dest = _api_setup(db)
    urls = [f"https://v.douyin.com/spec1_video_{i}/" for i in range(10)]
    with patch("app.main.resolve_douyin_input", side_effect=fake_resolver_factory()):
        with patch("app.main._utcnow", return_value=T0):
            res = tclient.post(f"/api/channels/{dest.id}/import-urls", json={"urls": urls})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 10
    assert body["rejected"] == 0
    assert body["scheduled_today"] == 4
    assert body["scheduled_future"] == 6


def test_2_one_of_four_plus_10_urls(tclient, db):
    """Test 2: 1/4 + add 10 URLs -> tối đa thêm 3 hôm nay, 7 queue."""
    pipe, dest = _api_setup(db)
    # 1 published at 01:00 UTC on T0's day
    t_pub = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
    make_published(db, pipe, dest, make_video(db, pipe), t_pub)

    urls = [f"https://v.douyin.com/spec2_video_{i}/" for i in range(10)]
    with patch("app.main.resolve_douyin_input", side_effect=fake_resolver_factory()):
        with patch("app.main._utcnow", return_value=T0):
            res = tclient.post(f"/api/channels/{dest.id}/import-urls", json={"urls": urls})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 10
    assert body["scheduled_today"] == 3
    assert body["scheduled_future"] == 7


def test_3_four_of_four_background_scheduler_no_publish(db):
    """Test 3: 4/4 + background scheduler -> không publish thêm, queue giữ nguyên."""
    pipe = make_pipeline(db)
    dest = make_destination(db, pipe)
    now = datetime.now(timezone.utc)
    for _ in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)

    # 2 queued items
    for _ in range(2):
        allocate_publication(db, dest, pipe, make_video(db, pipe), now)

    queued_before = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == dest.id, Publication.status == "queued")
    ).scalar_one()
    assert queued_before == 2

    # Run scheduler
    schedule_for_destination(db, dest, now=now)
    promoted = promote_due_publications(db, dest, now)
    assert promoted == 0

    queued_after = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == dest.id, Publication.status == "queued")
    ).scalar_one()
    assert queued_after == queued_before

    jobs_count = db.execute(
        select(func.count(VideoJob.id)).where(VideoJob.destination_id == dest.id)
    ).scalar_one()
    assert jobs_count == 0


def test_4_four_of_four_manual_publish_409(tclient, db):
    """Test 4: 4/4 + manual publish -> 409 DAILY_LIMIT_REACHED, override_required=true."""
    pipe, dest = _api_setup(db)
    now = datetime.now(timezone.utc)
    for _ in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)

    payload = {
        "source_url": "https://v.douyin.com/spec4/",
        "video_id": "spec4",
        "destination_ids": [dest.id],
        "metadata_mode": "same",
        "title": "Title 4",
        "privacy_status": "public",
    }
    res = tclient.post("/api/manual/publish", json=payload)
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "DAILY_LIMIT_REACHED"
    assert detail["daily_limit"] == 4
    assert detail["published_today"] == 4
    assert detail["remaining"] == 0
    assert detail["override_required"] is True


def test_5_user_cancels_keeps_queue(tclient, db):
    """Test 5: user chọn Cancel -> không publish, video giữ queue."""
    pipe, dest = _api_setup(db)
    now = datetime.now(timezone.utc)
    for _ in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)

    payload = {
        "source_url": "https://v.douyin.com/spec5/",
        "video_id": "spec5",
        "destination_ids": [dest.id],
        "metadata_mode": "same",
        "title": "Title 5",
        "privacy_status": "public",
        "queue_if_full": True,
    }
    res = tclient.post("/api/manual/publish", json=payload)
    assert res.status_code == 202, res.text
    body = res.json()
    assert len(body["publications"]) == 1
    assert body["publications"][0]["status"] == "queued"

    # No immediate job created
    jobs = db.execute(
        select(VideoJob).where(VideoJob.destination_id == dest.id)
    ).scalars().all()
    assert len(jobs) == 0


def test_6_user_publishes_anyway_override_5_of_4(tclient, db):
    """Test 6: user chọn Publish anyway -> tạo override -> publish thành 5/4."""
    from app.models import YouTubeDailyPublishOverride

    pipe, dest = _api_setup(db)
    now = datetime.now(timezone.utc)
    for _ in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)

    # Explicit user override created
    ores = tclient.post(
        f"/api/channels/{dest.id}/overrides",
        json={"extra_allowed": 1, "reason": "user confirmed", "source": "ui_confirmation"},
    )
    assert ores.status_code == 201

    # Audit record verified
    override_row = db.execute(
        select(YouTubeDailyPublishOverride)
        .where(YouTubeDailyPublishOverride.destination_id == dest.id)
    ).scalar_one()
    assert override_row.extra_allowed == 1
    assert override_row.source == "ui_confirmation"

    # Now manual publish succeeds
    payload = {
        "source_url": "https://v.douyin.com/spec6/",
        "video_id": "spec6",
        "destination_ids": [dest.id],
        "metadata_mode": "same",
        "title": "Title 6",
        "privacy_status": "public",
    }
    res = tclient.post("/api/manual/publish", json=payload)
    assert res.status_code == 202, res.text

    # Capacity reflects 5 allowed today
    cap = tclient.get(f"/api/channels/{dest.id}/schedule-capacity").json()
    assert cap["allowed_today"] == 5


def test_7_override_scheduler_never_auto_publishes_6th(tclient, db):
    """Test 7: 5/4 do override + scheduler chạy -> không tự publish video thứ 6 nếu không có override mới."""
    pipe, dest = _api_setup(db)
    now = datetime.now(timezone.utc)
    for _ in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), now)

    # 1 override created
    tclient.post(
        f"/api/channels/{dest.id}/overrides",
        json={"extra_allowed": 1, "reason": "user confirmed", "source": "ui_confirmation"},
    )
    # 5th video published
    tclient.post(
        "/api/manual/publish",
        json={
            "source_url": "https://v.douyin.com/spec7_pub5/",
            "video_id": "spec7_pub5",
            "destination_ids": [dest.id],
            "metadata_mode": "same",
            "title": "Title 7-5",
            "privacy_status": "public",
        },
    )
    # Queue video #6
    allocate_publication(db, dest, pipe, make_video(db, pipe), now)

    # Scheduler runs
    schedule_for_destination(db, dest, now=now)
    promoted = promote_due_publications(db, dest, now)
    assert promoted == 0  # Cannot promote 6th video without another explicit override


def test_8_two_concurrent_workers_at_3_of_4_only_one_claims():
    """Test 8: 2 workers chạy đồng thời khi 3/4 -> chỉ 1 worker được claim slot cuối -> không thành 5/4."""
    import tempfile, os

    path = tempfile.mktemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    setup = factory()
    pipe = make_pipeline(setup, slug=f"p8-{uuid4().hex[:8]}")
    dest = make_destination(setup, pipe)
    dest_id = dest.id

    # 3 published today
    for _ in range(3):
        make_published(setup, pipe, dest, make_video(setup, pipe), T0)

    # 1 queued for the 4th slot
    v = make_video(setup, pipe)
    pub, slot_utc, day = allocate_publication(setup, dest, pipe, v, T0)
    pub_id = pub.id
    setup.close()

    # Both workers race to claim the single remaining slot
    now = datetime(2026, 9, 26, 3, 5, tzinfo=timezone.utc)
    barrier = threading.Barrier(2)
    results = []

    def _run():
        s = factory()
        try:
            barrier.wait(timeout=10)
            d = s.get(Destination, dest_id)
            res = promote_due_publications(s, d, now)
            results.append(res)
        finally:
            s.close()

    t1 = threading.Thread(target=_run)
    t2 = threading.Thread(target=_run)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    check = factory()
    try:
        jobs = check.execute(
            select(VideoJob).where(VideoJob.publication_id == pub_id)
        ).scalars().all()
        # Exactly 1 worker claimed the slot
        assert len(jobs) == 1
        assert sorted(results) == [0, 1]
    finally:
        check.close()
        engine.dispose()
        if os.path.exists(path):
            os.unlink(path)


def test_9_channel_isolation_a_blocked_b_allowed(tclient, db):
    """Test 9: A = 4/4, B = 1/4 -> A bị chặn, B vẫn còn 3 slot."""
    pipe, dest_a = _api_setup(db)
    dest_b = make_destination(db, pipe, name="ChanB")
    now = datetime.now(timezone.utc)
    for _ in range(4):
        make_published(db, pipe, dest_a, make_video(db, pipe), now)
    make_published(db, pipe, dest_b, make_video(db, pipe), now)

    ca = tclient.get(f"/api/channels/{dest_a.id}/schedule-capacity").json()
    cb = tclient.get(f"/api/channels/{dest_b.id}/schedule-capacity").json()
    assert ca["used_today"] == 4 and ca["remaining_today"] == 0
    assert cb["published_today"] == 1 and cb["remaining_today"] == 3

    base = {
        "metadata_mode": "same", "title": "T", "description": "D", "privacy_status": "public",
    }
    # B succeeds
    rb = tclient.post(
        "/api/manual/publish",
        json={**base, "source_url": "https://v.douyin.com/spec9_b/", "video_id": "spec9_b", "destination_ids": [dest_b.id]},
    )
    assert rb.status_code == 202
    # A fails with 409
    ra = tclient.post(
        "/api/manual/publish",
        json={**base, "source_url": "https://v.douyin.com/spec9_a/", "video_id": "spec9_a", "destination_ids": [dest_a.id]},
    )
    assert ra.status_code == 409
    assert ra.json()["detail"]["override_required"] is True


def test_10_day_rollover_resets_quota_queue_continues(tclient, db):
    """Test 10: sang ngày mới -> quota về 0/4 -> queue tiếp tục chạy."""
    pipe, dest = _api_setup(db)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    for _ in range(4):
        make_published(db, pipe, dest, make_video(db, pipe), yesterday)

    # Overrides from yesterday do not carry over
    from app.models import YouTubeDailyPublishOverride
    from app.scheduler import destination_today
    yesterday_str = destination_today(dest, yesterday).isoformat()
    db.add(YouTubeDailyPublishOverride(
        destination_id=dest.id,
        date=yesterday_str,
        extra_allowed=2,
        reason="yesterday override",
        source="ui_confirmation",
    ))
    db.commit()

    cap = tclient.get(f"/api/channels/{dest.id}/schedule-capacity").json()
    assert cap["published_today"] == 0
    assert cap["remaining_today"] == 4
    assert cap["extra_allowed_today"] == 0

    # Old queue continues
    vids = [make_video(db, pipe) for _ in range(2)]
    for v in vids:
        allocate_publication(db, dest, pipe, v, yesterday)

    promoted = promote_due_publications(db, dest, datetime.now(timezone.utc) + timedelta(days=1))
    assert promoted >= 0

    # Manual publish succeeds today
    res = tclient.post(
        "/api/manual/publish",
        json={
            "source_url": "https://v.douyin.com/spec10/", "video_id": "spec10",
            "destination_ids": [dest.id], "metadata_mode": "same",
            "title": "T10", "privacy_status": "public",
        },
    )
    assert res.status_code == 202

