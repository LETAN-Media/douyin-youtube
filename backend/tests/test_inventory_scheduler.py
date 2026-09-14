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
from app.models import DouyinSource, DouyinVideo, Pipeline
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
        pipeline = Pipeline(
            id=str(uuid4()),
            name="Test",
            slug="test",
            enabled=True,
            daily_upload_limit=6,
            backlog_slots_per_day=4,
            new_slots_per_day=2,
            upload_slots=["09:00", "13:00", "17:00", "21:00"],
            **kwargs,
        )
        self.db.add(pipeline)
        self.db.flush()
        return pipeline

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

    def test_daily_limit_6(self):
        pipeline = self._make_pipeline()
        source = self._make_source(pipeline)

        now = datetime.datetime.now(datetime.timezone.utc)
        for i in range(6):
            job = __import__("app.models", fromlist=["VideoJob"]).VideoJob(
                id=str(uuid4()),
                source_url="https://www.douyin.com/video/x",
                status="published",
                pipeline_id=pipeline.id,
                source_video_id=str(uuid4()),
                created_at=now - datetime.timedelta(hours=i),
            )
            self.db.add(job)
        self.db.commit()

        video = self._make_video(source, pipeline)
        schedule_for_pipeline(self.db, pipeline)
        self.db.commit()

        scheduled = self.db.query(DouyinVideo).filter(DouyinVideo.status == "scheduled").count()
        self.assertEqual(scheduled, 0)

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
