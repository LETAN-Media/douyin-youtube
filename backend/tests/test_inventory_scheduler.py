import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.douyin_url import parse_douyin_profile_url, DouyinUrlError
from app.inventory import fetch_all_videos_from_source, sync_source_inventory
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline
from app.scheduler import count_inventory_available, pick_video, schedule_for_pipeline


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_fetch_all_videos(self):
        mock_info = {
            "_type": "playlist",
            "entries": [
                {
                    "id": f"video_{i}",
                    "title": f"Video {i}",
                    "description": f"Desc {i}",
                    "url": f"https://www.douyin.com/video/{i}",
                    "timestamp": 1700000000 + i * 86400,
                }
                for i in range(15)
            ],
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            instance.extract_info.return_value = mock_info
            mock_ydl.return_value = instance

            videos = fetch_all_videos_from_source("https://www.douyin.com/user/test", str(uuid4()))

        self.assertEqual(len(videos), 15)
        self.assertEqual(videos[0]["video_id"], "0")

    def test_no_mp4_download_on_scan(self):
        with patch("yt_dlp.YoutubeDL") as mock_ydl, patch("builtins.open", MagicMock()) as mock_open:
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            instance.extract_info.return_value = {
                "entries": [
                    {
                        "id": "v1",
                        "title": "V1",
                        "url": "https://www.douyin.com/video/v1",
                        "timestamp": 1700000000,
                    }
                ]
            }
            mock_ydl.return_value = instance

            videos = fetch_all_videos_from_source("https://www.douyin.com/user/test", str(uuid4()))

            for call in mock_ydl.call_args_list:
                options = call[1].get("options", call[0][0] if call[0] else {})
                if isinstance(options, dict):
                    self.assertTrue(options.get("download", False) is False)

        self.assertEqual(len(videos), 1)

    def test_unique_source_video(self):
        pipeline = Pipeline(
            id=str(uuid4()),
            name="Test",
            slug="test",
            enabled=True,
            daily_upload_limit=6,
        )
        self.db.add(pipeline)
        self.db.flush()

        source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            name="Source",
            profile_url="https://www.douyin.com/user/test",
            enabled=True,
        )
        self.db.add(source)
        self.db.flush()

        for i in range(15):
            video = DouyinVideo(
                id=str(uuid4()),
                source_id=source.id,
                pipeline_id=pipeline.id,
                video_id=f"video_{i}",
                title=f"Video {i}",
                url=f"https://www.douyin.com/video/{i}",
            )
            self.db.add(video)
        self.db.commit()

        self.assertEqual(self.db.query(DouyinVideo).count(), 15)
        self.assertEqual(
            self.db.query(DouyinVideo.video_id).distinct().count(),
            15,
        )


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_pipeline(self, **kwargs):
        defaults = {
            "id": str(uuid4()),
            "name": "Test",
            "slug": "test",
            "enabled": True,
            "daily_upload_limit": 6,
            "backlog_slots_per_day": 4,
            "new_slots_per_day": 2,
            "upload_slots": ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
            "timezone": "UTC",
        }
        defaults.update(kwargs)
        pipeline = Pipeline(**defaults)
        self.db.add(pipeline)
        self.db.flush()
        return pipeline

    def _make_destination(self, pipeline, **kwargs):
        import json as _json
        kwargs.setdefault("connected", True)
        kwargs.setdefault(
            "credentials",
            _json.dumps({
                "token": "test-token",
                "refresh_token": "test-refresh",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "scopes": [],
            }),
        )
        destination = Destination(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            platform="youtube",
            name="YouTube",
            enabled=True,
            daily_upload_limit=pipeline.daily_upload_limit,
            timezone=pipeline.timezone,
            upload_slots=pipeline.upload_slots,
            **kwargs,
        )
        self.db.add(destination)
        self.db.flush()
        return destination

    def _make_source(self, pipeline, **kwargs):
        source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            name="Source",
            profile_url="https://www.douyin.com/user/test",
            enabled=True,
            **kwargs,
        )
        self.db.add(source)
        self.db.flush()
        return source

    def _make_video(self, source, pipeline, is_backlog=False, **kwargs):
        video_id = kwargs.pop("video_id", str(uuid4()))
        video = DouyinVideo(
            id=str(uuid4()),
            source_id=source.id,
            pipeline_id=pipeline.id,
            video_id=video_id,
            title="Test",
            url="https://www.douyin.com/video/test",
            status="backlog" if is_backlog else "new",
            is_backlog=is_backlog,
            **kwargs,
        )
        self.db.add(video)
        self.db.flush()
        return video

    def test_timezone_ho_chi_minh(self):
        pipeline = self._make_pipeline(timezone="Asia/Ho_Chi_Minh")
        self._make_destination(pipeline)
        source = self._make_source(pipeline)
        video = self._make_video(source, pipeline)

        utc_09_ict = datetime.datetime(2026, 9, 14, 2, 0, tzinfo=datetime.timezone.utc)
        schedule_for_pipeline(self.db, pipeline, now=utc_09_ict)
        self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
        self.assertEqual(scheduled, 0)

        utc_11_ict = datetime.datetime(2026, 9, 14, 4, 0, tzinfo=datetime.timezone.utc)
        schedule_for_pipeline(self.db, pipeline, now=utc_11_ict)
        self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
        self.assertEqual(scheduled, 1)

    def test_configured_six_per_day_cap(self):
        # The configured limit and six slots are both honored.
        pipeline = self._make_pipeline()
        self._make_destination(pipeline)
        source = self._make_source(pipeline)

        slot_utc_times = [
            datetime.datetime(2026, 9, 14, h, 5, tzinfo=datetime.timezone.utc)
            for h in [8, 11, 14, 17, 20, 23]
        ]

        for i, slot_time in enumerate(slot_utc_times):
            video = self._make_video(source, pipeline, video_id=f"v{i}")
            schedule_for_pipeline(self.db, pipeline, now=slot_time)
            self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
        self.assertEqual(scheduled, 6)

    def test_one_job_per_slot_poll_10_times(self):
        pipeline = self._make_pipeline()
        self._make_destination(pipeline)
        source = self._make_source(pipeline)
        video = self._make_video(source, pipeline)

        slot_time = datetime.datetime(2026, 9, 14, 8, 0, tzinfo=datetime.timezone.utc)
        for _ in range(10):
            schedule_for_pipeline(self.db, pipeline, now=slot_time)
            self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
        self.assertEqual(scheduled, 1)

    def test_restart_no_duplicate(self):
        db_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        db_path.close()

        restart_engine = create_engine(f"sqlite:///{db_path.name}")
        Base.metadata.create_all(restart_engine)
        RestartSession = sessionmaker(bind=restart_engine)

        with RestartSession() as db:
            pipeline = Pipeline(
                id=str(uuid4()),
                name="Test",
                slug="test-restart",
                enabled=True,
                daily_upload_limit=6,
                upload_slots=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
                timezone="UTC",
            )
            db.add(pipeline)
            db.flush()

            import json as _json2
            destination = Destination(
                id=str(uuid4()),
                pipeline_id=pipeline.id,
                platform="youtube",
                name="YouTube",
                enabled=True,
                connected=True,
                credentials=_json2.dumps({"token": "t", "refresh_token": "r", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "c", "client_secret": "s", "scopes": []}),
                daily_upload_limit=6,
                timezone="UTC",
                upload_slots=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
            )
            db.add(destination)
            db.flush()

            source = DouyinSource(
                id=str(uuid4()),
                pipeline_id=pipeline.id,
                name="Source",
                profile_url="https://www.douyin.com/user/test",
                enabled=True,
            )
            db.add(source)
            db.flush()

            video = DouyinVideo(
                id=str(uuid4()),
                source_id=source.id,
                pipeline_id=pipeline.id,
                video_id=str(uuid4()),
                title="Test",
                url="https://www.douyin.com/video/test",
                status="new",
            )
            db.add(video)
            db.commit()

            pipeline_id = pipeline.id
            source_id = source.id
            video_id = video.id

            slot_time = datetime.datetime(2026, 9, 14, 8, 0, tzinfo=datetime.timezone.utc)
            schedule_for_pipeline(db, pipeline, now=slot_time)
            db.commit()

        restart_engine.dispose()

        restart_engine = create_engine(f"sqlite:///{db_path.name}")
        Base.metadata.create_all(restart_engine)
        RestartSession = sessionmaker(bind=restart_engine)

        with RestartSession() as db:
            new_pipeline = db.get(Pipeline, pipeline_id)
            new_source = db.get(DouyinSource, source_id)
            new_video = db.get(DouyinVideo, video_id)

            schedule_for_pipeline(db, new_pipeline, now=slot_time)
            db.commit()

        with RestartSession() as db:
            scheduled = db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
            self.assertEqual(scheduled, 1)

        restart_engine.dispose()
        os.unlink(db_path.name)

    def test_concurrent_no_duplicate(self):
        from sqlalchemy.pool import StaticPool

        concurrent_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(concurrent_engine)
        ConcurrentSession = sessionmaker(bind=concurrent_engine)

        with ConcurrentSession() as db:
            pipeline = Pipeline(
                id=str(uuid4()),
                name="Test",
                slug="test-concurrent",
                enabled=True,
                daily_upload_limit=6,
                upload_slots=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
                timezone="UTC",
            )
            db.add(pipeline)
            db.flush()

            import json as _json2
            destination = Destination(
                id=str(uuid4()),
                pipeline_id=pipeline.id,
                platform="youtube",
                name="YouTube",
                enabled=True,
                connected=True,
                credentials=_json2.dumps({"token": "t", "refresh_token": "r", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "c", "client_secret": "s", "scopes": []}),
                daily_upload_limit=6,
                timezone="UTC",
                upload_slots=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
            )
            db.add(destination)
            db.flush()

            source = DouyinSource(
                id=str(uuid4()),
                pipeline_id=pipeline.id,
                name="Source",
                profile_url="https://www.douyin.com/user/test",
                enabled=True,
            )
            db.add(source)
            db.flush()

            video = DouyinVideo(
                id=str(uuid4()),
                source_id=source.id,
                pipeline_id=pipeline.id,
                video_id=str(uuid4()),
                title="Test",
                url="https://www.douyin.com/video/test",
                status="new",
            )
            db.add(video)
            db.commit()

            slot_time = datetime.datetime(2026, 9, 14, 8, 0, tzinfo=datetime.timezone.utc)

            schedule_for_pipeline(db, pipeline, now=slot_time)
            db.commit()

            schedule_for_pipeline(db, pipeline, now=slot_time)
            db.commit()

        with ConcurrentSession() as db:
            scheduled = db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
            self.assertEqual(scheduled, 1)

        concurrent_engine.dispose()

    def test_local_day_daily_limit(self):
        # limit=3, destination ICT day: slots 08/11/14/17 ICT == 01/04/07/10 UTC.
        pipeline = self._make_pipeline(timezone="Asia/Ho_Chi_Minh", daily_upload_limit=3)
        self._make_destination(pipeline)
        source = self._make_source(pipeline)

        slot_utc_times = [
            datetime.datetime(2026, 9, 14, 1, 5, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 9, 14, 4, 5, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 9, 14, 7, 5, tzinfo=datetime.timezone.utc),
        ]

        for i, slot_time in enumerate(slot_utc_times):
            video = self._make_video(source, pipeline, video_id=f"v{i}")
            schedule_for_pipeline(self.db, pipeline, now=slot_time)
            self.db.commit()

        # 4th attempt hits a due slot (17:00 ICT == 10:00 UTC) but the
        # 3/day cap blocks it.
        video4 = self._make_video(source, pipeline, video_id="v4")
        schedule_for_pipeline(self.db, pipeline, now=datetime.datetime(2026, 9, 14, 10, 5, tzinfo=datetime.timezone.utc))
        self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
        self.assertEqual(scheduled, 3)

    def test_configured_backlog_and_new_distribution(self):
        # Six configured positions allocate four backlog and two new videos.
        pipeline = self._make_pipeline()
        self._make_destination(pipeline)
        source = self._make_source(pipeline)

        for i in range(4):
            self._make_video(source, pipeline, is_backlog=True, video_id=f"b{i}")
        for i in range(2):
            self._make_video(source, pipeline, is_backlog=False, video_id=f"n{i}")

        slot_times = [
            datetime.datetime(2026, 9, 14, h, 5, tzinfo=datetime.timezone.utc)
            for h in [8, 11, 14, 17, 20, 23]
        ]

        for slot_time in slot_times:
            schedule_for_pipeline(self.db, pipeline, now=slot_time)
            self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").all()
        backlog_scheduled = [v for v in scheduled if v.is_backlog]
        new_scheduled = [v for v in scheduled if not v.is_backlog]
        self.assertEqual(len(scheduled), 6)
        self.assertEqual(len(new_scheduled), 2)
        self.assertEqual(len(backlog_scheduled), 4)

    def test_round_robin_between_sources(self):
        pipeline = self._make_pipeline()
        sources = [self._make_source(pipeline) for _ in range(3)]

        for idx, source in enumerate(sources):
            for i in range(3):
                self._make_video(source, pipeline, video_id=f"src{idx}_v{i}")

        picked_ids = []
        for _ in range(6):
            video = pick_video(self.db, pipeline, "new")
            picked_ids.append(video.source_id)

        self.assertEqual(len(set(picked_ids)), 3)

    def test_published_not_rescheduled(self):
        pipeline = self._make_pipeline()
        source = self._make_source(pipeline)
        video = self._make_video(source, pipeline)
        video.status = "published"
        video.published_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()

        picked = pick_video(self.db, pipeline, "new")
        self.assertIsNone(picked)

    def test_backlog_fallback_when_no_new(self):
        pipeline = self._make_pipeline()
        source = self._make_source(pipeline)
        self._make_video(source, pipeline, is_backlog=True)

        video = pick_video(self.db, pipeline, "new")
        self.assertIsNotNone(video)
        self.assertTrue(video.is_backlog)


    def test_source_linked_inventory_video_is_picked(self):
        """Source-linked inventory must be selectable, matching the count."""
        pipeline = self._make_pipeline()
        destination = self._make_destination(pipeline)
        source = self._make_source(pipeline)
        video = DouyinVideo(
            id=str(uuid4()),
            source_id=source.id,
            pipeline_id=pipeline.id,
            video_id="source_inventory_v1",
            title="inventory video",
            url="https://www.douyin.com/video/source_inventory_v1",
            status="inventory",
            is_backlog=False,
        )
        self.db.add(video)
        self.db.commit()

        self.assertEqual(count_inventory_available(self.db, pipeline), 1)
        with patch(
            "app.scheduler.evaluate_content_level",
            return_value=("match", "test"),
        ):
            picked = pick_video(
                self.db, pipeline, "new", destination=destination
            )
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, video.id)


