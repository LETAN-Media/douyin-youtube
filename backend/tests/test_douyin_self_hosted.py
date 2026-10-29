import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import douyin_import
from app.db import Base
from app.douyin_self_hosted import (
    DouyinSelfHostedClient,
    DouyinSelfHostedConfig,
    DouyinSelfHostedError,
    extract_video_id,
)
from app.integrations.rapidapi.errors import RapidApiFailure, RapidApiPoolError
from app.models import DouyinScanJob, DouyinSource, DouyinVideo, Pipeline


class TestDouyinSelfHostedClient(unittest.TestCase):
    def test_extract_video_id(self):
        self.assertEqual(
            extract_video_id("https://www.douyin.com/video/7636227260496269297"),
            "7636227260496269297",
        )
        self.assertEqual(
            extract_video_id("https://www.douyin.com/video/7636227260496269297?param=1"),
            "7636227260496269297",
        )
        self.assertEqual(
            extract_video_id("7636227260496269297"),
            "7636227260496269297",
        )
        self.assertIsNone(extract_video_id("https://www.douyin.com/user/123"))
        self.assertIsNone(extract_video_id(""))

    @patch("httpx.Client.post")
    def test_fetch_video_items_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "total": 2,
            "sec_user_id": "test_sec_uid",
            "video_urls": [
                "https://www.douyin.com/video/7636227260496269297",
                "https://www.douyin.com/video/7604458729723452411",
            ],
        }
        mock_post.return_value = mock_resp

        client = DouyinSelfHostedClient(
            DouyinSelfHostedConfig(
                api_key="test_key",
                base_url="http://vps:8088",
                fallback_url="https://render.com",
            )
        )
        items = client.fetch_video_items("https://v.douyin.com/test/", max_count=10)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["video_id"], "7636227260496269297")
        self.assertEqual(items[1]["video_id"], "7604458729723452411")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["X-API-Key"], "test_key")
        self.assertEqual(kwargs["json"]["url"], "https://v.douyin.com/test/")

    @patch("httpx.Client.post")
    def test_failover_to_fallback_url(self, mock_post):
        def side_effect(url, **kwargs):
            if "vps" in url:
                mock_err_resp = MagicMock()
                mock_err_resp.status_code = 502
                mock_err_resp.text = "Bad Gateway"
                return mock_err_resp
            mock_ok_resp = MagicMock()
            mock_ok_resp.status_code = 200
            mock_ok_resp.json.return_value = {
                "success": True,
                "total": 1,
                "video_urls": ["https://www.douyin.com/video/7636227260496269297"],
            }
            return mock_ok_resp

        mock_post.side_effect = side_effect

        client = DouyinSelfHostedClient(
            DouyinSelfHostedConfig(
                api_key="test_key",
                base_url="http://vps:8088",
                fallback_url="https://render.com",
            )
        )
        items = client.fetch_video_items("https://v.douyin.com/test/")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["video_id"], "7636227260496269297")
        self.assertEqual(mock_post.call_count, 2)


class TestDouyinSelfHostedIntegration(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db: Session = self.Session()

        self.pipeline = Pipeline(
            id=str(uuid4()),
            name="Dance Shorts",
            slug="dance-shorts",
            enabled=True,
        )
        self.source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=self.pipeline.id,
            name="Creator Dance",
            douyin_sec_uid="MS4wLjABAAAAtest",
            profile_url="https://www.douyin.com/user/MS4wLjABAAAAtest",
            original_profile_url="https://v.douyin.com/test/",
            enabled=True,
        )
        self.db.add_all([self.pipeline, self.source])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_auto_fallback_when_rapidapi_fails(self):
        # 1. Video already published in DB
        published_video = DouyinVideo(
            id=str(uuid4()),
            pipeline_id=self.pipeline.id,
            source_id=self.source.id,
            video_id="7696123486017152433",
            url="https://www.douyin.com/video/7696123486017152433",
            status="published",
        )
        self.db.add(published_video)
        self.db.commit()

        # Queue a replenish scan job
        job = DouyinScanJob(
            id=str(uuid4()),
            pipeline_id=self.pipeline.id,
            source_id=self.source.id,
            scan_mode="replenish",
            status="running",
            locked_at=douyin_import.utcnow(),
            locked_by="test-worker",
        )
        self.db.add(job)
        self.db.commit()

        # Mock RapidAPI pool raising RapidApiPoolError (like the 503 code 301 we saw on production)
        rapidapi_failure = RapidApiFailure(
            "COLLECT FAILED",
            provider_id="rapidapi_fallback_1",
            kind="unavailable",
            retryable=True,
        )
        rapidapi_error = RapidApiPoolError([rapidapi_failure])

        # Mock DouyinSelfHostedClient returning the published video + a brand new video
        mock_self_hosted_items = [
            {
                "video_id": "7696123486017152433",  # Already published
                "url": "https://www.douyin.com/video/7696123486017152433",
                "title": "",
            },
            {
                "video_id": "7636227260496269297",  # Brand new video!
                "url": "https://www.douyin.com/video/7636227260496269297",
                "title": "",
            },
        ]

        with (
            patch.object(douyin_import, "SessionLocal", self.Session),
            patch("app.douyin_quota.SessionLocal", self.Session),
            patch.object(douyin_import, "_provider", side_effect=rapidapi_error),
            patch("app.douyin_self_hosted.DouyinSelfHostedClient.fetch_video_items", return_value=mock_self_hosted_items),
        ):
            summary = douyin_import.execute_scan_job(job.id, worker_id="test-worker")

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["provider"], "douyin_self_hosted")
        self.assertEqual(summary["new"], 1)

        # Verify DB state
        self.db.expire_all()
        saved_job = self.db.get(DouyinScanJob, job.id)
        self.assertEqual(saved_job.status, "completed")
        self.assertEqual(saved_job.provider_id, "douyin_self_hosted")
        self.assertEqual(saved_job.videos_new, 1)
        self.assertEqual(saved_job.videos_duplicate, 1)

        # Verify published video was NOT reverted or modified
        self.db.expire_all()
        pv = self.db.execute(
            select(DouyinVideo).where(DouyinVideo.video_id == "7696123486017152433")
        ).scalar_one()
        self.assertEqual(pv.status, "published")

        # Verify new video was created
        nv = self.db.execute(
            select(DouyinVideo).where(DouyinVideo.video_id == "7636227260496269297")
        ).scalar_one()
        self.assertIn(nv.status, ["new", "inventory"])

    def test_scan_source_self_hosted_explicit_call(self):
        mock_self_hosted_items = [
            {
                "video_id": "7694573328141519985",
                "url": "https://www.douyin.com/video/7694573328141519985",
                "title": "New Dance",
            },
        ]
        with (
            patch.object(douyin_import, "SessionLocal", self.Session),
            patch("app.douyin_self_hosted.DouyinSelfHostedClient.fetch_video_items", return_value=mock_self_hosted_items),
        ):
            summary = douyin_import.scan_source_self_hosted(self.source.id, max_count=50)

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["provider"], "douyin_self_hosted")
        self.assertEqual(summary["new"], 1)

        self.db.expire_all()
        nv = self.db.execute(
            select(DouyinVideo).where(DouyinVideo.video_id == "7694573328141519985")
        ).scalar_one_or_none()
        self.assertIsNotNone(nv)


if __name__ == "__main__":
    unittest.main()
