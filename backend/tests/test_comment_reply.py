"""AI YouTube comment reply tests — sentiment routing + prompt isolation.

Two things are proven here and must never regress:

* sentiment routing — praise costs ONE thank-you generation call, every other
  label is answered from the backend emoji map with NO second model call;
* prompt isolation — the comment flow reads only the comment prompt, while the
  metadata flow reads only the metadata prompt.
"""

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
    """Chat-completions response whose message content is JSON."""

    def __init__(self, content):
        self.text = json.dumps(
            {"choices": [{"message": {"content": json.dumps(content)}}]}
        )
        self.status_code = 200

    def raise_for_status(self):
        return None


class _RawResponse:
    """Chat-completions response whose message content is plain text."""

    def __init__(self, content):
        self.text = json.dumps({"choices": [{"message": {"content": content}}]})
        self.status_code = 200

    def raise_for_status(self):
        return None


class _Gateway:
    """Scripted fake of the AI gateway.

    ``classify`` / ``generate`` are response queues consumed in call order;
    each item is a payload, a raw string (returned verbatim), or an exception
    to raise. ``fail_models`` makes a model always fail like a timeout.
    """

    def __init__(
        self,
        *,
        classify=None,
        generate=None,
        fail_models=(),
        fail_all=False,
    ):
        self.classify = list(classify or [])
        self.generate = list(generate or [])
        self.fail_models = set(fail_models)
        self.fail_all = fail_all
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        model = json.get("model")
        system = json["messages"][0]["content"]
        kind = "classify" if system == acr.CLASSIFIER_PROMPT else "generate"
        self.calls.append(
            {
                "model": model,
                "kind": kind,
                "system": system,
                "messages": json["messages"],
            }
        )

        if self.fail_all or model in self.fail_models:
            raise RuntimeError(f"gateway down: {model}")

        queue = self.classify if kind == "classify" else self.generate
        if queue:
            item = queue.pop(0)
        else:
            item = (
                {"label": "positive"}
                if kind == "classify"
                else {"reply": "Thank you so much!"}
            )
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return _RawResponse(item)
        return _FakeResponse(item)

    @property
    def models(self):
        return [call["model"] for call in self.calls]

    @property
    def kinds(self):
        return [call["kind"] for call in self.calls]

    def calls_of(self, kind):
        return [call for call in self.calls if call["kind"] == kind]


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

    def _generate(self, text, gateway, **kwargs):
        with self.Session() as db:
            destination = self._destination(db)
            with patch.object(acr.httpx, "post", gateway):
                return acr.generate_comment_reply(
                    text, destination=destination, **kwargs
                )


# ---------------------------------------------------------------------------
# PROMPT ISOLATION — the hard requirement
# ---------------------------------------------------------------------------


