"""AI comment reply — sentiment-routed, and PROMPT-ISOLATED from metadata.

Two hard rules shape this module:

1. SENTIMENT ROUTING (cost + tone).
   Every comment costs exactly ONE classification call. Only a ``positive``
   comment costs a SECOND call, to draft one short thank-you sentence. Every
   other label is answered from :data:`CLASSIFICATION_EMOJI`, a deterministic
   backend map — no model is asked to write text for them.

2. PROMPT ISOLATION.
   The comment flow builds its reply prompt ONLY from
   ``destination.comment_reply_system_prompt`` (or the neutral built-in
   default constant below). It never reads, merges, or falls back to
   ``destination.prompt_override`` / ``metadata_profile`` /
   ``metadata_language`` — the fields that drive title/description/hashtags.
   Classification uses a fixed backend-owned classifier prompt (so a channel
   prompt can never derail the machine-readable label), but it still comes
   from the comment subsystem and is never the metadata prompt.

There is intentionally no shared generic "generate with channel prompt"
helper: ``app.ai_metadata.generate_metadata_structured`` and
``generate_comment_reply`` below are two separate functions with two separate
prompt sources, which is what keeps the isolation test meaningful.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, NamedTuple

import httpx

from app.config import settings
from app.models import Destination


logger = logging.getLogger("ai-comment-reply")


# ---------------------------------------------------------------------------
# Classification vocabulary
# ---------------------------------------------------------------------------

POSITIVE = "positive"
QUESTION = "question"
NEUTRAL = "neutral"
NEGATIVE = "negative"
FUNNY = "funny"
EXCITED = "excited"
EMOJI_ONLY = "emoji_only"

#: Labels the model may return. Exactly one per comment.
COMMENT_CLASSIFICATIONS = (
    POSITIVE,
    QUESTION,
    NEUTRAL,
    NEGATIVE,
    FUNNY,
    EXCITED,
    EMOJI_ONLY,
)

#: Deterministic backend reply for every NON-positive label. These are mapped
#: straight from the label — the backend never calls a model to write them.
CLASSIFICATION_EMOJI = {
    QUESTION: "\U0001f60a",  # 😊
    NEUTRAL: "\u2764\ufe0f",  # ❤️
    NEGATIVE: "\U0001f64f",  # 🙏
    FUNNY: "\U0001f602",  # 😂
    EXCITED: "\U0001f525",  # 🔥
    EMOJI_ONLY: "\u2764\ufe0f",  # ❤️
}

#: Labels that must never be answered, whatever a channel config says.
#: The 7-label rule set routes that decision through the per-category channel
#: filters instead (``reply_to_negative`` etc., off by default), so this stays
#: empty on purpose — but the hook remains so a future label can be withheld
#: globally without touching callers.
HOLD_CLASSIFICATIONS: tuple[str, ...] = ()

#: Tolerated synonyms, including the legacy UPPERCASE vocabulary of the first
#: implementation (spam/abuse/sensitive now fold into `negative`, which is
#: opt-in and off by default).
_LABEL_ALIASES = {
    "praise": POSITIVE,
    "appreciation": POSITIVE,
    "admiration": POSITIVE,
    "support": POSITIVE,
    "compliment": POSITIVE,
    "thanks": POSITIVE,
    "questions": QUESTION,
    "inquiry": QUESTION,
    "asking": QUESTION,
    "normal": NEUTRAL,
    "other": NEUTRAL,
    "misc": NEUTRAL,
    "complaint": NEGATIVE,
    "criticism": NEGATIVE,
    "angry": NEGATIVE,
    "sad": NEGATIVE,
    "humor": FUNNY,
    "humour": FUNNY,
    "joke": FUNNY,
    "funny_comment": FUNNY,
    "hype": EXCITED,
    "enthusiastic": EXCITED,
    "amazed": EXCITED,
    "emoji": EMOJI_ONLY,
    "emojis": EMOJI_ONLY,
    "emoji_only_comment": EMOJI_ONLY,
    # Legacy vocabulary (pre sentiment-routing implementation).
    "spam": NEGATIVE,
    "abuse": NEGATIVE,
    "sensitive": NEGATIVE,
    "skip": NEUTRAL,
}

#: The ONLY classifier prompt. Backend-owned so the label stays machine
#: readable no matter what channel prompt is configured.
CLASSIFIER_PROMPT = (
    "You classify YouTube comments. Read the comment and pick EXACTLY ONE "
    "label from this list:\n"
    "- positive: praise, appreciation, admiration, support, gratitude, a "
    "compliment about the video, the creator, the music or the editing.\n"
    "- question: a genuine question or information request.\n"
    "- neutral: plain, factual or low-emotion remarks that are neither "
    "praise, nor a question, nor hostile.\n"
    "- negative: criticism, complaint, insult, hostility, spam or anything "
    "the channel should not answer cheerfully.\n"
    "- funny: a joke, pun, teasing or playful remark.\n"
    "- excited: hype, strong enthusiasm, all-caps excitement, or many fire / "
    "clap emojis together with words.\n"
    "- emoji_only: the comment has no words at all, only emoji or symbols.\n\n"
    "Answer with a single JSON object and nothing else:\n"
    '{"label": "positive|question|neutral|negative|funny|excited|emoji_only", '
    '"confidence": 0.0}\n'
    "Never explain. Never add prose."
)

#: Neutral default used ONLY when a channel has no comment prompt of its own.
#: This is not the metadata prompt and must never be replaced by one.
DEFAULT_COMMENT_REPLY_PROMPT = (
    "You are the comment assistant for this YouTube channel.\n\n"
    "Rules:\n"
    "- Detect the language of the viewer's comment.\n"
    "- If the comment is positive praise, appreciation, admiration, or "
    "support, reply with one short natural thank-you sentence in the same "
    "language.\n"
    "- Keep replies concise and human.\n"
    "- Never mention AI.\n"
    "- Never use hashtags.\n"
    "- Never write promotional text.\n"
    "- Never ask follow-up questions.\n"
    "- Maximum one short sentence.\n"
    "- At most one emoji.\n\n"
    "For non-positive comments, the backend may replace the response with a "
    "predefined emoji according to classification."
)

#: Appended to whatever reply prompt is in force. Backend hard rules: they are
#: also enforced after the model answers (see :func:`enforce_positive_reply`),
#: so a custom channel prompt can never weaken them.
POSITIVE_HARD_RULES = (
    "Hard rules for the thank-you reply (highest priority, always enforced):\n"
    "- Write in the SAME language as the viewer's comment.\n"
    "- Thank the viewer; be warm, natural and human.\n"
    "- At most ONE short sentence.\n"
    "- No hashtags, no links, no promotional text.\n"
    "- Never ask a question back.\n"
    "- Never mention \"AI\" or that you are a bot.\n"
    "- At most ONE emoji.\n"
    "- Never repeat the viewer's comment back to them.\n\n"
    "Return ONLY a JSON object:\n"
    '{"reply": "your single thank-you sentence"}'
)

STYLE_INSTRUCTIONS = {
    "friendly": "Tone: friendly, warm and casual.",
    "funny": "Tone: light and playful, a small joke is welcome but stay kind.",
    "warm": "Tone: warm, grateful and encouraging.",
    "short": "Tone: very short — a single brief sentence.",
    "professional": "Tone: polite, professional and measured.",
    "custom": "Tone: follow the channel profile above exactly.",
}

_LANGUAGE_NAMES = {
    "auto": "the same language as the comment",
    "en": "English",
    "vi": "Vietnamese",
    "zh": "Chinese",
    "ko": "Korean",
    "ja": "Japanese",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "th": "Thai",
    "id": "Indonesian",
}

#: Bounded retry budget: (primary tries, fallback tries).
_PRIMARY_TRIES = 2  # first attempt + 1 retry
_FALLBACK_TRIES = 1


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def normalize_label(raw: Any) -> str | None:
    """Return a canonical lowercase label, or None when nothing matches."""
    value = str(raw or "").strip().lower()
    if not value:
        return None
    value = value.replace("-", "_").replace(" ", "_")
    if value in COMMENT_CLASSIFICATIONS:
        return value
    return _LABEL_ALIASES.get(value)


def is_emoji_only(text: str) -> bool:
    """True when a comment carries no letters or digits at all.

    Such a comment is ``emoji_only`` by definition, so the classifier is
    skipped entirely (one model call saved per emoji comment).
    """
    value = text or ""
    return not any(ch.isalnum() for ch in value)


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Cheap heuristic language guess for a comment (en/vi/zh/... )."""
    value = (text or "").strip()
    if not value:
        return "en"

    if re.search(r"[\u3040-\u30ff]", value):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", value):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", value):
        return "zh"
    if re.search(r"[\u0e00-\u0e7f]", value):
        return "th"

    lowered = value.lower()
    vietnamese_markers = (
        "ạ", "ả", "ấ", "ầ", "ẩ", "ẫ", "ậ", "ắ", "ằ", "ẳ", "ẵ", "ặ",
        "ế", "ề", "ể", "ễ", "ệ", "ố", "ồ", "ổ", "ỗ", "ộ", "ơ", "ờ", "ở",
        "ỡ", "ợ", "ư", "ừ", "ử", "ữ", "ự", "ị", "ỉ", "ĩ", "ọ", "ỏ", "õ",
        "ụ", "ủ", "ũ", "ỳ", "ỷ", "ỹ", "ỵ", "đ",
    )
    if any(marker in lowered for marker in vietnamese_markers):
        return "vi"
    if re.search(r"\b(la|gi|khong|không|cai|nay|này|hay|quá|qua|đẹp|dep)\b", lowered):
        return "vi"
    return "en"


