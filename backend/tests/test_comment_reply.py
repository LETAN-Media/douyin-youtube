"""AI YouTube comment reply tests, with prompt isolation as the centrepiece."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import ai_comment_reply as acr
from app import ai_metadata as aim
from app import comment_poller as cp
from app import youtube_comments as yc
from app.db import Base
from app.models import Destination, Pipeline, YouTubeComment

METADATA_PROMPT = (
    "You write attractive English YouTube titles about handsome boys."
)
COMMENT_PROMPT = (
    "You are the community manager for Handsome Boys Universe. "
    "Reply naturally, friendly, short and playful."
)


class _FakeResponse:
    def __init__(self, content):
        self.text = json.dumps(
            {"choices": [{"message": {"content": json.dumps(content)}}]}
        )
        self.status_code = 200

    def raise_for_status(self):
        return None


def _reply_payload(**overrides):
    payload = {
        "classification": "POSITIVE",
        "should_reply": True,
        "confidence": 0.93,
        "reply": "Glad you enjoyed it!",
        "reason": "kind comment",
    }
    payload.update(overrides)
    return payload


class _CommentTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

        self._patchers = [
            patch.object(cp, "SessionLocal", self.Session),
        ]
        for p in self._patchers:
            p.start()

        with self.Session() as db:
            pipeline = Pipeline(
                id=str(uuid4()),
                name="Handsome Boys Universe",
                slug=f"hbu-{uuid4().hex[:8]}",
            )
            db.add(pipeline)
            db.commit()
            self.pipeline_id = pipeline.id

            self.destination = Destination(
                id=str(uuid4()),
                pipeline_id=pipeline.id,
                platform="youtube",
                name="Handsome Boys Universe",
                external_account_id="UC_channel_1",
                connected=True,
                enabled=True,
                # Metadata prompt (must stay untouched by the comment flow).
                prompt_override=METADATA_PROMPT,
                metadata_profile="handsome boys entertainment",
                metadata_language="en",
                # Comment reply prompt (fully independent).
                comment_reply_enabled=True,
                comment_reply_mode="review",
                comment_reply_system_prompt=COMMENT_PROMPT,
                comment_reply_language="auto",
                comment_reply_style="friendly",
                comment_reply_daily_limit=20,
                comment_reply_min_interval_seconds=180,
                credentials=json.dumps(
                    {
                        "refresh_token": "fake",
                        "scopes": [
                            "https://www.googleapis.com/auth/youtube.upload",
                            "https://www.googleapis.com/auth/youtube.force-ssl",
                        ],
                    }
                ),
            )
            db.add(self.destination)
            db.commit()
            self.destination_id = self.destination.id

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def _destination(self, db):
        return db.get(Destination, self.destination_id)


# ---------------------------------------------------------------------------
# PROMPT ISOLATION — the hard requirement
# ---------------------------------------------------------------------------


class PromptIsolationTests(_CommentTestBase):
    def test_comment_reply_uses_only_the_comment_prompt(self):
        captured = {}

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured["messages"] = json["messages"]
            return _FakeResponse(_reply_payload())

        with self.Session() as db:
            destination = self._destination(db)
            with patch.object(acr.httpx, "post", _fake_post):
                result = acr.generate_comment_reply(
                    "love this channel!",
                    destination=destination,
                    video_title="Best moments",
                )

        self.assertIsNotNone(result)
        system = captured["messages"][0]["content"]
        self.assertEqual(system, COMMENT_PROMPT)
        self.assertNotIn(METADATA_PROMPT, system)
        self.assertNotEqual(system, METADATA_PROMPT)

        user = captured["messages"][1]["content"]
        self.assertIn("love this channel!", user)
        # The metadata prompt must never leak into the comment flow.
        self.assertNotIn(METADATA_PROMPT, user)

    def test_channel_without_comment_prompt_falls_back_to_neutral_default(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.comment_reply_system_prompt = None
            db.commit()

            system = acr.build_comment_reply_system_prompt(destination)

        self.assertEqual(system, acr.DEFAULT_COMMENT_REPLY_PROMPT)
        # Crucially NOT the metadata prompt.
        self.assertNotEqual(system, METADATA_PROMPT)
        self.assertNotIn("attractive English YouTube titles", system)

    def test_comment_prompt_beats_metadata_prompt_when_both_set(self):
        with self.Session() as db:
            destination = self._destination(db)
            self.assertEqual(
                acr.build_comment_reply_system_prompt(destination), COMMENT_PROMPT
            )
            self.assertEqual(destination.prompt_override, METADATA_PROMPT)

    @staticmethod
    def _executable_source(module_file: str) -> str:
        """Module source with docstrings removed, so prose cannot fool the
        isolation check — only real attribute access counts."""
        import ast

        tree = ast.parse(Path(module_file).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    node.body = body[1:]
        return ast.unparse(tree)

    def test_comment_module_never_reads_metadata_prompt_fields(self):
        code = self._executable_source(acr.__file__)
        for forbidden in (
            "prompt_override",
            "metadata_profile",
            "metadata_language",
        ):
            self.assertNotIn(
                forbidden,
                code,
                f"comment reply module must not reference {forbidden}",
            )

    def test_metadata_module_never_reads_comment_prompt_fields(self):
        code = self._executable_source(aim.__file__)
        self.assertNotIn("comment_reply_system_prompt", code)

    def test_metadata_generation_still_uses_the_metadata_prompt(self):
        """Regression: adding comment replies must not change metadata."""
        captured = {}

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured["messages"] = json["messages"]
            return _FakeResponse(
                {
                    "title": "Generated Title",
                    "description": "Clean description",
                    "hashtags": [
                        "#a1",
                        "#a2",
                        "#a3",
                        "#a4",
                        "#a5",
                    ],
                }
            )

        with self.Session() as db:
            destination = self._destination(db)
            with patch.object(aim.httpx, "post", _fake_post):
                result = aim.generate_metadata_structured(
                    "douyin context", destination=destination
                )

        self.assertIsNotNone(result)
        system = captured["messages"][0]["content"]
        self.assertEqual(system, METADATA_PROMPT)
        self.assertNotIn(COMMENT_PROMPT, system)
        self.assertEqual(result["title"], "Generated Title")
        self.assertEqual(len(result["hashtags"]), 5)

    def test_two_destinations_keep_independent_prompts(self):
        other_prompt = "You manage the JoyBeat Dance community. Be upbeat."
        with self.Session() as db:
            other = Destination(
                id=str(uuid4()),
                pipeline_id=self.pipeline_id,
                platform="youtube",
                name="JoyBeat Dance",
                connected=True,
                enabled=True,
                comment_reply_system_prompt=other_prompt,
            )
            db.add(other)
            db.commit()

            first = acr.build_comment_reply_system_prompt(self._destination(db))
            second = acr.build_comment_reply_system_prompt(db.get(Destination, other.id))

        self.assertEqual(first, COMMENT_PROMPT)
        self.assertEqual(second, other_prompt)
        self.assertNotEqual(first, second)


# ---------------------------------------------------------------------------
# Classification + safety
# ---------------------------------------------------------------------------


class ClassificationTests(_CommentTestBase):
    def _generate(self, content):
        with self.Session() as db:
            destination = self._destination(db)
            with patch.object(
                acr.httpx, "post", lambda *a, **k: _FakeResponse(content)
            ):
                return acr.generate_comment_reply(
                    "some comment", destination=destination
                )

    def test_positive_comment_can_reply(self):
        result = self._generate(_reply_payload())
        self.assertTrue(result["should_reply"])
        self.assertEqual(result["classification"], "POSITIVE")
        self.assertEqual(result["reply"], "Glad you enjoyed it!")

    def test_spam_is_hard_blocked_even_if_model_asks_to_reply(self):
        result = self._generate(
            _reply_payload(classification="SPAM", should_reply=True)
        )
        self.assertFalse(result["should_reply"])

    def test_abuse_is_hard_blocked(self):
        result = self._generate(_reply_payload(classification="ABUSE"))
        self.assertFalse(result["should_reply"])

    def test_sensitive_is_held(self):
        result = self._generate(_reply_payload(classification="SENSITIVE"))
        self.assertFalse(result["should_reply"])

    def test_unknown_classification_becomes_skip(self):
        result = self._generate(_reply_payload(classification="WHATEVER"))
        self.assertEqual(result["classification"], "SKIP")
        self.assertFalse(result["should_reply"])

    def test_invalid_confidence_is_clamped(self):
        result = self._generate(_reply_payload(confidence="not-a-number"))
        self.assertEqual(result["confidence"], 0.0)

    def test_eligibility_mapping_follows_channel_config(self):
        with self.Session() as db:
            destination = self._destination(db)

            self.assertTrue(cp.eligibility_reason("POSITIVE", destination)[0])
            self.assertTrue(cp.eligibility_reason("QUESTION", destination)[0])
            self.assertFalse(cp.eligibility_reason("NEUTRAL", destination)[0])
            self.assertFalse(cp.eligibility_reason("NEGATIVE", destination)[0])
            self.assertFalse(cp.eligibility_reason("SPAM", destination)[0])

            destination.comment_reply_to_neutral = True
            db.commit()
            self.assertTrue(cp.eligibility_reason("NEUTRAL", destination)[0])

    def test_emoji_only_detection(self):
        self.assertTrue(cp.is_emoji_only("🔥🔥"))
        self.assertFalse(cp.is_emoji_only("nice 🔥"))


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


class LanguageTests(unittest.TestCase):
    def test_detects_vietnamese_chinese_and_english(self):
        self.assertEqual(acr.detect_language("Video này hay quá"), "vi")
        self.assertEqual(acr.detect_language("很好"), "zh")
        self.assertEqual(acr.detect_language("nice video"), "en")

    def test_reply_defaults_to_commenter_language(self):
        self.assertEqual(
            acr.resolve_reply_language("hay quá", "auto"), "vi"
        )

    def test_channel_language_overrides_comment_language(self):
        self.assertEqual(
            acr.resolve_reply_language("hay quá", "en"), "en"
        )


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------


class RateLimitTests(_CommentTestBase):
    def _replied(self, db, destination, minutes_ago=0):
        comment = YouTubeComment(
            destination_id=destination.id,
            video_id="vid1",
            youtube_comment_id=f"c-{uuid4().hex[:8]}",
            text_original="hi",
            comment_text="hi",
            status="replied",
            reply_status="replied",
            replied_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        )
        db.add(comment)
        db.commit()
        return comment

    def test_daily_limit_stops_replies(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.comment_reply_daily_limit = 2
            destination.comment_reply_min_interval_seconds = 0
            db.commit()

            self._replied(db, destination)
            self._replied(db, destination)

            allowed, reason = cp.can_reply_now(db, destination)
            self.assertFalse(allowed)
            self.assertIn("daily reply limit", reason)

    def test_min_interval_stops_replies(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.comment_reply_min_interval_seconds = 180
            db.commit()

            self._replied(db, destination, minutes_ago=1)

            allowed, reason = cp.can_reply_now(db, destination)
            self.assertFalse(allowed)
            self.assertIn("min interval", reason)

    def test_replies_allowed_once_interval_elapsed(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.comment_reply_min_interval_seconds = 180
            db.commit()

            self._replied(db, destination, minutes_ago=10)

            allowed, reason = cp.can_reply_now(db, destination)
            self.assertTrue(allowed, reason)

    def test_zero_daily_limit_blocks_everything(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.comment_reply_daily_limit = 0
            db.commit()
            allowed, _ = cp.can_reply_now(db, destination)
            self.assertFalse(allowed)


# ---------------------------------------------------------------------------
# Dedupe + reply posting
# ---------------------------------------------------------------------------


class DedupeTests(_CommentTestBase):
    def test_upsert_is_idempotent_on_youtube_comment_id(self):
        payload = {
            "youtube_comment_id": "yt-1",
            "parent_comment_id": None,
            "author_channel_id": "UC_a",
            "author_name": "Ann",
            "text_original": "hello",
            "published_at": datetime.now(timezone.utc),
            "like_count": 1,
        }
        with self.Session() as db:
            destination = self._destination(db)
            first, is_new_first = cp._upsert_comment(
                db, destination, "vid1", "Title", payload
            )
            db.commit()
            second, is_new_second = cp._upsert_comment(
                db, destination, "vid1", "Title", payload
            )
            db.commit()

            count = db.query(YouTubeComment).count()

        self.assertTrue(is_new_first)
        self.assertFalse(is_new_second)
        self.assertEqual(count, 1)
        self.assertEqual(first.id, second.id)

    def test_post_reply_skips_when_already_replied(self):
        with self.Session() as db:
            destination = self._destination(db)
            comment = YouTubeComment(
                destination_id=destination.id,
                video_id="vid1",
                youtube_comment_id="yt-2",
                text_original="hi",
                comment_text="hi",
                status="replied",
                reply_status="replied",
                youtube_reply_id="already",
            )
            db.add(comment)
            db.commit()

            with patch.object(
                yc, "insert_comment_reply", side_effect=AssertionError("must not call")
            ):
                cp.post_reply(db, comment, destination, "duplicate?")

        self.assertEqual(comment.youtube_reply_id, "already")

    def test_post_reply_requires_force_ssl_scope(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.credentials = json.dumps(
                {
                    "refresh_token": "fake",
                    "scopes": [
                        "https://www.googleapis.com/auth/youtube.upload",
                        "https://www.googleapis.com/auth/youtube.readonly",
                    ],
                }
            )
            comment = YouTubeComment(
                destination_id=destination.id,
                video_id="vid1",
                youtube_comment_id="yt-3",
                text_original="hi",
                comment_text="hi",
                status="ready_to_reply",
                reply_status="ready_to_reply",
            )
            db.add(comment)
            db.commit()

            with patch.object(
                yc, "insert_comment_reply", side_effect=AssertionError("must not call")
            ):
                cp.post_reply(db, comment, destination, "hello")

            self.assertEqual(comment.status, "failed")
            self.assertEqual(comment.error, "YOUTUBE_SCOPE_MISSING")

    def test_post_reply_records_youtube_reply_id(self):
        with self.Session() as db:
            destination = self._destination(db)
            comment = YouTubeComment(
                destination_id=destination.id,
                video_id="vid1",
                youtube_comment_id="yt-4",
                text_original="hi",
                comment_text="hi",
                status="ready_to_reply",
                reply_status="ready_to_reply",
            )
            db.add(comment)
            db.commit()

            # Patch the name the poller actually calls, and hand it a client
            # so no real credential refresh is attempted.
            with patch.object(
                cp, "insert_comment_reply", return_value="reply-42"
            ) as mocked:
                cp.post_reply(
                    db, comment, destination, "Thanks!", youtube=object()
                )

            mocked.assert_called_once()

        self.assertEqual(comment.status, "replied")
        self.assertEqual(comment.reply_status, "replied")
        self.assertEqual(comment.youtube_reply_id, "reply-42")
        self.assertIsNotNone(comment.replied_at)

    def test_reconcile_marks_already_posted_reply(self):
        with self.Session() as db:
            destination = self._destination(db)
            comment = YouTubeComment(
                destination_id=destination.id,
                video_id="vid1",
                youtube_comment_id="parent-1",
                text_original="hi",
                comment_text="hi",
                status="replying",
                reply_status="replying",
            )
            db.add(comment)
            db.commit()

            fetched = [
                {
                    "youtube_comment_id": "reply-x",
                    "parent_comment_id": "parent-1",
                    "author_channel_id": "UC_channel_1",
                    "text_original": "Thanks!",
                    "published_at": datetime.now(timezone.utc),
                }
            ]
            resolved = cp._reconcile_replying(db, destination, fetched)
            db.commit()

        self.assertEqual(resolved, 1)
        self.assertEqual(comment.status, "replied")
        self.assertEqual(comment.youtube_reply_id, "reply-x")


# ---------------------------------------------------------------------------
# YouTube API layer
# ---------------------------------------------------------------------------


class YouTubeCommentServiceTests(unittest.TestCase):
    def test_insert_reply_uses_comments_insert_with_parent_id(self):
        calls = {}

        class _Comments:
            def insert(self, part=None, body=None):
                calls["part"] = part
                calls["body"] = body

                class _Req:
                    def execute(self_inner):
                        return {"id": "reply-1"}

                return _Req()

        class _YouTube:
            def comments(self):
                return _Comments()

        reply_id = yc.insert_comment_reply(_YouTube(), "parent-9", "Hello!")
        self.assertEqual(reply_id, "reply-1")
        self.assertEqual(calls["part"], "snippet")
        self.assertEqual(calls["body"]["snippet"]["parentId"], "parent-9")
        self.assertEqual(calls["body"]["snippet"]["textOriginal"], "Hello!")

    def test_fetch_normalizes_threads_and_children(self):
        class _Threads:
            def list(self, **kwargs):
                class _Req:
                    def execute(self_inner):
                        return {
                            "items": [
                                {
                                    "snippet": {
                                        "topLevelComment": {
                                            "id": "top-1",
                                            "snippet": {
                                                "authorDisplayName": "Ann",
                                                "authorChannelId": {"value": "UC_a"},
                                                "textOriginal": "great!",
                                                "likeCount": 3,
                                                "canReply": True,
                                            },
                                        }
                                    },
                                    "replies": {
                                        "comments": [
                                            {
                                                "id": "child-1",
                                                "snippet": {
                                                    "authorDisplayName": "Channel",
                                                    "authorChannelId": {
                                                        "value": "UC_channel_1"
                                                    },
                                                    "textOriginal": "thanks",
                                                },
                                            }
                                        ]
                                    },
                                }
                            ]
                        }

                return _Req()

        class _YouTube:
            def commentThreads(self):
                return _Threads()

        comments, next_token = yc.fetch_video_comments(_YouTube(), "vid-1")
        self.assertIsNone(next_token)
        self.assertEqual(len(comments), 2)
        self.assertIsNone(comments[0]["parent_comment_id"])
        self.assertEqual(comments[0]["youtube_comment_id"], "top-1")
        self.assertEqual(comments[0]["like_count"], 3)
        self.assertEqual(comments[1]["parent_comment_id"], "top-1")

        candidates = list(yc.iter_reply_candidates(comments))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["youtube_comment_id"], "top-1")

    def test_comments_disabled_maps_to_stable_code(self):
        from googleapiclient.errors import HttpError

        class _Resp:
            status = 403
            reason = "Forbidden"

        exc = HttpError(
            _Resp(),
            json.dumps(
                {"error": {"errors": [{"reason": "commentsDisabled"}]}}
            ).encode(),
        )
        try:
            yc.raise_for_http_error(exc)
        except yc.CommentServiceError as err:
            self.assertEqual(err.code, yc.COMMENTS_DISABLED)
        else:  # pragma: no cover
            self.fail("expected CommentServiceError")

    def test_quota_exceeded_maps_to_stable_code(self):
        from googleapiclient.errors import HttpError

        class _Resp:
            status = 403
            reason = "Forbidden"

        exc = HttpError(
            _Resp(),
            json.dumps(
                {"error": {"errors": [{"reason": "quotaExceeded"}]}}
            ).encode(),
        )
        try:
            yc.raise_for_http_error(exc)
        except yc.CommentServiceError as err:
            self.assertEqual(err.code, yc.YOUTUBE_QUOTA_EXCEEDED)
        else:  # pragma: no cover
            self.fail("expected CommentServiceError")


# ---------------------------------------------------------------------------
# HTTP layer — isolation must hold through the real routes
# ---------------------------------------------------------------------------


class CommentSettingsApiTests(_CommentTestBase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.db import get_db as real_get_db
        from app.main import app

        def _override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[real_get_db] = _override_db
        self._app = app
        self._client = TestClient(app)
        self._admin = {"X-Admin-Token": settings.admin_token}

    def tearDown(self):
        self._app.dependency_overrides.clear()
        super().tearDown()

    def test_settings_route_returns_comment_prompt_only(self):
        res = self._client.get(
            f"/api/channels/{self.destination_id}/comment-reply-settings",
            headers=self._admin,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["system_prompt"], COMMENT_PROMPT)
        self.assertNotIn(METADATA_PROMPT, data["system_prompt"])
        self.assertTrue(data["oauth_ready"])
        # The metadata prompt must not be reachable from this endpoint.
        self.assertNotIn("prompt_override", data)
        self.assertNotIn("metadata_profile", data)

    def test_patch_changes_only_the_comment_prompt(self):
        new_prompt = "You are the friendly comment manager. Be brief."
        res = self._client.patch(
            f"/api/channels/{self.destination_id}/comment-reply-settings",
            headers=self._admin,
            json={
                "system_prompt": new_prompt,
                "mode": "review",
                "daily_limit": 7,
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["system_prompt"], new_prompt)

        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            # Comment fields changed...
            self.assertEqual(destination.comment_reply_system_prompt, new_prompt)
            self.assertEqual(destination.comment_reply_mode, "review")
            self.assertEqual(destination.comment_reply_daily_limit, 7)
            # ...metadata fields did not.
            self.assertEqual(destination.prompt_override, METADATA_PROMPT)
            self.assertEqual(
                destination.metadata_profile, "handsome boys entertainment"
            )
            self.assertEqual(destination.metadata_language, "en")

    def test_comments_list_route_starts_empty(self):
        res = self._client.get(
            f"/api/channels/{self.destination_id}/comments",
            headers=self._admin,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])
        self.assertTrue(data["oauth_ready"])

    def test_oauth_scope_state_is_reported_per_channel(self):
        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            destination.credentials = json.dumps(
                {
                    "refresh_token": "fake",
                    "scopes": [
                        "https://www.googleapis.com/auth/youtube.upload",
                        "https://www.googleapis.com/auth/youtube.readonly",
                    ],
                }
            )
            db.commit()

        res = self._client.get(
            f"/api/channels/{self.destination_id}/comment-reply-settings",
            headers=self._admin,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["oauth_ready"])
        self.assertEqual(data["oauth_reason"], "YOUTUBE_SCOPE_MISSING")

    def test_requires_admin_token(self):
        res = self._client.get(
            f"/api/channels/{self.destination_id}/comments"
        )
        self.assertEqual(res.status_code, 401)


# ---------------------------------------------------------------------------
# End-to-end worker scan (mocked YouTube + AI)
# ---------------------------------------------------------------------------


def _thread(comment_id, text, author="Ann", channel="UC_viewer"):
    return {
        "youtube_comment_id": comment_id,
        "parent_comment_id": None,
        "video_id": "vid1",
        "author_channel_id": channel,
        "author_name": author,
        "text_original": text,
        "published_at": datetime.now(timezone.utc),
        "like_count": 1,
        "can_reply": True,
    }


class EndToEndScanTests(_CommentTestBase):
    def _seed_published_video(self, db):
        from app.models import DouyinVideo, Publication

        video = DouyinVideo(
            id=str(uuid4()),
            pipeline_id=self.pipeline_id,
            video_id="douyin-1",
            title="Douyin source",
            description="",
            url="https://www.douyin.com/video/1",
            status="published",
        )
        db.add(video)
        db.commit()
        db.add(
            Publication(
                id=str(uuid4()),
                pipeline_id=self.pipeline_id,
                douyin_video_id=video.id,
                destination_id=self.destination_id,
                platform="youtube",
                status="published",
                external_post_id="vid1",
                published_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    def _run_scan(self, comments, ai_payload, mode, first_scan=False):
        inserted: list[tuple[str, str]] = []
        captured: dict = {}

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured.setdefault("systems", []).append(json["messages"][0]["content"])
            return _FakeResponse(ai_payload)

        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            destination.comment_reply_mode = mode
            if mode == "off":
                destination.comment_reply_enabled = False
            # `first_scan=False` means the channel was scanned before, so new
            # comments are eligible. first_scan=True exercises the backfill rule.
            destination.last_comment_scan_at = (
                None
                if first_scan
                else datetime.now(timezone.utc) - timedelta(hours=1)
            )
            db.commit()
            self._seed_published_video(db)

            def _fake_insert(youtube, parent_comment_id, text):
                inserted.append((parent_comment_id, text))
                return "reply-99"

            with patch.object(
                cp, "build_destination_client", return_value=(None, object())
            ), patch.object(
                cp, "fetch_video_titles", return_value={"vid1": "Best of 2026"}
            ), patch.object(
                cp, "fetch_video_comments", return_value=(comments, None)
            ), patch.object(
                cp, "insert_comment_reply", _fake_insert
            ), patch.object(
                acr.httpx, "post", _fake_post
            ):
                summary = cp.scan_destination(db, destination)

            rows = db.query(YouTubeComment).all()
            return summary, rows, inserted, captured

    def test_review_mode_drafts_without_posting(self):
        summary, rows, inserted, captured = self._run_scan(
            [_thread("c1", "love this!")],
            _reply_payload(),
            "review",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "ready_to_reply")
        self.assertEqual(rows[0].ai_reply, "Glad you enjoyed it!")
        self.assertEqual(rows[0].ai_classification, "POSITIVE")
        self.assertEqual(inserted, [])
        self.assertEqual(summary["drafted"], 1)
        # Isolation holds in the worker path too.
        self.assertEqual(captured["systems"], [COMMENT_PROMPT])

    def test_auto_mode_posts_the_reply(self):
        summary, rows, inserted, captured = self._run_scan(
            [_thread("c2", "great moves")],
            _reply_payload(reply="Thank you so much!"),
            "auto",
        )
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0], "c2")
        self.assertEqual(inserted[0][1], "Thank you so much!")
        self.assertEqual(rows[0].status, "replied")
        self.assertEqual(rows[0].youtube_reply_id, "reply-99")
        self.assertEqual(summary["replied"], 1)
        self.assertEqual(captured["systems"], [COMMENT_PROMPT])

    def test_spam_comment_is_held_and_never_posted(self):
        summary, rows, inserted, _captured = self._run_scan(
            [_thread("c3", "FREE CRYPTO CLICK HERE")],
            _reply_payload(
                classification="SPAM", should_reply=True, reply="sure!"
            ),
            "auto",
        )
        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "held")
        self.assertEqual(summary["replied"], 0)

    def test_second_scan_does_not_duplicate_comments(self):
        comments = [_thread("c4", "hi")]
        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            destination.comment_reply_mode = "review"
            db.commit()
            self._seed_published_video(db)

            with patch.object(
                cp, "build_destination_client", return_value=(None, object())
            ), patch.object(
                cp, "fetch_video_titles", return_value={}
            ), patch.object(
                cp, "fetch_video_comments", return_value=(comments, None)
            ), patch.object(
                cp, "insert_comment_reply", return_value="never"
            ), patch.object(
                acr.httpx, "post", lambda *a, **k: _FakeResponse(_reply_payload())
            ):
                cp.scan_destination(db, destination)
                cp.scan_destination(db, destination)

            total = db.query(YouTubeComment).count()

        self.assertEqual(total, 1)

    def test_auto_mode_does_not_blast_backlog_on_first_scan(self):
        summary, rows, inserted, _captured = self._run_scan(
            [_thread("c9", "old comment from weeks ago")],
            _reply_payload(),
            "auto",
            first_scan=True,
        )
        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "ignored")
        self.assertIn("first scan", rows[0].ai_reason)
        self.assertEqual(summary["replied"], 0)

    def test_disabled_channel_is_skipped_entirely(self):
        summary, rows, inserted, _captured = self._run_scan(
            [_thread("c5", "hello")], _reply_payload(), "off"
        )
        self.assertEqual(rows, [])
        self.assertEqual(inserted, [])
        self.assertEqual(summary["fetched"], 0)

    def test_child_reply_is_stored_but_never_replied_to(self):
        child = _thread("child-1", "me too")
        child["parent_comment_id"] = "parent-1"
        summary, rows, inserted, _captured = self._run_scan(
            [_thread("parent-1", "first"), child],
            _reply_payload(),
            "auto",
        )
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0], "parent-1")
        statuses = sorted(r.youtube_comment_id for r in rows)
        self.assertEqual(statuses, ["child-1", "parent-1"])


if __name__ == "__main__":
    unittest.main()