class PromptIsolationTests(_CommentTestBase):
    def test_comment_reply_uses_only_the_comment_prompt(self):
        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[{"reply": "Glad you enjoyed it!"}],
        )
        result = self._generate(
            "love this channel!", gateway, video_title="Best moments"
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["classification"], acr.POSITIVE)
        self.assertEqual(result["reply"], "Glad you enjoyed it!")

        # Classification is backend-owned...
        classify_system = gateway.calls_of("classify")[0]["system"]
        self.assertEqual(classify_system, acr.CLASSIFIER_PROMPT)

        # ...and the thank-you uses the CHANNEL's comment prompt + hard rules.
        generate_system = gateway.calls_of("generate")[0]["system"]
        self.assertTrue(generate_system.startswith(COMMENT_PROMPT))
        self.assertIn(acr.POSITIVE_HARD_RULES, generate_system)

        for call in gateway.calls:
            self.assertNotIn(METADATA_PROMPT, call["system"])
            self.assertNotIn(METADATA_PROMPT, call["messages"][1]["content"])

    def test_channel_prompt_never_reaches_the_classifier(self):
        gateway = _Gateway(classify=[{"label": "neutral"}])
        self._generate("plain remark", gateway)

        classify_system = gateway.calls_of("classify")[0]["system"]
        self.assertNotIn("Handsome Boys Universe", classify_system)
        self.assertEqual(classify_system, acr.CLASSIFIER_PROMPT)

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

    def test_default_prompt_documents_the_routing_rules(self):
        prompt = acr.DEFAULT_COMMENT_REPLY_PROMPT
        self.assertIn(
            "You are the comment assistant for this YouTube channel.", prompt
        )
        self.assertIn("Maximum one short sentence.", prompt)
        self.assertIn("At most one emoji.", prompt)
        self.assertIn("Never mention AI.", prompt)
        self.assertIn("Never use hashtags.", prompt)
        self.assertIn("Never ask follow-up questions.", prompt)
        self.assertIn("predefined emoji according to classification", prompt)

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
        """Regression: comment replies must not change metadata generation."""
        captured = {}

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured["messages"] = json["messages"]
            return _FakeResponse(
                {
                    "title": "Generated Title",
                    "description": "Clean description",
                    "hashtags": ["#a1", "#a2", "#a3", "#a4", "#a5"],
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
            second = acr.build_comment_reply_system_prompt(
                db.get(Destination, other.id)
            )

        self.assertEqual(first, COMMENT_PROMPT)
        self.assertEqual(second, other_prompt)
        self.assertNotEqual(first, second)


# ---------------------------------------------------------------------------
# Sentiment routing: one classify call, a second only for positive
# ---------------------------------------------------------------------------


class SentimentRoutingTests(_CommentTestBase):
    def test_positive_comment_gets_one_ai_thank_you(self):
        gateway = _Gateway(
            classify=[{"label": "positive", "confidence": 0.93}],
            generate=[{"reply": "Thank you so much!"}],
        )
        result = self._generate("Your videos are amazing!", gateway)

        self.assertTrue(result["ok"])
        self.assertEqual(result["classification"], "positive")
        self.assertTrue(result["should_reply"])
        self.assertEqual(result["reply"], "Thank you so much!")
        self.assertEqual(result["confidence"], 0.93)
        self.assertEqual(gateway.kinds, ["classify", "generate"])

    def test_every_non_positive_label_is_a_backend_emoji(self):
        expected = {
            "question": "\U0001f60a",
            "neutral": "\u2764\ufe0f",
            "negative": "\U0001f64f",
            "funny": "\U0001f602",
            "excited": "\U0001f525",
        }
        for label, emoji in expected.items():
            with self.subTest(label=label):
                gateway = _Gateway(classify=[{"label": label}])
                result = self._generate("a comment", gateway)

                self.assertTrue(result["ok"])
                self.assertEqual(result["classification"], label)
                self.assertEqual(result["reply"], emoji)
                self.assertTrue(result["should_reply"])
                # Exactly ONE model call: classification. No generation call.
                self.assertEqual(gateway.kinds, ["classify"])

    def test_emoji_only_maps_to_heart(self):
        gateway = _Gateway(classify=[{"label": "whatever"}])
        result = self._generate("\U0001f525\U0001f525", gateway)

        self.assertEqual(result["classification"], "emoji_only")
        self.assertEqual(result["reply"], "\u2764\ufe0f")
        # Detected locally: not even the classification call is made.
        self.assertEqual(gateway.calls, [])

    def test_positive_disabled_spends_no_generation_call(self):
        gateway = _Gateway(classify=[{"label": "positive"}])
        result = self._generate("amazing!", gateway, allow_positive=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["classification"], "positive")
        self.assertFalse(result["should_reply"])
        self.assertEqual(result["reply"], "")
        self.assertEqual(gateway.kinds, ["classify"])

    def test_known_praise_uses_two_calls_only(self):
        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[{"reply": "Thanks!"}],
        )
        self._generate("great video", gateway)
        self.assertEqual(len(gateway.calls), 2)

    def test_confidence_is_clamped(self):
        gateway = _Gateway(classify=[{"label": "positive", "confidence": 9}])
        result = self._generate("great video", gateway)
        self.assertEqual(result["confidence"], 1.0)

    def test_bare_label_word_is_accepted(self):
        gateway = _Gateway(classify=["neutral"])
        result = self._generate("ok then", gateway)
        self.assertEqual(result["classification"], "neutral")

    def test_json_inside_a_code_fence_is_accepted(self):
        gateway = _Gateway(classify=['```json\n{"label": "funny"}\n```'])
        result = self._generate("haha good one", gateway)
        self.assertEqual(result["classification"], "funny")

    def test_legacy_uppercase_vocabulary_still_maps(self):
        self.assertEqual(acr.normalize_label("POSITIVE"), "positive")
        self.assertEqual(acr.normalize_label("emoji-only"), "emoji_only")
        # Legacy safety labels fold into negative (opt-in, off by default).
        self.assertEqual(acr.normalize_label("SPAM"), "negative")
        self.assertEqual(acr.normalize_label("SENSITIVE"), "negative")
        self.assertIsNone(acr.normalize_label("banana"))


# ---------------------------------------------------------------------------
# Invalid output, retry budget and fallback model
# ---------------------------------------------------------------------------


class FallbackTests(_CommentTestBase):
    def test_invalid_output_retries_once_then_uses_the_fallback_model(self):
        gateway = _Gateway(
            classify=[
                {"label": "banana"},  # primary attempt
                {"label": "banana"},  # primary retry
                {"label": "banana"},  # fallback attempt
            ]
        )
        result = self._generate("hmm", gateway)

        self.assertTrue(result["ok"])
        self.assertEqual(result["classification"], "neutral")
        self.assertIn("neutral", result["reason"])
        self.assertEqual(len(gateway.calls), 3)
        models = gateway.models
        self.assertEqual(models[0], "groq/qwen/qwen3.8-27b")
        self.assertEqual(models[1], models[0])
        self.assertEqual(models[2], "gpt-oss-20b")

    def test_valid_fallback_answer_is_used(self):
        gateway = _Gateway(
            classify=[{"label": "nope"}, {"label": "nope"}, {"label": "funny"}]
        )
        result = self._generate("haha", gateway)
        self.assertEqual(result["classification"], "funny")
        self.assertEqual(result["model"], "gpt-oss-20b")

    def test_primary_timeout_falls_back_to_the_second_model(self):
        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[{"reply": "Thank you so much!"}],
            fail_models={"groq/qwen/qwen3.8-27b"},
        )
        result = self._generate("nice one", gateway)

        self.assertTrue(result["ok"])
        self.assertEqual(result["classification"], "positive")
        self.assertEqual(result["model"], "gpt-oss-20b")
        self.assertEqual(gateway.models[0], "groq/qwen/qwen3.8-27b")
        self.assertEqual(gateway.models[1], "gpt-oss-20b")

    def test_both_models_failing_reports_the_exact_error(self):
        gateway = _Gateway(fail_all=True)
        result = self._generate("hello", gateway)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reply"], "")
        self.assertFalse(result["should_reply"])
        self.assertIn("RuntimeError", result["error"])
        self.assertIn("gpt-oss-20b", result["error"])
        # Bounded: one try per tier, never an infinite retry loop.
        self.assertEqual(len(gateway.calls), 2)

    def test_ai_disabled_reports_a_stable_error(self):
        with self.Session() as db:
            destination = self._destination(db)
            with patch.object(acr.settings, "ai_enabled", False), patch.object(
                acr.settings, "ai_api_key", ""
            ), patch.dict("os.environ", {"AI_ENABLED": "false", "AI_API_KEY": ""}):
                result = acr.generate_comment_reply(
                    "hello", destination=destination
                )
        self.assertFalse(result["ok"])
        self.assertIn("AI_DISABLED", result["error"])

    def test_rejected_generation_is_a_failure_not_random_text(self):
        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[
                {"reply": "Your videos are amazing!"},  # echo of the comment
                {"reply": "Your videos are amazing!"},
                {"reply": "Your videos are amazing!"},
            ],
        )
        result = self._generate("Your videos are amazing!", gateway)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reply"], "")
        self.assertIn("hard rules", result["error"])

    def test_empty_comment_is_not_sent_to_the_model(self):
        gateway = _Gateway()
        self.assertIsNone(
            self._generate("   ", gateway)
        )
        self.assertEqual(gateway.calls, [])