def resolve_reply_language(comment_text: str, channel_language: str | None) -> str:
    """Language the reply should be written in.

    Default is the commenter's own language; a channel may pin a specific one.
    """
    setting = (channel_language or "auto").strip().lower()
    if setting and setting != "auto":
        return setting
    return detect_language(comment_text)


def build_comment_reply_system_prompt(destination: Destination | None) -> str:
    """The ONLY system prompt for comment replies.

    Reads nothing but ``comment_reply_system_prompt``. The metadata prompt
    (``prompt_override``) is intentionally unreachable from here.
    """
    if destination is not None:
        custom = (destination.comment_reply_system_prompt or "").strip()
        if custom:
            return custom
    return DEFAULT_COMMENT_REPLY_PROMPT


# ---------------------------------------------------------------------------
# AI plumbing
# ---------------------------------------------------------------------------

class _AIConfig(NamedTuple):
    enabled: bool
    api_key: str
    base_url: str
    model: str
    fallback_model: str
    temperature: float
    max_tokens: int


def _ai_config() -> _AIConfig:
    """Transport settings shared with the gateway, model settings NOT.

    The base URL / key are the shared AI gateway; the model, temperature and
    token budget belong to the comment-reply feature alone so it never rides
    on the metadata model configuration.
    """
    ai_enabled = (
        bool(settings.ai_enabled)
        or os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    api_key = (settings.ai_api_key or os.getenv("AI_API_KEY", "")).strip()
    base_url = (
        settings.ai_base_url
        or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
    ).rstrip("/")

    model = (
        settings.comment_reply_model
        or os.getenv("COMMENT_REPLY_MODEL", "")
    ).strip() or "groq/qwen/qwen3.8-27b"
    fallback_model = (
        settings.comment_reply_fallback_model
        or os.getenv("COMMENT_REPLY_FALLBACK_MODEL", "")
    ).strip() or "gpt-oss-20b"

    try:
        temperature = float(settings.comment_reply_temperature)
    except (TypeError, ValueError):
        temperature = 0.3
    try:
        max_tokens = int(settings.comment_reply_max_tokens)
    except (TypeError, ValueError):
        max_tokens = 80

    return _AIConfig(
        enabled=ai_enabled,
        api_key=api_key,
        base_url=base_url,
        model=model,
        fallback_model=fallback_model if fallback_model != model else "",
        temperature=max(0.0, min(2.0, temperature)),
        max_tokens=max(16, min(1024, max_tokens)),
    )


def _chat(cfg: _AIConfig, model: str, messages: list[dict[str, str]]) -> str:
    """One chat-completions call. Raises on any transport/HTTP/body error."""
    response = httpx.post(
        cfg.base_url + "/chat/completions",
        headers={
            "Authorization": "Bearer " + cfg.api_key,
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        },
        timeout=45,
    )
    response.raise_for_status()

    raw_text = response.text
    if raw_text.endswith("data: [DONE]\n\n") or "\n" in raw_text:
        raw_text = raw_text.split("\n")[0]

    body = json.loads(raw_text)
    return body["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", value, flags=re.S)
    if not match:
        raise RuntimeError("AI did not return JSON")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise RuntimeError("Invalid AI JSON")
    return parsed


def _tiers(cfg: _AIConfig) -> tuple[tuple[str, int], ...]:
    tiers = ((cfg.model, _PRIMARY_TRIES),)
    if cfg.fallback_model:
        tiers += ((cfg.fallback_model, _FALLBACK_TRIES),)
    return tiers


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _parse_classification(content: str) -> tuple[str | None, float, str]:
    """Return (label|None, confidence, reason) from a model answer."""
    raw = (content or "").strip()
    if not raw:
        return None, 0.0, ""

    data: dict[str, Any] | None
    try:
        data = _extract_json(raw)
    except Exception:
        data = None

    if data is None:
        # Tolerate a bare label word ("positive") even though the prompt asks
        # for JSON — the value is still validated against the vocabulary.
        label = normalize_label(raw)
        return (label, 0.0, "") if label else (None, 0.0, "")

    label = normalize_label(
        data.get("label") or data.get("classification") or data.get("category")
    )
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        label,
        max(0.0, min(1.0, confidence)),
        str(data.get("reason") or "").strip()[:500],
    )