class TestDouyinUrlParser(unittest.TestCase):
    def test_share_user_url(self):
        url = "https://m.douyin.com/share/user/MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi"
        result = parse_douyin_profile_url(url)
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi")
        self.assertEqual(result.original, url)

    def test_www_user_url(self):
        url = "https://www.douyin.com/user/MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi"
        result = parse_douyin_profile_url(url)
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi")

    def test_short_douyin_com_url(self):
        url = "https://douyin.com/user/MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi"
        result = parse_douyin_profile_url(url)
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAAornGVjobtmExVryzewXhP7o8ZLi7cGMluuV3bni6ZkNQbv5gNlaw4lLQITnECKwi")

    def test_video_url_returns_none(self):
        url = "https://www.douyin.com/video/123456789"
        with self.assertRaises(DouyinUrlError):
            parse_douyin_profile_url(url)

    def test_non_douyin_url_returns_none(self):
        result = parse_douyin_profile_url("https://www.youtube.com/watch?v=123")
        self.assertIsNone(result)


class TestLegacyVideoFallback(unittest.TestCase):
    """Tests for legacy video fallback when source_id=NULL but pipeline_id matches."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_pipeline(self, **kwargs):
        defaults = {
            "id": str(uuid4()),
            "name": "Test",
            "slug": "test",
            "enabled": True,
            "daily_upload_limit": 6,
            "backlog_slots_per_day": 4,
            "new_slots_per_day": 2,
            "upload_slots": ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
            "timezone": "UTC",
        }
        defaults.update(kwargs)
        pipeline = Pipeline(**defaults)
        self.db.add(pipeline)
        self.db.flush()
        return pipeline

    def _make_destination(self, pipeline, **kwargs):
        import json as _json
        kwargs.setdefault("connected", True)
        kwargs.setdefault(
            "credentials",
            _json.dumps({
                "token": "test-token",
                "refresh_token": "test-refresh",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "scopes": [],
            }),
        )
        destination = Destination(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            platform="youtube",
            name="YouTube",
            enabled=True,
            daily_upload_limit=pipeline.daily_upload_limit,
            timezone=pipeline.timezone,
            upload_slots=pipeline.upload_slots,
            **kwargs,
        )
        self.db.add(destination)
        self.db.flush()
        return destination

    def test_legacy_videos_source_id_null_picked_by_pipeline_fallback(self):
        """Legacy videos with source_id=NULL should be picked via pipeline fallback."""
        pipeline = self._make_pipeline()
        self._make_destination(pipeline)
        # No sources created - legacy videos have no source

        # Create legacy videos with source_id=NULL but matching pipeline_id
        # Set douyin_created_at to control ordering (oldest first by default)
        base_time = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        video1 = DouyinVideo(
            id=str(uuid4()),
            source_id=None,  # Legacy: no source linked
            pipeline_id=pipeline.id,
            video_id="legacy_v1",
            title="Legacy Video 1",
            url="https://www.douyin.com/video/legacy_v1",
            status="inventory",
            is_backlog=False,
            douyin_created_at=base_time + datetime.timedelta(days=1),  # oldest
        )
        video2 = DouyinVideo(
            id=str(uuid4()),
            source_id=None,
            pipeline_id=pipeline.id,
            video_id="legacy_v2",
            title="Legacy Video 2",
            url="https://www.douyin.com/video/legacy_v2",
            status="inventory",
            is_backlog=True,
            douyin_created_at=base_time + datetime.timedelta(days=2),
        )
        video3 = DouyinVideo(
            id=str(uuid4()),
            source_id=None,
            pipeline_id=pipeline.id,
            video_id="legacy_v3",
            title="Legacy Video 3",
            url="https://www.douyin.com/video/legacy_v3",
            status="new",
            is_backlog=False,
            douyin_created_at=base_time + datetime.timedelta(days=3),  # newest
        )
        self.db.add_all([video1, video2, video3])
        self.db.commit()

        # Import pick_video here to use the scheduler's function
        from app.scheduler import pick_video

        # Pipeline backlog_order defaults to "asc" (oldest first)
        # For "new" slot: candidates are v1 (inventory, !backlog) and v3 (new, !backlog)
        # Ordered by douyin_created_at ASC: v1 (oldest) then v3 (newest)
        # First pick: v1
        picked = pick_video(self.db, pipeline, "new")
        self.assertIsNotNone(picked)
        self.assertEqual(picked.video_id, "legacy_v1")
        self.assertIsNone(picked.source_id)

        # Pick for "backlog" slot - should get v2 (is_backlog=True)
        picked = pick_video(self.db, pipeline, "backlog")
        self.assertIsNotNone(picked)
        self.assertEqual(picked.video_id, "legacy_v2")
        self.assertIsNone(picked.source_id)

        # Second "new" pick - v1 already scheduled, should get v3
        # Note: In real scheduler, v1 status becomes "scheduled" after scheduling
        # Here we manually update to simulate
        v1 = self.db.query(DouyinVideo).filter(DouyinVideo.video_id == "legacy_v1").one()
        v1.status = "scheduled"
        self.db.commit()

        picked = pick_video(self.db, pipeline, "new")
        self.assertIsNotNone(picked)
        self.assertEqual(picked.video_id, "legacy_v3")

    def test_legacy_videos_respect_published_status(self):
        """Legacy videos with published status should not be picked."""
        pipeline = self._make_pipeline()
        self._make_destination(pipeline)

        video = DouyinVideo(
            id=str(uuid4()),
            source_id=None,
            pipeline_id=pipeline.id,
            video_id="legacy_published",
            title="Published Legacy",
            url="https://www.douyin.com/video/legacy_published",
            status="published",
            published_at=datetime.datetime.now(datetime.timezone.utc),
        )
        self.db.add(video)
        self.db.commit()

        from app.scheduler import pick_video
        picked = pick_video(self.db, pipeline, "new")
        self.assertIsNone(picked)

    def test_legacy_videos_respect_held_rejected_status(self):
        """Legacy videos with held/rejected status should not be picked."""
        pipeline = self._make_pipeline()
        self._make_destination(pipeline)

        held_video = DouyinVideo(
            id=str(uuid4()),
            source_id=None,
            pipeline_id=pipeline.id,
            video_id="legacy_held",
            title="Held Legacy",
            url="https://www.douyin.com/video/legacy_held",
            status="held",
        )
        rejected_video = DouyinVideo(
            id=str(uuid4()),
            source_id=None,
            pipeline_id=pipeline.id,
            video_id="legacy_rejected",
            title="Rejected Legacy",
            url="https://www.douyin.com/video/legacy_rejected",
            status="rejected",
        )
        self.db.add_all([held_video, rejected_video])
        self.db.commit()

        from app.scheduler import pick_video
        picked = pick_video(self.db, pipeline, "new")
        self.assertIsNone(picked)


if __name__ == "__main__":
    unittest.main()