# ---------------------------------------------------------------------------
# POSITIVE hard rules, enforced in the backend
# ---------------------------------------------------------------------------


class PositiveReplyRulesTests(unittest.TestCase):
    def test_spec_examples_are_kept(self):
        self.assertEqual(
            acr.enforce_positive_reply(
                "Thank you so much! \u2764\ufe0f", "Your videos are amazing!"
            ),
            "Thank you so much! \u2764\ufe0f",
        )
        self.assertEqual(
            acr.enforce_positive_reply(
                "C\u1ea3m \u01a1n b\u1ea1n nhi\u1ec1u nh\u00e9 \u2764\ufe0f",
                "Video hay qu\u00e1",
            ),
            "C\u1ea3m \u01a1n b\u1ea1n nhi\u1ec1u nh\u00e9 \u2764\ufe0f",
        )
        self.assertEqual(
            acr.enforce_positive_reply(
                "\u8c22\u8c22\u4f60\u7684\u652f\u6301 \u2764\ufe0f",
                "\u592a\u5e05\u4e86",
            ),
            "\u8c22\u8c22\u4f60\u7684\u652f\u6301 \u2764\ufe0f",
        )
        self.assertEqual(
            acr.enforce_positive_reply(
                "\u3042\u308a\u304c\u3068\u3046\u3054\u3056\u3044\u307e\u3059\uff01\u2764\ufe0f",
                "\u6700\u9ad8\u3067\u3059\uff01",
            ),
            "\u3042\u308a\u304c\u3068\u3046\u3054\u3056\u3044\u307e\u3059\uff01\u2764\ufe0f",
        )

    def test_keeps_only_the_first_sentence(self):
        self.assertEqual(
            acr.enforce_positive_reply(
                "Thank you so much! Glad you liked it.", "nice"
            ),
            "Thank you so much!",
        )

    def test_drops_a_follow_up_question(self):
        text = acr.enforce_positive_reply(
            "Thanks! Do you want more videos?", "nice video"
        )
        self.assertEqual(text, "Thanks!")
        self.assertNotIn("?", text)

    def test_strips_hashtags_links_and_ai_mentions(self):
        text = acr.enforce_positive_reply(
            "Thanks a lot! #viral #love https://spam.example now",
            "great",
        )
        self.assertNotIn("#", text)
        self.assertNotIn("http", text)

        text = acr.enforce_positive_reply("As an AI I thank you", "great")
        self.assertNotIn("AI", text)

    def test_at_most_one_emoji(self):
        self.assertEqual(
            acr.enforce_positive_reply(
                "Thank you \U0001f525\U0001f602\U0001f64f", "wow"
            ),
            "Thank you \U0001f525",
        )

    def test_echoing_the_comment_is_rejected(self):
        self.assertEqual(
            acr.enforce_positive_reply(
                "Your videos are amazing!", "Your videos are amazing!"
            ),
            "",
        )

    def test_emoji_only_answer_is_rejected(self):
        self.assertEqual(acr.enforce_positive_reply("\u2764\ufe0f", "nice"), "")

    def test_empty_answer_is_rejected(self):
        self.assertEqual(acr.enforce_positive_reply("", "nice"), "")


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