def classify_comment(
    comment_text: str,
    *,
    destination: Destination | None = None,
    video_title: str | None = None,
    comment_language: str | None = None,
) -> dict[str, Any]:
    """Classify ONE comment into exactly one of the 7 labels.

    Returns ``{ok, error, classification, confidence, reason, language,
    detected_language, calls, model}``.

    ``ok`` is True whenever a label is available. When every model answer is
    unusable the label degrades to ``neutral`` (safe: it is not auto-replied
    unless the channel opts in), and ``ok`` stays True. ``ok`` is False only
    when no usable answer could be obtained at all (AI off, every call errored
    at the transport level) — the caller then records the exact error.
    """
    text = (comment_text or "").strip()
    detected = comment_language or detect_language(text)
    target_language = resolve_reply_language(
        text,
        destination.comment_reply_language if destination else "auto",
    )
    base: dict[str, Any] = {
        "ok": True,
        "error": None,
        "classification": NEUTRAL,
        "confidence": 0.0,
        "reason": "",
        "language": target_language,
        "detected_language": detected,
        "calls": 0,
        "model": None,
    }

    if not text:
        return {**base, "ok": False, "error": "EMPTY_COMMENT"}

    # No words at all => emoji_only, by definition. No model call needed.
    if is_emoji_only(text):
        return {
            **base,
            "classification": EMOJI_ONLY,
            "reason": "no words in comment (detected locally)",
        }

    cfg = _ai_config()
    if not cfg.enabled or not cfg.api_key:
        return {
            **base,
            "ok": False,
            "error": "AI_DISABLED: AI_ENABLED/AI_API_KEY not configured",
        }

    messages = [
        {"role": "system", "content": CLASSIFIER_PROMPT},
        {
            "role": "user",
            "content": _classifier_user_block(text, detected, video_title),
        },
    ]

    calls = 0
    saw_response = False
    last_error: str | None = None

    for model, tries in _tiers(cfg):
        for _ in range(tries):
            try:
                content = _chat(cfg, model, messages)
                calls += 1
                saw_response = True
            except Exception as exc:
                calls += 1
                last_error = f"{model}: {type(exc).__name__}: {exc}"
                logger.warning("Comment classification call failed (%s)", last_error)
                # A transport error is not worth retrying the same model.
                break

            label, confidence, reason = _parse_classification(content)
            if label is not None:
                return {
                    **base,
                    "classification": label,
                    "confidence": confidence,
                    "reason": reason,
                    "calls": calls,
                    "model": model,
                }
            last_error = (
                f"{model}: invalid classification output {content.strip()[:120]!r}"
            )
            logger.warning("Comment classification retry: %s", last_error)

    if saw_response:
        return {
            **base,
            "classification": NEUTRAL,
            "reason": "classification output invalid; defaulted to neutral",
            "calls": calls,
            "error": None,
        }

    return {
        **base,
        "ok": False,
        "error": last_error or "AI_CLASSIFICATION_FAILED",
        "calls": calls,
    }


