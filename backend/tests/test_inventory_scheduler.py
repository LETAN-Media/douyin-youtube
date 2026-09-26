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
from app.douyin_url import parse_douyin_profile_url
from app.inventory import fetch_all_videos_from_source, sync_source_inventory
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline
from app.scheduler import pick_video, schedule_for_pipeline


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

    def test_four_shorts_per_day_cap(self):
        # Fixed rule: max 4 shorts/day/channel even with 6 configured slots.
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
        self.assertEqual(scheduled, 4)

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

    def test_backlog_new_ratio(self):
        # Fixed 4/day cap: backlog fills first, new videos wait for next days.
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
        self.assertEqual(len(scheduled), 4)
        self.assertEqual(len(backlog_scheduled), 4)
        self.assertEqual(len(new_scheduled), 0)

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
        result = parse_douyin_profile_url(url)
        self.assertIsNone(result)

    def test_non_douyin_url_returns_none(self):
        result = parse_douyin_profile_url("https://www.youtube.com/watch?v=123")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
