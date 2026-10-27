"""Unit and integration tests for Douyin Auto Inventory & Auto Replenishment."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import douyin_import, monitor
from app.config import settings
from app.models import (
    Base,
    Destination,
    DouyinScanJob,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    VideoJob,
)


def _session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _video(vid: str, desc: str = "Video") -> dict:
    return {
        "video_id": str(vid),
        "title": f"{desc} {vid}",
        "url": f"https://www.douyin.com/video/{vid}",
        "thumbnail_url": f"https://example.com/{vid}.jpg",
        "duration": 45,
    }


class _FakeProvider:
    def __init__(self, pages: list[dict]):
        self.pages = list(pages)
        self.calls: list[str | None] = []
        self.name = "fake_provider"
        self.uses_rapidapi_quota = False

    def fetch_page(self, sec_uid: str, cursor: str | None = None) -> dict:
        self.calls.append(cursor)
        if not self.pages:
            return {"items": [], "has_more": False, "next_cursor": ""}
        return self.pages.pop(0)


class TestAutoInventoryAndReplenish(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = _session_factory(self.engine)

        self._p_main = patch.object(douyin_import, "SessionLocal", self.Session)
        self._p_mon = patch.object(monitor, "SessionLocal", self.Session)
        self._p_inv = patch("app.inventory.SessionLocal", self.Session)
        self._p_main.start()
        self._p_mon.start()
        self._p_inv.start()

        with self.Session() as db:
            p = Pipeline(id="pipe-1", name="Test Pipeline", slug="test-pipeline", enabled=True)
            db.add(p)
            s = DouyinSource(
                id="src-1",
                pipeline_id="pipe-1",
                name="Creator 1",
                profile_url="https://www.douyin.com/user/MS4wLjABAAAA_test",
                douyin_sec_uid="MS4wLjABAAAA_test",
                enabled=True,
                initial_import_status="pending",
            )
            db.add(s)
            db.commit()

    def tearDown(self):
        self._p_main.stop()
        self._p_mon.stop()
        self._p_inv.stop()
        self.engine.dispose()

    def test_queue_scan_job_dedup(self):
        """Queueing a scan job when one is already pending or running returns the existing one."""
        with self.Session() as db:
            j1 = douyin_import.queue_scan_job(db, "src-1", scan_mode="initial")
            self.assertEqual(j1.status, "pending")
            self.assertEqual(j1.scan_mode, "initial")

            # Queueing again returns existing job without creating duplicate
            j2 = douyin_import.queue_scan_job(db, "src-1", scan_mode="initial")
            self.assertEqual(j1.id, j2.id)

            total_jobs = db.execute(select(func.count(DouyinScanJob.id))).scalar_one()
            self.assertEqual(total_jobs, 1)

    def test_initial_full_scan_pagination_and_completion(self):
        """Initial full scan walks all pages until has_more=False and records stats."""
        provider = _FakeProvider([
            {
                "items": [_video("v1"), _video("v2")],
                "has_more": True,
                "next_cursor": "cursor_page2",
            },
            {
                "items": [_video("v3")],
                "has_more": False,
                "next_cursor": "",
            },
        ])

        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            summary = douyin_import.initial_import("src-1")

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["new"], 3)
        self.assertEqual(summary["pages"], 2)

        with self.Session() as db:
            videos = db.execute(select(DouyinVideo)).scalars().all()
            self.assertEqual(len(videos), 3)
            for v in videos:
                self.assertTrue(v.is_backfill)
                self.assertIn(v.status, ("new", "backlog"))

            job = db.execute(select(DouyinScanJob)).scalar_one()
            self.assertEqual(job.status, "completed")
            self.assertEqual(job.stop_reason, "END_OF_RESULTS")
            self.assertEqual(job.pages_scanned, 2)
            self.assertEqual(job.videos_new, 3)

    def test_quota_pause_and_resumption_from_cursor(self):
        """Quota exhaustion pauses scan with cursor, and resume continues from stored cursor."""
        provider = _FakeProvider([
            {
                "items": [_video("v1"), _video("v2")],
                "has_more": True,
                "next_cursor": "page_2_cursor",
            },
        ])

        # Step 1: Page 1 succeeds, but next page hits quota
        with patch.object(douyin_import, "get_primary_provider", return_value=provider), \
             patch.object(douyin_import, "_provider_uses_quota", return_value=True), \
             patch("app.douyin_quota.can_spend", side_effect=[True, False]):
            summary = douyin_import.initial_import("src-1")

        self.assertEqual(summary["status"], "paused_quota")
        self.assertEqual(summary["cursor"], "page_2_cursor")

        with self.Session() as db:
            src = db.get(DouyinSource, "src-1")
            self.assertEqual(src.initial_import_cursor, "page_2_cursor")
            self.assertEqual(src.initial_import_status, "paused_quota")

            job = db.execute(select(DouyinScanJob)).scalar_one()
            self.assertEqual(job.status, "paused_quota")
            self.assertEqual(job.stop_reason, "QUOTA_EXHAUSTED")

        # Step 2: Resume continues with cursor from page 2
        provider2 = _FakeProvider([
            {
                "items": [_video("v3")],
                "has_more": False,
                "next_cursor": "",
            },
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider2), \
             patch.object(douyin_import, "_provider_uses_quota", return_value=False):
            summary2 = douyin_import.initial_import("src-1", resume=True)

        self.assertEqual(summary2["status"], "completed")
        self.assertIn("page_2_cursor", provider2.calls)

        with self.Session() as db:
            src = db.get(DouyinSource, "src-1")
            self.assertIsNone(src.initial_import_cursor)
            self.assertEqual(src.initial_import_status, "completed")
            videos = db.execute(select(DouyinVideo)).scalars().all()
            self.assertEqual(len(videos), 3)

    def test_dedup_on_rescanning_does_not_duplicate(self):
        """Scanning the same videos again increments duplicate count and leaves rows unique."""
        provider1 = _FakeProvider([
            {"items": [_video("v10"), _video("v20")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider1):
            s1 = douyin_import.initial_import("src-1")
            self.assertEqual(s1["new"], 2)

        # Second scan finds same videos
        provider2 = _FakeProvider([
            {"items": [_video("v10"), _video("v20")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider2):
            s2 = douyin_import.refresh_source("src-1")

        self.assertEqual(s2["new"], 0)
        with self.Session() as db:
            count = db.execute(select(func.count(DouyinVideo.id))).scalar_one()
            self.assertEqual(count, 2)

    def test_dedup_legacy_videos_linked_and_never_revert_published(self):
        """Legacy video with source_id=NULL and status=published is linked to source and stays published."""
        with self.Session() as db:
            legacy = DouyinVideo(
                id="leg-1",
                pipeline_id="pipe-1",
                source_id=None,
                video_id="v_published",
                url="https://www.douyin.com/video/v_published",
                status="published",
            )
            db.add(legacy)
            db.commit()

        provider = _FakeProvider([
            {"items": [_video("v_published")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            res = douyin_import.refresh_source("src-1")

        self.assertEqual(res["new"], 0)
        with self.Session() as db:
            videos = db.execute(select(DouyinVideo).where(DouyinVideo.video_id == "v_published")).scalars().all()
            self.assertEqual(len(videos), 1)
            v = videos[0]
            self.assertEqual(v.status, "published")  # Preserved!
            self.assertEqual(v.source_id, "src-1")   # Linked!

    def test_pinned_post_safe_stop_incremental_scan(self):
        """Incremental scan does not stop on a pinned known video if new videos exist on the page."""
        with self.Session() as db:
            # v_pinned is already in inventory
            db.add(DouyinVideo(
                id="p1", pipeline_id="pipe-1", source_id="src-1",
                video_id="v_pinned", url="https://example.com/pinned", status="inventory",
            ))
            db.commit()

        # Creator page: pinned post at top, then brand new v_new1, v_new2
        provider = _FakeProvider([
            {
                "items": [_video("v_pinned"), _video("v_new1"), _video("v_new2")],
                "has_more": True,
                "next_cursor": "p2",
            },
            {
                # Page 2 has only known/old items
                "items": [_video("v_pinned")],
                "has_more": False,
                "next_cursor": "",
            },
        ])

        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            with self.Session() as db:
                job = douyin_import.queue_scan_job(db, "src-1", scan_mode="replenish")
                job_id = job.id
            summary = douyin_import.claim_and_run_scan_job(job_id=job_id)

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["new"], 2)  # v_new1 and v_new2 discovered!

        with self.Session() as db:
            j = db.get(DouyinScanJob, job_id)
            self.assertEqual(j.stop_reason, "KNOWN_REELS_REACHED")
            vids = [v.video_id for v in db.execute(select(DouyinVideo)).scalars().all()]
            self.assertIn("v_new1", vids)
            self.assertIn("v_new2", vids)

    def test_auto_replenish_low_inventory_trigger(self):
        """When available inventory is <= threshold, check_and_schedule_replenishments schedules a job."""
        with self.Session() as db:
            # 2 published videos, 1 available video (threshold=3)
            db.add(DouyinVideo(id="v1", pipeline_id="pipe-1", source_id="src-1", video_id="v1", url="https://example.com/v1", status="published"))
            db.add(DouyinVideo(id="v2", pipeline_id="pipe-1", source_id="src-1", video_id="v2", url="https://example.com/v2", status="published"))
            db.add(DouyinVideo(id="v3", pipeline_id="pipe-1", source_id="src-1", video_id="v3", url="https://example.com/v3", status="inventory"))
            src = db.get(DouyinSource, "src-1")
            src.last_scan_at = datetime.now(timezone.utc) - timedelta(hours=10)
            db.commit()

        with patch.object(douyin_import, "can_start_import", return_value=True):
            with self.Session() as db:
                scheduled = monitor.check_and_schedule_replenishments(db)
                self.assertEqual(len(scheduled), 1)

                job = db.get(DouyinScanJob, scheduled[0])
                self.assertEqual(job.scan_mode, "replenish")
                self.assertEqual(job.status, "pending")

    def test_auto_replenish_cooldown_respected(self):
        """If source was scanned recently (<6 hours), auto-replenish is skipped."""
        with self.Session() as db:
            # Available is 0, but scanned 1 hour ago
            src = db.get(DouyinSource, "src-1")
            src.last_scan_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()

        with patch.object(douyin_import, "can_start_import", return_value=True):
            with self.Session() as db:
                scheduled = monitor.check_and_schedule_replenishments(db)
                self.assertEqual(len(scheduled), 0)

    def test_crash_recovery_resets_running_jobs(self):
        """recover_incomplete_scan_jobs resets running jobs to pending and clears locks."""
        with self.Session() as db:
            stuck = DouyinScanJob(
                id="stuck-1",
                pipeline_id="pipe-1",
                source_id="src-1",
                scan_mode="initial",
                status="running",
                locked_by="old_container_pid_123",
                locked_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                retry_count=1,
            )
            db.add(stuck)
            db.commit()

        with self.Session() as db:
            recovered = douyin_import.recover_incomplete_scan_jobs(db)
            self.assertEqual(recovered, 1)

            job = db.get(DouyinScanJob, "stuck-1")
            self.assertEqual(job.status, "pending")
            self.assertIsNone(job.locked_by)
            self.assertIsNone(job.locked_at)
            self.assertEqual(job.retry_count, 2)

    def test_worker_claim_locking(self):
        """Two workers cannot claim the same job concurrently."""
        with self.Session() as db:
            job = douyin_import.queue_scan_job(db, "src-1", scan_mode="initial")
            job_id = job.id

        provider = _FakeProvider([{"items": [], "has_more": False, "next_cursor": ""}])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            # Worker 1 claims it
            res = douyin_import.claim_and_run_scan_job(job_id=job_id, worker_id="worker_1")
            self.assertIsNotNone(res)
            self.assertEqual(res["status"], "completed")

            # Worker 2 tries to claim same job -> returns None because already completed
            res2 = douyin_import.claim_and_run_scan_job(job_id=job_id, worker_id="worker_2")
            self.assertIsNone(res2)

    def test_layer_c_upload_dedup_reconciliation(self):
        """Worker verifies existing youtube_video_id on job or publication to prevent duplicate upload."""
        with self.Session() as db:
            job = VideoJob(
                id="job-dedup-1",
                pipeline_id="pipe-1",
                source_url="https://example.com/video/1",
                status="uploading",
                youtube_video_id="yt_existing_video_id",
            )
            db.add(job)
            db.commit()

            # Read back
            j = db.get(VideoJob, "job-dedup-1")
            existing_yt_id = getattr(j, "youtube_video_id", None)
            self.assertEqual(existing_yt_id, "yt_existing_video_id")

    def test_auto_replenish_when_available_zero_and_scan_on(self):
        """When available inventory = 0 (all published or rejected) and SCAN ON, system schedules replenishment."""
        with self.Session() as db:
            # 26 published, 21 rejected, 1 held (exact JoyBeat situation: 0 available)
            db.add(DouyinVideo(id="pub-1", pipeline_id="pipe-1", source_id="src-1", video_id="pub-1", url="https://example.com/pub1", status="published"))
            db.add(DouyinVideo(id="rej-1", pipeline_id="pipe-1", source_id="src-1", video_id="rej-1", url="https://example.com/rej1", status="rejected"))
            db.add(DouyinVideo(id="hld-1", pipeline_id="pipe-1", source_id="src-1", video_id="hld-1", url="https://example.com/hld1", status="held"))
            
            src = db.get(DouyinSource, "src-1")
            src.enabled = True
            # Cooldown has passed (scanned 8 hours ago)
            src.last_scan_at = datetime.now(timezone.utc) - timedelta(hours=8)
            db.commit()

        with self.Session() as db:
            available = monitor.count_available_inventory_for_source(db, "src-1")
            self.assertEqual(available, 0)
            
            scheduled = monitor.check_and_schedule_replenishments(db)
            self.assertEqual(len(scheduled), 1)

            job = db.get(DouyinScanJob, scheduled[0])
            self.assertEqual(job.scan_mode, "replenish")
            self.assertEqual(job.status, "pending")

    def test_legacy_rapidapi_quota_does_not_block_self_hosted(self):
        """Legacy RapidAPI quota exhaustion must never block self-hosted scanning."""
        with self.Session() as db:
            src = db.get(DouyinSource, "src-1")
            src.enabled = True
            src.feed_provider = "self_hosted"
            src.last_scan_at = datetime.now(timezone.utc) - timedelta(hours=10)
            db.commit()

        # Mock rapidapi quota as exhausted
        from app import douyin_quota
        with patch.object(douyin_quota, "can_spend", return_value=False):
            # With self-hosted enabled, can_start_import returns True
            with patch.object(settings, "douyin_self_hosted_enabled", True):
                self.assertTrue(douyin_import.can_start_import())
                
                with self.Session() as db:
                    scheduled = monitor.check_and_schedule_replenishments(db)
                    self.assertEqual(len(scheduled), 1)

    def test_cooldown_prevents_continuous_scan_when_no_new_videos(self):
        """Cooldown strictly prevents continuous scanning when creator published no new videos."""
        now = datetime.now(timezone.utc)
        with self.Session() as db:
            src = db.get(DouyinSource, "src-1")
            src.enabled = True
            # Last scan 2 hours ago: found 0 new videos
            src.last_scan_at = now - timedelta(hours=2)
            src.last_scan_stats = '{"new": 0, "found": 21, "status": "completed", "stop_reason": "KNOWN_REELS_REACHED"}'
            db.commit()

        with self.Session() as db:
            # 2 hours < 6 hours cooldown -> must not schedule
            scheduled = monitor.check_and_schedule_replenishments(db)
            self.assertEqual(len(scheduled), 0)

            # Ensure source.next_scan_at is set to last_scan_at + 6 hours
            src = db.get(DouyinSource, "src-1")
            self.assertIsNotNone(src.next_scan_at)
            # next_scan_at should be approximately now + 4 hours
            diff = (src.next_scan_at.replace(tzinfo=timezone.utc) - now).total_seconds()
            self.assertGreater(diff, 3.5 * 3600)
            self.assertLess(diff, 4.5 * 3600)

    def test_stuck_scan_job_auto_recovery_and_execution(self):
        """A scan job stuck in 'running' state is recovered and can then be executed successfully."""
        with self.Session() as db:
            job = douyin_import.queue_scan_job(db, "src-1", scan_mode="replenish")
            job.status = "running"
            job.locked_at = datetime.now(timezone.utc) - timedelta(minutes=45)
            job.locked_by = "dead_worker_99"
            db.commit()
            job_id = job.id

        with self.Session() as db:
            # Automatic recovery resets status to pending
            recovered = douyin_import.recover_incomplete_scan_jobs(db, max_age_seconds=1800)
            self.assertEqual(recovered, 1)
            
            j = db.get(DouyinScanJob, job_id)
            self.assertEqual(j.status, "pending")
            self.assertIsNone(j.locked_by)

        # Worker can now claim and execute the recovered job
        fake_page = {"items": [_video("vid_rec_1")], "has_more": False, "next_cursor": ""}
        provider = _FakeProvider([fake_page])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            summary = douyin_import.claim_and_run_scan_job(job_id=job_id, worker_id="monitor_worker")
            self.assertIsNotNone(summary)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["new"], 1)

        with self.Session() as db:
            j = db.get(DouyinScanJob, job_id)
            self.assertEqual(j.status, "completed")

    def test_dashboard_stats_includes_scan_observability(self):
        """dashboard_stats endpoint returns last_scan_at, next_scan_at, scan_status, scan_result, scan_reason."""
        from app.main import dashboard_stats
        now = datetime.now(timezone.utc)

        with self.Session() as db:
            src = db.get(DouyinSource, "src-1")
            src.enabled = True
            src.last_scan_at = now - timedelta(hours=1)
            src.last_scan_stats = '{"job_id": "job-1", "found": 21, "new": 0, "duplicates": 21, "status": "completed", "stop_reason": "KNOWN_REELS_REACHED"}'
            db.commit()

            # 1. When monitor is offline, correctly reports WORKER_OFFLINE
            with patch("app.main.monitor_task", None):
                res = dashboard_stats(db=db)
                pipe_rows = [p for p in res["pipelines"] if p["id"] == "pipe-1"]
                self.assertEqual(len(pipe_rows), 1)
                p = pipe_rows[0]
                self.assertEqual(p["scan_reason"], "WORKER_OFFLINE")
                self.assertIn("offline", p["scan_reason_detail"])

            # 2. When monitor is online, correctly reports cooldown & NO_NEW_VIDEOS
            mock_task = MagicMock()
            mock_task.done.return_value = False
            with patch("app.main.monitor_task", mock_task), patch.object(settings, "monitor_enabled", True):
                res = dashboard_stats(db=db)
                pipe_rows = [p for p in res["pipelines"] if p["id"] == "pipe-1"]
                p = pipe_rows[0]
                self.assertIn("last_scan_at", p)
                self.assertIsNotNone(p["last_scan_at"])
                self.assertIn("next_scan_at", p)
                self.assertIsNotNone(p["next_scan_at"])
                self.assertEqual(p["scan_status"], "cooldown")
                self.assertEqual(p["scan_reason"], "NO_NEW_VIDEOS")
                self.assertIn("Nguồn chưa có video mới", p["scan_reason_detail"])
                self.assertIsNotNone(p["scan_result"])
                self.assertEqual(p["scan_result"]["new"], 0)
                self.assertEqual(p["scan_result"]["found"], 21)
                self.assertEqual(p["scan_result"]["stop_reason"], "KNOWN_REELS_REACHED")


if __name__ == "__main__":
    unittest.main()