def _classifier_user_block(
    text: str,
    detected: str,
    video_title: str | None,
) -> str:
    lines = []
    if video_title:
        lines.append(f"Video title: {_collapse(video_title)[:300]}")
    lines.append(f"Comment language detected: {detected}")
    lines.append("")
    lines.append("Comment to classify:")
    lines.append(text[:2000])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reply building
# ---------------------------------------------------------------------------

# An emoji "cluster": a base emoji, optional variation selector, and any ZWJ
# joined parts (so a family/pin emoji counts as one).
_EMOJI_CLUSTER_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2})"
    "|(?:"
    "[\U0001F000-\U0001FAFF\u2190-\u21FF\u2600-\u27BF\u2B00-\u2BFF]"
    "\uFE0F?"
    "(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]\uFE0F?)*"
    ")"
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\u3002\uff01\uff1f\u2026])\s+")
_HASHTAG_RE = re.compile(r"#\S+")
_LINK_RE = re.compile(r"(?:https?://|www\.)\S+", flags=re.I)
# Only uppercase "AI" is stripped: lowercase "ai" is a real Vietnamese word.
_AI_MENTION_RES = (
    re.compile(r"\bA\.I\.\b", flags=re.I),
    re.compile(r"(?i)\b(?:as an ai|i am an ai|i'm an ai|an ai assistant|ai assistant)\b"),
    re.compile(r"\bAI\b"),
)
_COMPARE_STRIP_RE = re.compile(r"[^0-9a-z\u00c0-\u024f\u0100-\u017f\u4e00-\u9fff]+")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _limit_one_emoji(text: str) -> str:
    """Keep at most one emoji cluster, dropping any extras."""
    matches = list(_EMOJI_CLUSTER_RE.finditer(text))
    if len(matches) <= 1:
        return text
    for extra in reversed(matches[1:]):
        text = text[: extra.start()] + text[extra.end():]
    return _collapse(text)


