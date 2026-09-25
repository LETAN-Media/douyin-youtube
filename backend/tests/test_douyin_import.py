import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import douyin_import, douyin_quota
from app.config import settings
from app.db import Base
from app.models import AppSetting, DouyinSource, DouyinVideo, Pipeline


def _session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def _video(video_id: str, *, created_ts: int = 1_700_000_000):
    return {
        "video_id": video_id,
        "title": f"video {video_id}",
        "description": "",
        "url": f"https://www.douyin.com/video/{video_id}",
        "douyin_created_at": __import__("datetime").datetime.fromtimestamp(
            created_ts, tz=__import__("datetime").timezone.utc
        ),
    }


class _FakeProvider:
    """One page per fetch_page call; records the cursors it was given."""

    name = "rapidapi_justone"

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls: list[str | None] = []

    def fetch_page(self, sec_uid_or_url, cursor=None):
        self.calls.append(cursor)
        if len(self.calls) > len(self.pages):
            return {"items": [], "has_more": False, "next_cursor": ""}
        return self.pages[len(self.calls) - 1]


class _ImportTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = _session_factory(self.engine)

        self._patchers = [
            patch.object(douyin_import, "SessionLocal", self.Session),
            patch.object(douyin_quota, "SessionLocal", self.Session),
        ]
        for p in self._patchers:
            p.start()
        douyin_quota.reset_for_tests()

        # No real sleeping between pages during tests.
        self._delay = patch.object(
            settings, "douyin_initial_import_page_delay_seconds", 0
        )
        self._delay.start()

        with self.Session() as db:
            pipeline = Pipeline(
                id=str(uuid4()),
                name="Test",
                slug=f"test-{uuid4().hex[:8]}",
                enabled=True,
                daily_upload_limit=6,
            )
            source = DouyinSource(
                id=str(uuid4()),
                pipeline_id=pipeline.id,
                name="Creator",
                profile_url="https://www.douyin.com/user/SEC123",
                douyin_sec_uid="SEC123",
                enabled=True,
            )
            db.add(pipeline)
            db.add(source)
            db.commit()
            self.pipeline_id = pipeline.id
            self.source_id = source.id

    def tearDown(self):
        self._delay.stop()
        for p in self._patchers:
            p.stop()
        self.engine.dispose()

    def _status(self):
        with self.Session() as db:
            return db.get(DouyinSource, self.source_id)

    def _videos(self):
        with self.Session() as db:
            return [
                v.video_id
                for v in db.query(DouyinVideo)
                .filter(DouyinVideo.source_id == self.source_id)
                .all()
            ]