class LanguageTests(unittest.TestCase):
    def test_detects_vietnamese_chinese_japanese_and_english(self):
        self.assertEqual(acr.detect_language("Video này hay quá"), "vi")
        self.assertEqual(acr.detect_language("很好"), "zh")
        self.assertEqual(acr.detect_language("最高です！"), "ja")
        self.assertEqual(acr.detect_language("nice video"), "en")

    def test_reply_defaults_to_commenter_language(self):
        self.assertEqual(acr.resolve_reply_language("hay quá", "auto"), "vi")

    def test_channel_language_overrides_comment_language(self):
        self.assertEqual(acr.resolve_reply_language("hay quá", "en"), "en")

    def test_thank_you_is_asked_in_the_commenter_language(self):
        for comment, expected in (
            ("Your videos are amazing!", "English"),
            ("Video hay quá", "Vietnamese"),
            ("太帅了", "Chinese"),
            ("最高です！", "Japanese"),
        ):
            with self.subTest(comment=comment):
                gateway = _Gateway(
                    classify=[{"label": "positive"}],
                    generate=[{"reply": "ok"}],
                )
                with patch.object(acr.httpx, "post", gateway):
                    acr.build_reply_for_classification(
                        "positive", comment, destination=None
                    )
                user_block = gateway.calls_of("generate")[0]["messages"][1][
                    "content"
                ]
                self.assertIn(f"Reply language: {expected}.", user_block)


# ---------------------------------------------------------------------------
# Filtering: one toggle per label
# ---------------------------------------------------------------------------


