"""AI comment reply — PROMPT-ISOLATED from the metadata generator.

Hard rule enforced by this module's shape: the comment-reply flow builds its
system prompt ONLY from ``destination.comment_reply_system_prompt`` (or the
neutral built-in default constant below). It never reads, merges, or falls back
to ``destination.prompt_override`` / ``metadata_profile`` /
``metadata_language`` — the fields that drive title/description/hashtags.

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
from typing import Any

import httpx

from app.config import settings
from app.models import Destination


logger = logging.getLogger("ai-comment-reply")


#: Classification labels returned by the model.
POSITIVE = "POSITIVE"
QUESTION = "QUESTION"
NEUTRAL = "NEUTRAL"
NEGATIVE = "NEGATIVE"
SPAM = "SPAM"
ABUSE = "ABUSE"
SENSITIVE = "SENSITIVE"
SKIP = "SKIP"

COMMENT_CLASSIFICATIONS = (
    POSITIVE,
    QUESTION,
    NEUTRAL,
    NEGATIVE,
    SPAM,
    ABUSE,
    SENSITIVE,
    SKIP,
)

#: Classifications we must never auto-reply to.
HOLD_CLASSIFICATIONS = (NEGATIVE, SPAM, ABUSE, SENSITIVE, SKIP)

#: Neutral fallback used ONLY when a channel has no comment prompt of its own.
#: This is not the metadata prompt and must never be replaced by one.
DEFAULT_COMMENT_REPLY_PROMPT = (
    "You are the community manager replying to comments on a YouTube channel.\n"
    "You are NOT the on-camera creator and you never claim to be.\n\n"
    "Write short, natural, human replies (1-2 sentences).\n"
    "Rules:\n"
    "- Reply in the SAME language as the comment unless told otherwise.\n"
    "- Never repeat the comment back verbatim.\n"
    "- Never use more than one emoji, and never spam emoji.\n"
    "- Never use the same sentence for different people; vary your wording.\n"
    "- Never invent facts about filming, locations, or ownership. Do not say\n"
    '  "I filmed this", "I was there", or "thanks for supporting my original\n'
    '  video". Safe phrasing is warm and generic: "Glad you enjoyed it!".\n'
    "- Never promise anything, never share personal or contact details.\n"
    "- Never give legal, medical, or financial advice.\n"
    "- If the comment is spam, abuse, a threat, a copyright/takedown notice, a\n"
    "  business/partnership request, or a sensitive/controversial complaint,\n"
    "  set should_reply to false and let a human handle it.\n\n"
    "Classify the comment before replying. Allowed classifications:\n"
    "POSITIVE, QUESTION, NEUTRAL, NEGATIVE, SPAM, ABUSE, SENSITIVE, SKIP.\n\n"
    "Return ONLY a JSON object:\n"
    '{"classification": "POSITIVE|QUESTION|NEUTRAL|NEGATIVE|SPAM|ABUSE|'
    'SENSITIVE|SKIP", "should_reply": true, "confidence": 0.0, "reply": "", '
    '"reason": ""}\n'
    "Use an empty reply string whenever should_reply is false."
)

STYLE_INSTRUCTIONS = {
    "friendly": "Tone: friendly, warm and casual.",
    "funny": "Tone: light and playful, a small joke is welcome but stay kind.",
    "warm": "Tone: warm, grateful and encouraging.",
    "short": "Tone: very short — aim for a single brief sentence.",
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


def _normalize_result(
    data: dict[str, Any],
    *,
    reply_language: str,
) -> dict[str, Any]:
    classification = str(data.get("classification") or "").strip().upper()
    if classification not in COMMENT_CLASSIFICATIONS:
        classification = SKIP

    reply = str(data.get("reply") or "").strip()
    # Strip a stray surrounding quote pair the model sometimes adds.
    if len(reply) >= 2 and reply[0] == reply[-1] and reply[0] in "\"'":
        reply = reply[1:-1].strip()
    reply = re.sub(r"\s+", " ", reply)
    if len(reply) > 900:
        reply = reply[:900].rstrip()

    should_reply = data.get("should_reply")
    if isinstance(should_reply, str):
        should_reply = should_reply.strip().lower() in ("true", "1", "yes")
    should_reply = bool(should_reply)

    # A withheld classification can never be auto-sent, whatever the model said.
    if classification in HOLD_CLASSIFICATIONS:
        should_reply = False
    if should_reply and not reply:
        should_reply = False

    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "classification": classification,
        "should_reply": should_reply,
        "confidence": confidence,
        "reply": reply,
        "reason": str(data.get("reason") or "").strip()[:500],
        "language": reply_language,
    }


def _ai_config() -> tuple[bool, str, str, str]:
    ai_enabled = (
        bool(settings.ai_enabled)
        or os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    api_key = (settings.ai_api_key or os.getenv("AI_API_KEY", "")).strip()
    base_url = (
        settings.ai_base_url
        or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
    ).rstrip("/")
    model = settings.ai_model or os.getenv("AI_MODEL", "youtube-douyin")
    return ai_enabled, api_key, base_url, model


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
) -> dict[str, Any] | None:
    """Classify one comment and draft a reply.

    Returns a validated dict:
    ``{classification, should_reply, confidence, reply, reason, language}``
    or None when AI is unavailable / the call failed.

    The system prompt comes exclusively from the comment-reply prompt
    (explicit ``channel_prompt`` argument, else ``destination.
    comment_reply_system_prompt``, else the neutral default).
    """
    if not (comment_text or "").strip():
        return None

    ai_enabled, api_key, base_url, model = _ai_config()
    if not ai_enabled or not api_key:
        logger.warning("Comment reply AI unavailable (AI_ENABLED/AI_API_KEY)")
        return None

    system_prompt = (
        channel_prompt.strip()
        if (channel_prompt or "").strip()
        else build_comment_reply_system_prompt(destination)
    )

    detected = comment_language or detect_language(comment_text)
    target_language = (
        reply_language
        or resolve_reply_language(
            comment_text,
            destination.comment_reply_language if destination else "auto",
        )
    )
    language_name = _LANGUAGE_NAMES.get(
        (target_language or "auto").lower(),
        _LANGUAGE_NAMES["auto"],
    )

    style_key = (style or (destination.comment_reply_style if destination else "friendly") or "friendly").lower()
    style_line = STYLE_INSTRUCTIONS.get(style_key, STYLE_INSTRUCTIONS["friendly"])

    context_lines = [
        f"Reply language: {language_name}.",
        f"Comment language detected: {detected}.",
        style_line,
        "",
    ]
    if video_title:
        context_lines.append(f"Video title: {video_title}")
    if video_description:
        context_lines.append(
            "Video description: " + re.sub(r"\s+", " ", video_description)[:600]
        )
    if parent_context:
        context_lines.append(f"Thread context: {parent_context[:400]}")
    context_lines.append("")
    context_lines.append("Comment to handle:")
    context_lines.append(comment_text.strip()[:2000])

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(context_lines)},
        ],
        "temperature": 0.7,
        "max_tokens": 400,
    }

    try:
        response = httpx.post(
            base_url + "/chat/completions",
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        response.raise_for_status()

        raw_text = response.text
        if raw_text.endswith("data: [DONE]\n\n") or "\n" in raw_text:
            raw_text = raw_text.split("\n")[0]

        body = json.loads(raw_text)
        content = body["choices"][0]["message"]["content"]
        data = _extract_json(content)
        return _normalize_result(data, reply_language=target_language)
    except Exception:
        logger.exception("AI comment reply generation failed")
        return None


__all__ = [
    "COMMENT_CLASSIFICATIONS",
    "DEFAULT_COMMENT_REPLY_PROMPT",
    "HOLD_CLASSIFICATIONS",
    "build_comment_reply_system_prompt",
    "detect_language",
    "generate_comment_reply",
    "resolve_reply_language",
]