class TestInitialImport(_ImportTestBase):
    def test_paginates_until_has_more_false(self):
        provider = _FakeProvider([
            {"items": [_video("1"), _video("2")], "has_more": True, "next_cursor": "100"},
            {"items": [_video("3")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            result = douyin_import.initial_import(self.source_id)

        self.assertEqual(result["status"], douyin_import.STATUS_COMPLETED)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["new"], 3)
        self.assertEqual(sorted(self._videos()), ["1", "2", "3"])

        source = self._status()
        self.assertEqual(source.initial_import_status, "completed")
        self.assertIsNone(source.initial_import_cursor)
        self.assertEqual(source.initial_import_pages, 2)
        self.assertEqual(source.inventory_count, 3)
        self.assertIsNotNone(source.initial_import_completed_at)
        self.assertEqual(source.provider_status, "ok")
        # Fresh import starts from page 1, second call uses the returned cursor.
        self.assertEqual(provider.calls, [None, "100"])

    def test_dedupes_across_pages_and_never_downloads(self):
        provider = _FakeProvider([
            {"items": [_video("1")], "has_more": True, "next_cursor": "100"},
            {"items": [_video("1"), _video("2")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            douyin_import.initial_import(self.source_id)
        self.assertEqual(sorted(self._videos()), ["1", "2"])

    def test_imported_backlog_stays_available(self):
        # Videos older than the pipeline backlog threshold become backlog,
        # not baseline: a manual import must feed the publish queue.
        provider = _FakeProvider([
            {"items": [_video("old", created_ts=1_500_000_000)], "has_more": False,
             "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            douyin_import.initial_import(self.source_id)

        with self.Session() as db:
            video = (
                db.query(DouyinVideo)
                .filter(DouyinVideo.video_id == "old")
                .one()
            )
            self.assertTrue(video.is_backlog)
            self.assertTrue(video.is_backfill)
            self.assertIn(video.status, ("backlog", "new"))


class TestResumeAndQuota(_ImportTestBase):
    def test_quota_stop_keeps_cursor_and_resume_continues(self):
        provider = _FakeProvider([
            {"items": [_video("1")], "has_more": True, "next_cursor": "100"},
            {"items": [_video("2")], "has_more": True, "next_cursor": "200"},
            {"items": [_video("3")], "has_more": False, "next_cursor": ""},
        ])

        # Allow exactly one page, then the quota floor refuses the next one.
        calls = {"n": 0}

        def fake_can_spend(requests=1):
            calls["n"] += 1
            return calls["n"] <= 1

        with patch.object(douyin_import, "get_primary_provider", return_value=provider), \
             patch.object(douyin_quota, "can_spend", side_effect=fake_can_spend):
            first = douyin_import.initial_import(self.source_id)

        self.assertEqual(first["status"], douyin_import.STATUS_PAUSED_QUOTA)
        self.assertEqual(first["pages"], 1)
        source = self._status()
        self.assertEqual(source.initial_import_status, "paused_quota")
        self.assertEqual(source.initial_import_cursor, "100")
        self.assertEqual(source.provider_status, "quota_exhausted")
        self.assertEqual(provider.calls, [None])

        # Resume: quota available again, continues from the stored cursor.
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            second = douyin_import.initial_import(self.source_id, resume=True)

        self.assertEqual(second["status"], douyin_import.STATUS_COMPLETED)
        self.assertEqual(sorted(self._videos()), ["1", "2", "3"])
        self.assertEqual(provider.calls, [None, "100", "200"])
        self.assertIsNone(self._status().initial_import_cursor)

    def test_no_request_spent_when_quota_already_exhausted(self):
        provider = _FakeProvider([
            {"items": [_video("1")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider), \
             patch.object(douyin_quota, "can_spend", return_value=False):
            result = douyin_import.initial_import(self.source_id)

        self.assertEqual(result["status"], douyin_import.STATUS_PAUSED_QUOTA)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self._videos(), [])


class TestManualRefresh(_ImportTestBase):
    def _seed(self, *video_ids):
        provider = _FakeProvider([
            {"items": [_video(v) for v in video_ids], "has_more": False,
             "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            douyin_import.initial_import(self.source_id)

    def test_stops_at_first_known_video(self):
        self._seed("100", "99", "98")

        # Newest-first page: one brand new video, then a video already known.
        provider = _FakeProvider([
            {"items": [_video("101"), _video("100"), _video("99")],
             "has_more": True, "next_cursor": "50"},
            {"items": [_video("97")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            result = douyin_import.refresh_source(self.source_id)

        self.assertEqual(result["status"], douyin_import.STATUS_COMPLETED)
        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["new"], 1)
        # Only page 1 was spent; the second page was never requested.
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("101", self._videos())
        status = self._status().initial_import_status
        self.assertEqual(status, "completed")
        self.assertIsNotNone(self._status().last_refresh_at)

    def test_refresh_does_not_clobber_resume_cursor(self):
        with self.Session() as db:
            source = db.get(DouyinSource, self.source_id)
            source.initial_import_status = "paused_quota"
            source.initial_import_cursor = "777"
            db.commit()

        provider = _FakeProvider([
            {"items": [_video("500")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider):
            douyin_import.refresh_source(self.source_id)

        self.assertEqual(self._status().initial_import_cursor, "777")

    def test_refresh_respects_quota_floor(self):
        self._seed("100")
        provider = _FakeProvider([
            {"items": [_video("101")], "has_more": False, "next_cursor": ""},
        ])
        with patch.object(douyin_import, "get_primary_provider", return_value=provider), \
             patch.object(douyin_quota, "can_spend", return_value=False):
            result = douyin_import.refresh_source(self.source_id)

        self.assertEqual(result["status"], douyin_import.STATUS_PAUSED_QUOTA)
        self.assertEqual(provider.calls, [])


class TestQuotaRecord(_ImportTestBase):
    def test_headers_authoritative_and_floor(self):
        recorded = douyin_quota.record_headers({
            "x-ratelimit-requests-limit": "20",
            "x-ratelimit-requests-remaining": "2",
        })
        self.assertIsNotNone(recorded)
        self.assertEqual(recorded["remaining"], 2)
        self.assertEqual(recorded["used"], 18)
        # safety_margin default is 1: remaining 2 allows one more, not two.
        self.assertTrue(douyin_quota.can_spend(1))
        self.assertFalse(douyin_quota.can_spend(2))

    def test_mark_exhausted_blocks_spend(self):
        douyin_quota.mark_exhausted("HTTP 429")
        snap = douyin_quota.snapshot()
        self.assertEqual(snap["remaining"], 0)
        self.assertTrue(snap["exhausted"])
        self.assertEqual(snap["status"], douyin_quota.STATUS_EXHAUSTED)
        self.assertFalse(douyin_quota.can_spend(1))
        with self.assertRaises(douyin_quota.QuotaExhausted):
            douyin_quota.ensure_can_spend(1)

    def test_quota_snapshot_hides_secrets(self):
        snap = douyin_import.quota_status()
        for key in snap:
            self.assertNotIn("key", key.lower())


class TestJustOneClientQuota(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = _session_factory(self.engine)
        self._qd = patch.object(douyin_quota, "SessionLocal", self.Session)
        self._qd.start()
        douyin_quota.reset_for_tests()

    def tearDown(self):
        self._qd.stop()
        self.engine.dispose()

    def _client_module(self):
        from app.integrations.rapidapi import justone

        return justone

    def test_429_is_terminal_and_marks_exhausted(self):
        justone = self._client_module()
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "quota"
        resp.headers = {"x-ratelimit-requests-limit": "20",
                        "x-ratelimit-requests-remaining": "0"}
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = resp

        with patch.object(justone.httpx, "Client", return_value=client), \
             patch.object(settings, "rapidapi_key", "test-key"), \
             patch.object(settings, "douyin_rapidapi_host", "example.p.rapidapi.com"):
            with self.assertRaises(justone.JustOneQuotaError):
                justone.fetch_user_videos("SEC123")

        # Exactly one billed attempt: a 429 must not be retried.
        self.assertEqual(client.get.call_count, 1)
        self.assertTrue(douyin_quota.snapshot()["exhausted"])

    def test_success_normalizes_aweme_list(self):
        justone = self._client_module()
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"x-ratelimit-requests-limit": "20",
                        "x-ratelimit-requests-remaining": "19"}
        resp.json.return_value = {
            "code": 0,
            "data": {
                "aweme_list": [
                    {
                        "aweme_id": "7467752268393530654",
                        "desc": "Test video",
                        "create_time": 1700000000,
                        "share_url": "https://www.douyin.com/video/7467752268393530654",
                        "video": {"cover": {"url_list": ["https://cover/1.jpg"]}},
                    }
                ],
                "has_more": 0,
                "max_cursor": 0,
            },
        }
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = resp

        with patch.object(justone.httpx, "Client", return_value=client), \
             patch.object(settings, "rapidapi_key", "test-key"), \
             patch.object(settings, "douyin_rapidapi_host", "example.p.rapidapi.com"):
            result = justone.fetch_user_videos("SEC123")

        self.assertEqual(result["has_more"], False)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["aweme_id"], "7467752268393530654")
        self.assertEqual(result["items"][0]["cover_url"], "https://cover/1.jpg")
        self.assertEqual(douyin_quota.snapshot()["remaining"], 19)


class TestJustOneNormalization(unittest.TestCase):
    def test_normalize_item(self):
        from app.douyin_inventory_providers import JustOneRapidApiProvider

        item = {
            "aweme_id": "123",
            "caption": "hello",
            "create_time": 1700000000,
            "share_url": "",
            "cover_url": "https://c/1.jpg",
        }
        normalized = JustOneRapidApiProvider._normalize_justone_item(item)
        self.assertEqual(normalized["video_id"], "123")
        self.assertEqual(normalized["title"], "hello")
        self.assertTrue(normalized["url"].endswith("/video/123"))
        self.assertIsNotNone(normalized["douyin_created_at"])


if __name__ == "__main__":
    unittest.main()
