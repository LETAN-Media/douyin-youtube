import json
import unittest
from datetime import datetime, timedelta, timezone
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
    EndpointCircuitBreaker,
    extract_video_id,
    shorten_provider_error,
)
from app.inventory import _upsert_videos
from app.main import _format_iso_utc
from app.models import DouyinScanJob, DouyinSource, DouyinVideo, Pipeline


class TestDouyinAutoScanRegression(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database for test isolation
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db: Session = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    # -------------------------------------------------------------
    # 1. Error Formatting & Sanitization
    # -------------------------------------------------------------
    def test_shorten_provider_error(self):
        # Render HTTP 502 error
        raw_render_502 = "PROVIDER_ERROR: Provider https://douyin-api-8xzt.onrender.com error (HTTP 502)"
        short_502 = shorten_provider_error(raw_render_502)
        self.assertEqual(short_502, "Lỗi cổng API (HTTP 502)")

        # HTTP 503 error
        raw_503 = "HTTP 503 Service Unavailable"
        self.assertEqual(shorten_provider_error(raw_503), "Dịch vụ tạm thời quá tải (HTTP 503)")

        # HTTP 500 error
        raw_500 = "HTTP 500 Internal Server Error"
        self.assertEqual(shorten_provider_error(raw_500), "Lỗi máy chủ nội bộ (HTTP 500)")

        # HTTP 429 rate limit
        raw_429 = "Provider returned 429 Too Many Requests"
        self.assertEqual(shorten_provider_error(raw_429), "Giới hạn tần suất (HTTP 429)")

        # Timeout
        raw_timeout = "HTTP timed out after 30 seconds connecting to http://162.4.177.109:8088"
        self.assertEqual(shorten_provider_error(raw_timeout), "Hết thời gian chờ (Timeout)")

        # Connection refused / offline
        raw_conn = "Connection refused to http://162.4.177.109:8088"
        self.assertEqual(shorten_provider_error(raw_conn), "Máy chủ ngoại tuyến (Offline)")

        # None / empty
        self.assertEqual(shorten_provider_error(None), "")

    # -------------------------------------------------------------
    # 2. Circuit Breaker Behavior
    # -------------------------------------------------------------
    def test_circuit_breaker_transitions(self):
        cb = EndpointCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
        endpoint = "http://162.4.177.109:8088"

        self.assertTrue(cb.is_available(endpoint))

        # 2 failures -> still available
        cb.record_failure(endpoint)
        cb.record_failure(endpoint)
        self.assertTrue(cb.is_available(endpoint))

        # 3rd failure -> breaker opens
        cb.record_failure(endpoint)
        self.assertFalse(cb.is_available(endpoint))

        # Fast forward time past cooldown
        cb._states[endpoint].last_failure_at -= 15.0
        # Half-open probe is allowed
        self.assertTrue(cb.is_available(endpoint))

        # If success recorded during half-open, breaker closes
        cb.record_success(endpoint)
        self.assertTrue(cb.is_available(endpoint))
        self.assertEqual(cb._states[endpoint].failures, 0)
        self.assertFalse(cb._states[endpoint].is_open)

    # -------------------------------------------------------------
    # 3. Provider Failover: Primary 500 -> Render Fallback 502
    # -------------------------------------------------------------
    @patch("time.sleep", return_value=None)
    @patch("httpx.Client.post")
    def test_client_failover_primary_to_fallback(self, mock_post, mock_sleep):
        # Call 1: Primary returns 500 (attempt 1)
        # Call 2: Primary returns 500 (retry attempt 2)
        # Call 3: Fallback returns 502 (attempt 1)
        # Call 4: Fallback returns 502 (retry attempt 2)
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.text = "Internal Server Error"

        resp_502 = MagicMock()
        resp_502.status_code = 502
        resp_502.text = "Bad Gateway"

        mock_post.side_effect = [resp_500, resp_500, resp_502, resp_502]

        client = DouyinSelfHostedClient(
            DouyinSelfHostedConfig(
                api_key="test_key",
                base_url="http://162.4.177.109:8088",
                fallback_url="https://douyin-api-8xzt.onrender.com",
            )
        )

        with self.assertRaises(DouyinSelfHostedError) as ctx:
            client.fetch_video_items("https://v.douyin.com/test/")

        self.assertEqual(ctx.exception.code, "BAD_GATEWAY")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertTrue(ctx.exception.retryable)

    # -------------------------------------------------------------
    # 4. Fallback from SelfHosted to RapidAPI Pool
    # -------------------------------------------------------------
    def test_execute_rapidapi_fallback_success(self):
        pipeline = Pipeline(id=str(uuid4()), name="Test Pipe", slug="test-pipe")
        self.db.add(pipeline)
        self.db.commit()

        source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            name="Daniel Xu",
            original_profile_url="https://v.douyin.com/DanielXu/",
            douyin_sec_uid="MS4wLjABAAAA_test",
        )
        self.db.add(source)
        self.db.commit()

        job = DouyinScanJob(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            source_id=source.id,
            scan_mode="replenish",
            status="running",
        )
        self.db.add(job)
        self.db.commit()

        mock_pool = MagicMock()
        mock_pool.has_available_provider.return_value = True

        mock_session = MagicMock()
        mock_session.provider_id = "rapidapi_justone"
        mock_session.fetch_page.return_value = {
            "items": [
                {
                    "video_id": "7111222333444",
                    "title": "Fallback dance video",
                    "cover_url": "https://example.com/cover.jpg",
                    "duration": 30,
                    "share_url": "https://www.douyin.com/video/7111222333444",
                    "published_at": "2026-10-29T00:00:00Z",
                }
            ],
            "has_more": False,
            "cursor": None,
        }
        mock_pool.open_scan.return_value = mock_session

        with patch.object(douyin_import, "SessionLocal", self.Session), \
             patch("app.douyin_quota.can_spend", return_value=True), \
             patch("app.integrations.rapidapi.pool.get_rapidapi_pool", return_value=mock_pool):

            fallback_result = douyin_import._execute_rapidapi_fallback(
                job_id=job.id,
                source_id=source.id,
                pipeline_id=pipeline.id,
                sec_uid="MS4wLjABAAAA_test",
                scan_mode="replenish",
                is_backlog=False,
                existing_error="HTTP 502 Bad Gateway",
            )

        self.assertIsNotNone(fallback_result)
        self.assertEqual(fallback_result["status"], "completed")
        self.assertEqual(fallback_result["provider"], "rapidapi_justone")
        self.assertEqual(fallback_result["new"], 1)

    # -------------------------------------------------------------
    # 5. Scan Job Retry with Exponential Backoff
    # -------------------------------------------------------------
    def test_is_retryable_error(self):
        self.assertTrue(douyin_import._is_retryable_error("HTTP 502"))
        self.assertTrue(douyin_import._is_retryable_error("Bad Gateway"))
        self.assertTrue(douyin_import._is_retryable_error("ReadTimeout"))
        self.assertTrue(douyin_import._is_retryable_error("429 Too Many Requests"))
        self.assertFalse(douyin_import._is_retryable_error("Invalid URL scheme"))
        self.assertFalse(douyin_import._is_retryable_error("User does not exist"))

    @patch("app.douyin_import._PageSource")
    def test_execute_scan_job_schedules_backoff_retry(self, mock_page_source_cls):
        # Force a 502 error during page_source.fetch_page()
        mock_source_instance = MagicMock()
        mock_source_instance.provider_id = "douyin_self_hosted"
        mock_source_instance.fetch_page.side_effect = Exception("PROVIDER_ERROR: Provider https://douyin-api-8xzt.onrender.com error (HTTP 502)")
        mock_page_source_cls.return_value = mock_source_instance

        pipeline = Pipeline(id=str(uuid4()), name="JoyBeat Dance", slug="joybeat-dance")
        self.db.add(pipeline)
        self.db.commit()

        source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            name="Daniel Xu",
            original_profile_url="https://v.douyin.com/DanielXu/",
            douyin_sec_uid="MS4wLjABAAAA_test",
        )
        self.db.add(source)
        self.db.commit()

        job = DouyinScanJob(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            source_id=source.id,
            scan_mode="replenish",
            status="pending",
            retry_count=0,
        )
        self.db.add(job)
        self.db.commit()

        with patch.object(douyin_import, "SessionLocal", self.Session), \
             patch("app.douyin_import._execute_rapidapi_fallback", return_value=None):

            res = douyin_import.execute_scan_job(job.id, worker_id="test-worker")

        # Reload job and source from DB
        self.db.expire_all()
        refreshed_job = self.db.get(DouyinScanJob, job.id)
        refreshed_source = self.db.get(DouyinSource, source.id)

        # Job should be scheduled for retry (status="pending", retry_count=1)
        self.assertEqual(refreshed_job.status, "pending")
        self.assertEqual(refreshed_job.retry_count, 1)
        self.assertIsNotNone(refreshed_job.next_retry_at)

        # Next retry should be within ~2 minutes
        now = datetime.now(timezone.utc)
        diff_seconds = (refreshed_job.next_retry_at.replace(tzinfo=timezone.utc) - now).total_seconds()
        self.assertTrue(100 <= diff_seconds <= 130)

        # Error message should be sanitized (not raw 502 technical URL trace)
        self.assertEqual(refreshed_job.error, "Lỗi cổng API (HTTP 502)")
        self.assertEqual(refreshed_source.inventory_sync_error, "Lỗi cổng API (HTTP 502)")
        self.assertEqual(refreshed_source.provider_status, "provider_error")

    # -------------------------------------------------------------
    # 6. Deduplication & Inventory Preservation
    # -------------------------------------------------------------
    def test_upsert_videos_preserves_existing_inventory_and_prevents_duplicates(self):
        pipeline = Pipeline(id=str(uuid4()), name="JoyBeat Dance", slug="joybeat-dance", backlog_threshold_days=7)
        self.db.add(pipeline)
        self.db.commit()

        source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            name="Daniel Xu",
            original_profile_url="https://v.douyin.com/DanielXu/",
        )
        self.db.add(source)
        self.db.commit()

        # Simulate existing inventory with different statuses (published, scheduled)
        v_published = DouyinVideo(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            source_id=source.id,
            video_id="video_published_101",
            title="Dance 101 Original",
            url="https://www.douyin.com/video/video_published_101",
            status="published",
        )
        v_scheduled = DouyinVideo(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            source_id=source.id,
            video_id="video_scheduled_102",
            title="Dance 102 Original",
            url="https://www.douyin.com/video/video_scheduled_102",
            status="scheduled",
        )
        self.db.add_all([v_published, v_scheduled])
        self.db.commit()

        # Rescan returns existing videos (with changed title) + 1 brand new video
        scanned_items = [
            {
                "video_id": "video_published_101",
                "title": "Dance 101 - Rescan modified title",
                "url": "https://www.douyin.com/video/video_published_101",
                "cover_url": "https://example.com/101.jpg",
                "duration": 35,
            },
            {
                "video_id": "video_scheduled_102",
                "title": "Dance 102 - Rescan modified title",
                "url": "https://www.douyin.com/video/video_scheduled_102",
                "cover_url": "https://example.com/102.jpg",
                "duration": 40,
            },
            {
                "video_id": "video_brand_new_103",
                "title": "Dance 103",
                "url": "https://www.douyin.com/video/video_brand_new_103",
                "cover_url": "https://example.com/103.jpg",
                "duration": 45,
            },
        ]

        # Upsert scanned items
        new_count, updated_count = _upsert_videos(
            self.db,
            source=source,
            pipeline=pipeline,
            videos=scanned_items,
            backfill=False,
        )
        self.db.commit()

        # Only 1 new video should be added, 2 updated
        self.assertEqual(new_count, 1)
        self.assertEqual(updated_count, 2)

        # Verify all videos in db
        videos = list(self.db.execute(select(DouyinVideo).where(DouyinVideo.source_id == source.id)).scalars().all())
        self.assertEqual(len(videos), 3)

        # Verify published and scheduled statuses and titles were NOT overwritten
        by_id = {v.video_id: v for v in videos}
        self.assertEqual(by_id["video_published_101"].status, "published")
        self.assertEqual(by_id["video_published_101"].title, "Dance 101 Original")  # Protected!
        self.assertEqual(by_id["video_scheduled_102"].status, "scheduled")
        self.assertEqual(by_id["video_scheduled_102"].title, "Dance 102 Original")  # Protected!
        self.assertEqual(by_id["video_brand_new_103"].status, "new")

    # -------------------------------------------------------------
    # 7. Timezone Offset Formatting
    # -------------------------------------------------------------
    def test_format_iso_utc(self):
        # Naive datetime is stamped with UTC
        naive_dt = datetime(2026, 10, 29, 8, 28, 42)
        formatted = _format_iso_utc(naive_dt)
        self.assertIn("+00:00", formatted)
        self.assertEqual(formatted, "2026-10-29T08:28:42+00:00")

        # None stays None
        self.assertIsNone(_format_iso_utc(None))

        # Timezone-aware datetime remains UTC
        tz_dt = datetime(2026, 10, 29, 15, 28, 42, tzinfo=timezone(timedelta(hours=7)))
        formatted_tz = _format_iso_utc(tz_dt)
        self.assertEqual(formatted_tz, "2026-10-29T08:28:42+00:00")


if __name__ == "__main__":
    unittest.main()