def _normalize_for_compare(text: str) -> str:
    return _collapse(
        _COMPARE_STRIP_RE.sub(" ", (text or "").lower())
    )


def enforce_positive_reply(reply: str, comment_text: str) -> str:
    """Apply the POSITIVE hard rules in the backend, after the model speaks.

    Returns the compliant reply, or "" when nothing usable survives — the
    caller must never send random text, so an empty result is a failure, not
    a fallback string.
    """
    text = (reply or "").strip()
    if not text:
        return ""

    # Strip a stray surrounding quote pair the model sometimes adds.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()

    text = _collapse(text)
    text = _LINK_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(" ", text)
    for pattern in _AI_MENTION_RES:
        text = pattern.sub(" ", text)
    text = _collapse(text)
    # Keep a copy for the sentence split below, which drops everything after
    # the first sentence — including an emoji parked after the full stop.
    text_before_splitting = text

    # One short sentence, and never a question back.
    sentences = [
        part
        for part in _SENTENCE_SPLIT_RE.split(text)
        if part.strip() and "?" not in part and "\uff1f" not in part
    ]
    if not sentences:
        return ""
    text = sentences[0].strip()

    # A single emoji the model parked after the sentence end ("Thank you! ❤️")
    # still belongs to the reply.
    if not _EMOJI_CLUSTER_RE.search(text):
        first_emoji = _EMOJI_CLUSTER_RE.search(text_before_splitting)
        if first_emoji:
            text = _collapse(f"{text} {first_emoji.group(0)}")
    text = _limit_one_emoji(text)
    text = text.strip(" \t-–—,;:")

    # Never echo the viewer's own comment back at them.
    reply_norm = _normalize_for_compare(text)
    comment_norm = _normalize_for_compare(comment_text)
    if reply_norm and reply_norm == comment_norm:
        return ""
    if comment_norm and len(comment_norm) >= 8 and comment_norm in reply_norm:
        remainder = reply_norm.replace(comment_norm, " ", 1)
        if not re.search(r"[0-9a-z\u00c0-\u024f\u4e00-\u9fff]", remainder):
            return ""

    # A thank-you must actually contain words.
    if not re.search(r"[0-9A-Za-z\u00c0-\u024f\u0100-\u017f\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        return ""

    if len(text) > 240:
        text = text[:240].rsplit(" ", 1)[0].strip()
        text = _limit_one_emoji(text)
    return text


def _parse_reply_text(content: str) -> str:
    """Pull the reply out of a model answer (JSON object, else plain text)."""
    raw = (content or "").strip()
    if not raw:
        return ""
    try:
        data = _extract_json(raw)
    except Exception:
        return raw
    if isinstance(data, dict):
        for key in ("reply", "text", "message", "response"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    return raw


def _reply_context_lines(
    *,
    language_name: str,
    detected: str,
    style_line: str,
    video_title: str | None,
    comment_text: str,
) -> list[str]:
    lines = [
        f"Reply language: {language_name}.",
        f"Comment language detected: {detected}.",
        style_line,
        "",
    ]
    if video_title:
        lines.append(f"Video title: {video_title}")
    lines.append("")
    lines.append("Viewer comment to thank:")
    lines.append(comment_text[:2000])
    return lines


def build_reply_for_classification(
    classification: str,
    comment_text: str,
    *,
    destination: Destination | None = None,
    channel_prompt: str | None = None,
    video_title: str | None = None,
    reply_language: str | None = None,
    detected_language: str | None = None,
    style: str | None = None,
) -> dict[str, Any]:
    """Build the reply for an already-known label.

    ``positive`` -> one AI thank-you call. Every other label -> deterministic
    emoji from :data:`CLASSIFICATION_EMOJI`, with NO model call.
    """
    label = normalize_label(classification) or NEUTRAL
    text = (comment_text or "").strip()
    result: dict[str, Any] = {
        "ok": True,
        "error": None,
        "classification": label,
        "should_reply": True,
        "reply": "",
        "calls": 0,
        "model": None,
    }

    emoji = CLASSIFICATION_EMOJI.get(label)
    if emoji is not None:
        result["reply"] = emoji
        return result

    # ---- positive: ONE short thank-you generation call -------------------
    if not text:
        return {**result, "ok": False, "should_reply": False, "error": "EMPTY_COMMENT"}

    cfg = _ai_config()
    if not cfg.enabled or not cfg.api_key:
        return {
            **result,
            "ok": False,
            "should_reply": False,
            "error": "AI_DISABLED: AI_ENABLED/AI_API_KEY not configured",
        }

    system_prompt = (
        channel_prompt.strip()
        if (channel_prompt or "").strip()
        else build_comment_reply_system_prompt(destination)
    )
    detected = detected_language or detect_language(text)
    target_language = reply_language or resolve_reply_language(
        text,
        destination.comment_reply_language if destination else "auto",
    )
    language_name = _LANGUAGE_NAMES.get(
        (target_language or "auto").lower(), _LANGUAGE_NAMES["auto"]
    )
    style_key = (
        style
        or (destination.comment_reply_style if destination else "friendly")
        or "friendly"
    ).lower()
    style_line = STYLE_INSTRUCTIONS.get(style_key, STYLE_INSTRUCTIONS["friendly"])

    messages = [
        {
            "role": "system",
            "content": f"{system_prompt}\n\n{POSITIVE_HARD_RULES}",
        },
        {
            "role": "user",
            "content": "\n".join(
                _reply_context_lines(
                    language_name=language_name,
                    detected=detected,
                    style_line=style_line,
                    video_title=video_title,
                    comment_text=text,
                )
            ),
        },
    ]

    calls = 0
    last_error: str | None = None
    for model, tries in _tiers(cfg):
        for _ in range(tries):
            try:
                content = _chat(cfg, model, messages)
                calls += 1
            except Exception as exc:
                calls += 1
                last_error = f"{model}: {type(exc).__name__}: {exc}"
                logger.warning("Comment reply generation failed (%s)", last_error)
                break

            reply = enforce_positive_reply(_parse_reply_text(content), text)
            if reply:
                return {
                    **result,
                    "reply": reply,
                    "calls": calls,
                    "model": model,
                }
            last_error = f"{model}: reply rejected by backend hard rules"
            logger.warning("Comment reply retry: %s", last_error)

    return {
        **result,
        "ok": False,
        "should_reply": False,
        "error": last_error or "AI_REPLY_FAILED",
        "calls": calls,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def generate_comment_reply(
    comment_text: str,
    *,
    channel_prompt: str | None = None,
    destination: Destination | None = None,
    video_title: str | None = None,
    video_description: str | None = None,
    comment_language: str | None = None,
    reply_language: str | None = None,
    style: str | None = None,
    parent_context: str | None = None,
    allow_positive: bool = True,
) -> dict[str, Any] | None:
    """Classify one comment and build its reply.

    Cost shape: exactly one classification call, plus one generation call only
    when the label is ``positive`` AND ``allow_positive`` is True. Callers that
    already know positive replies are disabled pass ``allow_positive=False``
    so a disabled category never spends a generation call.

    Returns ``{ok, error, classification, should_reply, confidence, reply,
    reason, language, calls, model}``, or None for empty input.
    """
    text = (comment_text or "").strip()
    if not text:
        return None

    classification = classify_comment(
        text,
        destination=destination,
        comment_language=comment_language,
    )
    result: dict[str, Any] = {
        "ok": bool(classification["ok"]),
        "error": classification.get("error"),
        "classification": classification["classification"],
        "should_reply": False,
        "confidence": classification.get("confidence", 0.0),
        "reply": "",
        "reason": classification.get("reason", ""),
        "language": classification.get("language", "en"),
        "calls": classification.get("calls", 0),
        "model": classification.get("model"),
    }
    if not classification["ok"]:
        return result

    label = classification["classification"]
    if label == POSITIVE and not allow_positive:
        result["reason"] = "positive replies disabled for this channel"
        return result

    built = build_reply_for_classification(
        label,
        text,
        destination=destination,
        channel_prompt=channel_prompt,
        video_title=video_title,
        reply_language=reply_language or classification.get("language"),
        detected_language=classification.get("detected_language"),
        style=style,
    )
    result["calls"] += built.get("calls", 0)
    if built.get("model"):
        result["model"] = built["model"]
    if not built["ok"]:
        result["ok"] = False
        result["error"] = built["error"]
        return result

    result["should_reply"] = bool(built["should_reply"])
    result["reply"] = built["reply"]
    return result


__all__ = [
    "CLASSIFICATION_EMOJI",
    "CLASSIFIER_PROMPT",
    "COMMENT_CLASSIFICATIONS",
    "DEFAULT_COMMENT_REPLY_PROMPT",
    "EMOJI_ONLY",
    "EXCITED",
    "FUNNY",
    "HOLD_CLASSIFICATIONS",
    "NEGATIVE",
    "NEUTRAL",
    "POSITIVE",
    "POSITIVE_HARD_RULES",
    "QUESTION",
    "build_comment_reply_system_prompt",
    "build_reply_for_classification",
    "classify_comment",
    "detect_language",
    "enforce_positive_reply",
    "generate_comment_reply",
    "is_emoji_only",
    "normalize_label",
    "resolve_reply_language",
]
