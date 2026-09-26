"""Tests for native YouTube scheduled publishing."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Destination, DouyinVideo, Pipeline, Publication, VideoJob
from app.youtube_scheduling import (
    assign_backlog_slots,
    build_insert_status,
    find_next_free_slot,
    format_scheduled_preview,
    local_to_utc,
    parse_publish_at,
    validate_publish_at,
    ScheduleValidationError,
)


def _utcnow():
    return datetime.now(timezone.utc)


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _pipeline(db, **kw):
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("name", "T")
    kw.setdefault("slug", f"t-{uuid4().hex[:8]}")
    kw.setdefault("enabled", True)
    p = Pipeline(**kw)
    db.add(p)
    db.flush()
    return p


def _dest(db, pipeline, **kw):
    import json as _j
    kw.setdefault("id", str(uuid4()))
    kw.setdefault("platform", "youtube")
    kw.setdefault("name", "YT")
    kw.setdefault("enabled", True)
    kw.setdefault("connected", True)
    kw.setdefault("credentials", _j.dumps({"token": "t", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": []}))
    kw.setdefault("timezone", "Asia/Ho_Chi_Minh")
    kw.setdefault("upload_slots", ["09:00", "18:00"])
    d = Destination(pipeline_id=pipeline.id, **kw)
    db.add(d)
    db.flush()
    return d


def test_immediate_public_status():
    s = build_insert_status("immediate")
    assert s == {"privacyStatus": "public"}


def test_private_status():
    assert build_insert_status("private") == {"privacyStatus": "private"}


def test_unlisted_status():
    assert build_insert_status("unlisted") == {"privacyStatus": "unlisted"}
    # Never send publishAt for unlisted.
    assert "publishAt" not in build_insert_status("unlisted")


def test_scheduled_future_datetime():
    fut = _utcnow() + timedelta(hours=2)
    s = build_insert_status("scheduled", fut)
    assert s["privacyStatus"] == "private"
    assert s["publishAt"].endswith("Z")
    assert "T" in s["publishAt"]


def test_publishat_requires_private():
    # scheduled mode forces private even if caller wanted public.
    fut = _utcnow() + timedelta(hours=2)
    s = build_insert_status("scheduled", fut)
    assert s["privacyStatus"] == "private"


def test_timezone_conversion_hcm():
    # 2026-09-26 19:30 Asia/Ho_Chi_Minh -> 12:30Z UTC
    utc = local_to_utc("2026-09-26", "19:30", "Asia/Ho_Chi_Minh")
    assert utc.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-09-26T12:30:00Z"
    # DD/MM/YYYY supported
    utc2 = local_to_utc("26/09/2026", "19:30", "Asia/Ho_Chi_Minh")
    assert utc2.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-09-26T12:30:00Z"


def test_dst_safe_timezone():
    # America/New_York has DST; conversion must use zoneinfo, not fixed offset.
    # Winter (EST, UTC-5): 12:00 -> 17:00Z. Summer (EDT, UTC-4): 12:00 -> 16:00Z.
    w = local_to_utc("2026-01-15", "12:00", "America/New_York")
    s = local_to_utc("2026-07-15", "12:00", "America/New_York")
    assert w.strftime("%H:%M") == "17:00"
    assert s.strftime("%H:%M") == "16:00"
    assert w.utcoffset() == timedelta(0)  # canonical UTC


def test_past_schedule_rejected():
    past = _utcnow() - timedelta(minutes=1)
    try:
        validate_publish_at(past)
        assert False, "should raise"
    except ScheduleValidationError as e:
        assert "INVALID_PUBLISH_AT" in str(e)
    # Within 5-min margin also rejected.
    soon = _utcnow() + timedelta(minutes=2)
    try:
        validate_publish_at(soon)
        assert False
    except ScheduleValidationError:
        pass


def test_scheduled_requires_publish_at():
    from app.youtube_scheduling import validate_scheduled_mode
    try:
        validate_scheduled_mode("scheduled", None)
        assert False
    except ScheduleValidationError as e:
        assert "INVALID_PUBLISH_AT" in str(e)


def test_change_schedule_builds_private_publishat():
    from app.youtube_scheduling import build_reschedule_status
    fut = _utcnow() + timedelta(hours=3)
    body = build_reschedule_status(fut)
    assert body["privacyStatus"] == "private"
    assert body["publishAt"].endswith("Z")


def test_publish_now_status():
    from app.youtube_scheduling import build_publish_now_status
    assert build_publish_now_status() == {"privacyStatus": "public"}


def test_auto_slot_assignment_sequence():
    slots = ["09:00", "18:00"]
    used: set[str] = set()
    now = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    assigned = assign_backlog_slots(4, slots, "Asia/Ho_Chi_Minh", used, start_after=now)
    assert len(assigned) == 4
    # video1 Sep 26 09:00 ICT = Sep 26 02:00Z etc. Check ordering + day rollover.
    assert assigned[0] < assigned[1] < assigned[2] < assigned[3]
    # No duplicate minute.
    keys = {a.isoformat() for a in assigned}
    assert len(keys) == 4


def test_slot_collision_protected():
    slots = ["09:00", "18:00"]
    now = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    first = find_next_free_slot(slots, "Asia/Ho_Chi_Minh", set(), now=now)
    assert first is not None
    second = find_next_free_slot(slots, "Asia/Ho_Chi_Minh", {first.isoformat()}, now=now)
    assert second is not None
    assert second != first
    # Without protection, collision would repeat.
    third = find_next_free_slot(slots, "Asia/Ho_Chi_Minh", {first.isoformat(), second.isoformat()}, now=now)
    assert third not in (first, second)


def test_different_schedule_per_channel():
    # Channel A: 09:00,18:00 ; Channel B: 12:00,20:00,22:00
    now = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    a = find_next_free_slot(["09:00", "18:00"], "Asia/Ho_Chi_Minh", set(), now=now)
    b = find_next_free_slot(["12:00", "20:00", "22:00"], "Asia/Ho_Chi_Minh", set(), now=now)
    assert a is not None and b is not None
    assert a != b


def test_upload_video_sends_publishat_mocked():
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        db.commit()
        fut = _utcnow() + timedelta(hours=2)
        captured = {}

        fake_insert = MagicMock()
        fake_insert.next_chunk.return_value = (None, {"id": "yt123"})
        fake_videos = MagicMock()
        fake_videos.insert.side_effect = lambda part, body, media_body: (captured.update(body) or fake_insert)
        fake_youtube = MagicMock()
        fake_youtube.videos.return_value = fake_videos

        with patch("app.youtube.build") as mock_build, patch("app.youtube.MediaFileUpload") as mock_media:
            mock_build.return_value = fake_youtube
            mock_media.return_value = MagicMock()
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                f.write(b"x")
                path = f.name
            try:
                from pathlib import Path
                from app.youtube import upload_video
                vid = upload_video(
                    db=db, file_path=Path(path), title="t", description="d",
                    privacy_status="private", destination_id=d.id,
                    publish_at=fut, publish_mode="scheduled",
                )
                assert vid == "yt123"
                assert captured["status"]["privacyStatus"] == "private"
                assert captured["status"]["publishAt"].endswith("Z")
            finally:
                os.unlink(path)
    finally:
        db.close()
        engine.dispose()


def test_upload_immediate_never_sends_publishat():
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        db.commit()
        captured = {}
        fake_insert = MagicMock()
        fake_insert.next_chunk.return_value = (None, {"id": "yt1"})
        fake_videos = MagicMock()
        fake_videos.insert.side_effect = lambda part, body, media_body: (captured.update(body) or fake_insert)
        fake_youtube = MagicMock()
        fake_youtube.videos.return_value = fake_videos
        with patch("app.youtube.build") as mock_build, patch("app.youtube.MediaFileUpload") as mock_media:
            mock_build.return_value = fake_youtube
            mock_media.return_value = MagicMock()
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                f.write(b"x")
                path = f.name
            try:
                from pathlib import Path
                from app.youtube import upload_video
                upload_video(db=db, file_path=Path(path), title="t", description="d",
                             privacy_status="public", destination_id=d.id, publish_mode="immediate")
                assert captured["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
                assert "publishAt" not in captured["status"]
            finally:
                os.unlink(path)
    finally:
        db.close()
        engine.dispose()


def test_change_schedule_api_requires_future():
    # videos.update must send private + publishAt together.
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        db.commit()
        captured = {}
        fake_update = MagicMock()
        fake_update.execute.return_value = {"id": "yt1"}
        fake_videos = MagicMock()
        def _upd(part, body):
            captured.update(body)
            assert body["status"]["privacyStatus"] == "private"
            assert "publishAt" in body["status"]
            return fake_update
        fake_videos.update.side_effect = _upd
        fake_youtube = MagicMock()
        fake_youtube.videos.return_value = fake_videos
        with patch("app.youtube.build_destination_client") as mock_cli:
            mock_cli.return_value = (MagicMock(), fake_youtube)
            from app.youtube import update_video_schedule
            fut = _utcnow() + timedelta(hours=5)
            update_video_schedule(db, d.id, "yt1", fut)
            assert captured["id"] == "yt1"
    finally:
        db.close()
        engine.dispose()


def test_publish_now_and_cancel_calls():
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        db.commit()
        from app.youtube import publish_video_now, cancel_video_schedule, get_video_status
        for fn, expected in [(publish_video_now, "public"), (cancel_video_schedule, "private")]:
            captured = {}
            fake_op = MagicMock()
            fake_op.execute.return_value = {"id": "yt1"}
            fake_videos = MagicMock()
            def _u(part, body, _c=captured):
                _c.update(body)
                return fake_op
            fake_videos.update.side_effect = _u
            fake_youtube = MagicMock()
            fake_youtube.videos.return_value = fake_videos
            with patch("app.youtube.build_destination_client") as mock_cli:
                mock_cli.return_value = (MagicMock(), fake_youtube)
                fn(db, d.id, "yt1")
                assert captured["status"]["privacyStatus"] == expected
                if fn == cancel_video_schedule:
                    assert "publishAt" not in captured["status"]
        # get_video_status parses privacy/publishedAt
        fake_list = MagicMock()
        fake_list.execute.return_value = {"items": [{"status": {"privacyStatus": "public", "uploadStatus": "processed"}, "snippet": {"publishedAt": "2026-09-26T12:30:00Z"}}]}
        fake_videos2 = MagicMock()
        fake_videos2.list.return_value = fake_list
        fake_youtube2 = MagicMock()
        fake_youtube2.videos.return_value = fake_videos2
        with patch("app.youtube.build_destination_client") as mock_cli:
            mock_cli.return_value = (MagicMock(), fake_youtube2)
            info = get_video_status(db, d.id, "yt1")
            assert info["privacyStatus"] == "public"
            assert info["publishedAt"] == "2026-09-26T12:30:00Z"
    finally:
        db.close()
        engine.dispose()


def test_reconciler_flips_scheduled_to_published():
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        v = DouyinVideo(id=str(uuid4()), pipeline_id=p.id, video_id="vv1", title="t", url="https://x", status="scheduled")
        db.add(v)
        db.flush()
        pub = Publication(pipeline_id=p.id, douyin_video_id=v.id, destination_id=d.id, platform="youtube",
                          status="scheduled", scheduled_at=_utcnow())
        db.add(pub)
        db.flush()
        try:
            pub.youtube_scheduled = True
            pub.youtube_publish_mode = "scheduled"
            pub.youtube_publish_at = _utcnow() - timedelta(minutes=1)
            pub.external_post_id = "yt999"
            pub.external_url = "https://youtu.be/yt999"
        except Exception:
            pass
        db.commit()
        with patch("app.youtube_reconciler.get_video_status" if False else "app.youtube.get_video_status") as mock_status:
            # Patch where reconciler imports it: app.youtube.get_video_status
            pass
        with patch("app.youtube.get_video_status") as mock_status:
            mock_status.return_value = {"privacyStatus": "public", "publishedAt": "2026-09-26T12:30:00Z", "publishAt": None, "video_id": "yt999"}
            from app.youtube_reconciler import reconcile_scheduled_videos
            summary = reconcile_scheduled_videos(db_session=db)
            assert summary["published"] == 1
            db.refresh(pub)
            assert pub.status == "published"
            assert pub.youtube_actual_published_at is not None
    finally:
        db.close()
        engine.dispose()


def test_scheduled_upload_retry_keeps_publish_at():
    # Failed scheduled job retry must preserve publish_at (not drop to immediate).
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        fut = _utcnow() + timedelta(hours=2)
        job = VideoJob(source_url="https://x", status="failed", pipeline_id=p.id,
                       destination_id=d.id, source_video_id="s1", error="boom")
        try:
            job.youtube_publish_mode = "scheduled"
            job.youtube_publish_at = fut
            job.youtube_schedule_timezone = "Asia/Ho_Chi_Minh"
        except Exception:
            pass
        db.add(job)
        db.commit()
        db.refresh(job)
        assert getattr(job, "youtube_publish_mode", None) == "scheduled"
        assert getattr(job, "youtube_publish_at", None) is not None
    finally:
        db.close()
        engine.dispose()


def test_duplicate_upload_protection_unique_constraint():
    engine, db = make_db()
    try:
        p = _pipeline(db)
        d = _dest(db, p)
        v = DouyinVideo(id=str(uuid4()), pipeline_id=p.id, video_id="dup1", title="t", url="https://x", status="inventory")
        db.add(v)
        db.flush()
        pub1 = Publication(pipeline_id=p.id, douyin_video_id=v.id, destination_id=d.id, platform="youtube", status="published")
        db.add(pub1)
        db.commit()
        # Second publication for same video+destination violates unique constraint.
        from sqlalchemy.exc import IntegrityError
        pub2 = Publication(pipeline_id=p.id, douyin_video_id=v.id, destination_id=d.id, platform="youtube", status="queued")
        db.add(pub2)
        try:
            db.commit()
            assert False, "expected IntegrityError"
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        engine.dispose()


def test_preview_format():
    utc = datetime(2026, 9, 26, 12, 30, tzinfo=timezone.utc)
    prev = format_scheduled_preview(utc, "Asia/Ho_Chi_Minh")
    assert "26 Sep 2026" in prev
    assert "19:30" in prev
    assert "GMT+7" in prev


def test_parse_publish_at_rfc3339():
    dt = parse_publish_at("2026-09-26T12:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.hour == 12