class EligibilityTests(_CommentTestBase):
    def test_defaults_follow_the_channel_configuration(self):
        with self.Session() as db:
            destination = self._destination(db)

            for label in ("positive", "POSITIVE", "question"):
                self.assertTrue(
                    cp.eligibility_reason(label, destination)[0], label
                )
            for label in (
                "neutral",
                "negative",
                "funny",
                "excited",
                "emoji_only",
                "SPAM",
            ):
                self.assertFalse(
                    cp.eligibility_reason(label, destination)[0], label
                )

    def test_each_toggle_controls_its_own_label(self):
        with self.Session() as db:
            destination = self._destination(db)
            destination.comment_reply_to_neutral = True
            destination.comment_reply_to_negative = True
            destination.comment_reply_to_funny = True
            destination.comment_reply_to_excited = True
            destination.comment_reply_to_emoji_only = True
            db.commit()

            for label in (
                "neutral",
                "negative",
                "funny",
                "excited",
                "emoji_only",
            ):
                eligible, reason = cp.eligibility_reason(label, destination)
                self.assertTrue(eligible, f"{label}: {reason}")

            destination.comment_reply_to_funny = False
            db.commit()
            eligible, reason = cp.eligibility_reason("funny", destination)
            self.assertFalse(eligible)
            self.assertIn("funny", reason)

    def test_unknown_label_is_never_eligible(self):
        with self.Session() as db:
            destination = self._destination(db)
            eligible, reason = cp.eligibility_reason("banana", destination)
            self.assertFalse(eligible)
            self.assertIn("no policy", reason)

    def test_emoji_only_detection(self):
        self.assertTrue(cp.is_emoji_only("🔥🔥"))
        self.assertFalse(cp.is_emoji_only("nice 🔥"))


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
                yc,
                "insert_comment_reply",
                side_effect=AssertionError("must not call"),
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
                yc,
                "insert_comment_reply",
                side_effect=AssertionError("must not call"),
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

            with patch.object(
                cp, "insert_comment_reply", return_value="reply-42"
            ) as mocked:
                cp.post_reply(db, comment, destination, "Thanks!", youtube=object())

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
# HTTP layer — isolation and the new filters must hold through the routes
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
        self.assertFalse(data["reply_to_funny"])
        self.assertFalse(data["reply_to_excited"])
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
                "reply_to_funny": True,
                "reply_to_excited": True,
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["system_prompt"], new_prompt)
        self.assertTrue(res.json()["reply_to_funny"])
        self.assertTrue(res.json()["reply_to_excited"])

        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            # Comment fields changed...
            self.assertEqual(destination.comment_reply_system_prompt, new_prompt)
            self.assertEqual(destination.comment_reply_mode, "review")
            self.assertEqual(destination.comment_reply_daily_limit, 7)
            self.assertTrue(destination.comment_reply_to_funny)
            self.assertTrue(destination.comment_reply_to_excited)
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

    def test_scan_fails_loudly_without_force_ssl_scope(self):
        """The scan must never answer "queued" when it cannot read YouTube."""
        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            destination.credentials = json.dumps(
                {
                    "refresh_token": "fake",
                    "scopes": [
                        "https://www.googleapis.com/auth/youtube.readonly",
                    ],
                }
            )
            db.commit()

        res = self._client.post(
            f"/api/channels/{self.destination_id}/comments/scan",
            headers=self._admin,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "YOUTUBE_SCOPE_MISSING")

    def test_scan_queues_and_reports_the_reply_mode(self):
        res = self._client.post(
            f"/api/channels/{self.destination_id}/comments/scan",
            headers=self._admin,
        )

        self.assertEqual(res.status_code, 202)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["mode"], "review")
        self.assertEqual(body["destination_id"], self.destination_id)


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

    def _run_scan(self, comments, gateway, mode, first_scan=False, **dest_config):
        inserted: list[tuple[str, str]] = []

        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            destination.comment_reply_mode = mode
            # Picking REVIEW/AUTO in the UI also switches the assistant on.
            destination.comment_reply_enabled = mode != "off"
            # `first_scan=False` means the channel was scanned before, so new
            # comments are eligible. first_scan=True exercises the backfill rule.
            destination.last_comment_scan_at = (
                None
                if first_scan
                else datetime.now(timezone.utc) - timedelta(hours=1)
            )
            for key, value in dest_config.items():
                setattr(destination, key, value)
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
                acr.httpx, "post", gateway
            ):
                summary = cp.scan_destination(db, destination)

            rows = db.query(YouTubeComment).all()
            return summary, rows, inserted, gateway

    def test_review_mode_drafts_without_posting(self):
        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[{"reply": "Thank you so much!"}],
        )
        summary, rows, inserted, gateway = self._run_scan(
            [_thread("c1", "love this!")], gateway, "review"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "ready_to_reply")
        self.assertEqual(rows[0].ai_reply, "Thank you so much!")
        self.assertEqual(rows[0].ai_classification, "positive")
        self.assertEqual(inserted, [])
        self.assertEqual(summary["drafted"], 1)
        # Isolation holds in the worker path too.
        for call in gateway.calls:
            self.assertNotIn(METADATA_PROMPT, call["system"])
        self.assertTrue(
            gateway.calls_of("generate")[0]["system"].startswith(COMMENT_PROMPT)
        )

    def test_auto_mode_posts_the_thank_you(self):
        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[{"reply": "Thank you so much!"}],
        )
        summary, rows, inserted, _gateway = self._run_scan(
            [_thread("c2", "great moves")], gateway, "auto"
        )

        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0], "c2")
        self.assertEqual(inserted[0][1], "Thank you so much!")
        self.assertEqual(rows[0].status, "replied")
        self.assertEqual(rows[0].youtube_reply_id, "reply-99")
        self.assertEqual(summary["replied"], 1)

    def test_auto_mode_sends_the_question_emoji(self):
        gateway = _Gateway(classify=[{"label": "question"}])
        summary, rows, inserted, gateway = self._run_scan(
            [_thread("c3", "what is that dance?")], gateway, "auto"
        )

        self.assertEqual(inserted, [("c3", "\U0001f60a")])
        self.assertEqual(rows[0].status, "replied")
        self.assertEqual(rows[0].ai_classification, "question")
        self.assertEqual(summary["replied"], 1)
        # Only the classification call was made.
        self.assertEqual(gateway.kinds, ["classify"])

    def test_auto_mode_holds_a_disabled_category_without_a_generation_call(self):
        gateway = _Gateway(classify=[{"label": "neutral"}])
        summary, rows, inserted, gateway = self._run_scan(
            [_thread("c4", "post this on douyin")], gateway, "auto"
        )

        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "held")
        self.assertIn("neutral", rows[0].ai_reason)
        self.assertEqual(rows[0].ai_reply, None)
        self.assertEqual(gateway.kinds, ["classify"])
        self.assertEqual(summary["replied"], 0)

    def test_auto_mode_keeps_a_negative_comment_held_by_default(self):
        gateway = _Gateway(classify=[{"label": "negative"}])
        _summary, rows, inserted, gateway = self._run_scan(
            [_thread("c5", "worst video ever")], gateway, "auto"
        )

        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "held")
        self.assertEqual(gateway.kinds, ["classify"])

    def test_auto_mode_does_not_generate_when_positive_is_disabled(self):
        gateway = _Gateway(classify=[{"label": "positive"}])
        _summary, rows, inserted, gateway = self._run_scan(
            [_thread("c14", "love this channel")],
            gateway,
            "auto",
            comment_reply_to_positive=False,
        )

        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "held")
        self.assertIn("positive", rows[0].ai_reason)
        # A disabled category must never spend a generation call.
        self.assertEqual(gateway.kinds, ["classify"])

    def test_funny_and_excited_follow_their_toggles(self):
        gateway = _Gateway(
            classify=[{"label": "funny"}, {"label": "excited"}]
        )
        summary, rows, inserted, gateway = self._run_scan(
            [_thread("c6", "haha nice joke"), _thread("c7", "LETS GOOOO")],
            gateway,
            "auto",
            comment_reply_to_funny=True,
            comment_reply_to_excited=True,
            # Two replies in one pass: the interval gate would queue the second.
            comment_reply_min_interval_seconds=0,
        )

        self.assertEqual(
            sorted(inserted), sorted([("c6", "\U0001f602"), ("c7", "\U0001f525")])
        )
        self.assertEqual(summary["replied"], 2)
        # Emoji replies never generate text.
        self.assertEqual(gateway.kinds, ["classify", "classify"])

    def test_emoji_only_comment_holds_by_default_and_costs_no_model_call(self):
        gateway = _Gateway()
        _summary, rows, inserted, gateway = self._run_scan(
            [_thread("c8", "\U0001f525\U0001f525")], gateway, "auto"
        )

        self.assertEqual(inserted, [])
        self.assertEqual(gateway.calls, [])
        self.assertEqual(rows[0].status, "held")
        self.assertEqual(rows[0].ai_classification, "emoji_only")

    def test_emoji_only_comment_is_answered_when_enabled(self):
        gateway = _Gateway()
        _summary, rows, inserted, gateway = self._run_scan(
            [_thread("c8b", "\U0001f525\U0001f525")],
            gateway,
            "auto",
            comment_reply_to_emoji_only=True,
        )

        self.assertEqual(inserted, [("c8b", "\u2764\ufe0f")])
        self.assertEqual(gateway.calls, [])

    def test_ai_failure_marks_the_comment_failed_with_the_exact_error(self):
        gateway = _Gateway(fail_all=True)
        summary, rows, inserted, _gateway = self._run_scan(
            [_thread("c8c", "nice one")], gateway, "auto"
        )

        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "failed")
        self.assertIn("RuntimeError", rows[0].error)
        self.assertEqual(summary["replied"], 0)

    def test_second_scan_does_not_duplicate_comments(self):
        comments = [_thread("c9", "hi")]
        gateway = _Gateway(classify=[{"label": "positive", "confidence": 0.5}])
        with self.Session() as db:
            destination = db.get(Destination, self.destination_id)
            destination.comment_reply_mode = "review"
            destination.comment_reply_enabled = True
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
                acr.httpx, "post", gateway
            ):
                cp.scan_destination(db, destination)
                cp.scan_destination(db, destination)

            total = db.query(YouTubeComment).count()

        self.assertEqual(total, 1)

    def test_auto_mode_does_not_blast_backlog_on_first_scan(self):
        gateway = _Gateway(classify=[{"label": "positive"}])
        summary, rows, inserted, _gateway = self._run_scan(
            [_thread("c10", "old comment from weeks ago")],
            gateway,
            "auto",
            first_scan=True,
        )

        self.assertEqual(inserted, [])
        self.assertEqual(rows[0].status, "ignored")
        self.assertIn("first scan", rows[0].ai_reason)
        self.assertEqual(summary["replied"], 0)

    def test_scan_while_ai_off_ingests_but_never_drafts(self):
        """Scanning is independent of the AI-reply switch (read-only ingest)."""
        gateway = _Gateway()
        summary, rows, inserted, gateway = self._run_scan(
            [_thread("c11", "hello")], gateway, "off"
        )

        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(summary["mode"], "off")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "new")
        self.assertEqual(rows[0].reply_status, "new")
        self.assertIsNone(rows[0].ai_reply)
        self.assertEqual(inserted, [])
        # No AI call is made when the assistant is off.
        self.assertEqual(gateway.calls, [])
        self.assertEqual(summary["drafted"], 0)

    def test_review_scan_drafts_comments_ingested_while_off(self):
        """Comments stored with the assistant OFF get a draft once REVIEW is on.

        Drafting never writes to YouTube, so this is safe; the alternative
        would be silently stranding every comment fetched before enabling.
        """
        first_gateway = _Gateway()
        _summary, first_rows, _inserted, first_gateway = self._run_scan(
            [_thread("c12", "love it")], first_gateway, "off"
        )
        self.assertEqual(first_rows[0].status, "new")
        self.assertEqual(first_gateway.calls, [])

        gateway = _Gateway(
            classify=[{"label": "positive"}],
            generate=[{"reply": "Thank you!"}],
        )
        summary, rows, inserted, gateway = self._run_scan([], gateway, "review")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "ready_to_reply")
        self.assertEqual(rows[0].ai_reply, "Thank you!")
        self.assertEqual(inserted, [])
        self.assertEqual(summary["drafted"], 1)

    def test_auto_scan_never_replies_to_comments_ingested_while_off(self):
        """AUTO must only reply to comments discovered by its own scan."""
        self._run_scan([_thread("c13", "great moves")], _Gateway(), "off")

        gateway = _Gateway(classify=[{"label": "positive"}])
        _summary, rows, inserted, _gateway = self._run_scan([], gateway, "auto")

        self.assertEqual(inserted, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "new")

    def test_child_reply_is_stored_but_never_replied_to(self):
        child = _thread("child-1", "me too")
        child["parent_comment_id"] = "parent-1"
        gateway = _Gateway(classify=[{"label": "question"}])
        _summary, rows, inserted, _gateway = self._run_scan(
            [_thread("parent-1", "first?"), child], gateway, "auto"
        )

        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0][0], "parent-1")
        ids = sorted(r.youtube_comment_id for r in rows)
        self.assertEqual(ids, ["child-1", "parent-1"])


if __name__ == "__main__":
    unittest.main()
