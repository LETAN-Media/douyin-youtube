import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.models import Destination, Pipeline


logger = logging.getLogger("ai-metadata")

PROMPT_FILE = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "youtube_shorts_en.txt"
)


def extract_json(text: str) -> dict:
    value = text.strip()

    value = re.sub(
        r"^```(?:json)?\s*",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"\s*```$",
        "",
        value,
    )

    try:
        result = json.loads(value)

        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        value,
        flags=re.S,
    )

    if not match:
        raise RuntimeError(
            "AI did not return JSON"
        )

    result = json.loads(
        match.group(0)
    )

    if not isinstance(result, dict):
        raise RuntimeError(
            "Invalid AI JSON"
        )

    return result


def clean_hashtag(value: str) -> str:
    tag = value.strip().lower()

    if not tag:
        return ""

    tag = re.sub(
        r"\s+",
        "",
        tag,
    )

    if not tag.startswith("#"):
        tag = "#" + tag

    # Block disallowed channel name hashtags or attributions
    disallowed = {"#joybeat", "#danielxu", "#danniu", "#daniel"}
    if tag in disallowed:
        return ""

    return tag[:60]


DANCE_POSITIVE_KEYWORDS = [
    "舞蹈", "编舞", "翻跳", "街舞", "练舞", "舞者", "男舞者", "舞蹈教学", "跳舞",
    "极速翻跳", "齐舞", "爵士", "urban", "dance", "choreography", "dancer", "choreo",
    "dancecover", "kpopdance", "cpopdance", "dancepractice", "performance", "freestyle",
    "footwork", "asiandancer", "dancevideo", "popping", "locking", "hiphop", "krump",
    "waacking", "breaking", "c-pop dance", "k-pop dance"
]

NON_DANCE_DISQUALIFY_KEYWORDS = [
    "腹肌", "胸肌", "脱衣", "身材", "肌肉", "健身", "举铁", "健美", "健身房",
    "gym", "workout", "shirtless", "abs", "muscle", "fitness", "bodybuilding",
    "自拍", "男模", "美食", "吃播", "探店", "做饭", "车", "跑车", "搞笑", "段子"
]


def evaluate_content_match(
    context_text: str,
    niche: str | None = None,
    prompt_override: str | None = None,
) -> tuple[bool, str]:
    """Evaluate whether video content matches channel niche / criteria.

    Returns (is_match: bool, reason: str).
    """
    context_lower = (context_text or "").lower()
    niche_text = (niche or "").lower()
    prompt_text = (prompt_override or "").lower()

    is_dance_channel = (
        "dance" in niche_text
        or "dance" in prompt_text
        or "choreography" in niche_text
        or "choreography" in prompt_text
    )
    has_strict_match = (
        "content_mismatch" in prompt_text
        or "content selection" in prompt_text
        or is_dance_channel
    )

    if not has_strict_match:
        return True, "Channel does not enforce strict content match"

    has_dance_kw = any(kw.lower() in context_lower for kw in DANCE_POSITIVE_KEYWORDS)
    has_disqualify_kw = any(kw.lower() in context_lower for kw in NON_DANCE_DISQUALIFY_KEYWORDS)

    # Disqualify immediately if non-dance/fitness keywords present and no dance keywords
    if has_disqualify_kw and not has_dance_kw:
        return False, "CONTENT_MISMATCH: Contains non-dance/fitness/lifestyle keywords without dance context"

    ai_enabled = (
        bool(settings.ai_enabled)
        or os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    api_key = (settings.ai_api_key or os.getenv("AI_API_KEY", "")).strip()

    if not ai_enabled or not api_key:
        if has_dance_kw:
            return True, "Matched dance keywords via heuristic"
        return False, "CONTENT_MISMATCH: No dance keywords found in caption or hashtags"

    base_url = (
        settings.ai_base_url
        or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
    ).rstrip("/")
    model = settings.ai_model or os.getenv("AI_MODEL", "youtube-douyin")

    system_prompt = (
        "You are a strict content match evaluator for a YouTube dance channel.\n"
        "Your role: verify if the video is primarily dance, choreography, dance covers, or dance practice.\n\n"
        "STRICT REJECTION CRITERIA:\n"
        "- Reject pure gym/body showcases, shirtless posing with no dance, fitness, physique showcases.\n"
        "- Reject random lifestyle clips, food, cars, comedy, thirst-traps with no meaningful dance.\n\n"
        "Return ONLY a JSON object with this format:\n"
        '{\n  "match": true,\n  "reason": "explanation in English"\n}\n'
        "or\n"
        '{\n  "match": false,\n  "reason": "CONTENT_MISMATCH: reason in English"\n}'
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Douyin context:\n{context_text}"},
        ],
        "temperature": 0.2,
        "max_tokens": 150,
    }

    try:
        resp = httpx.post(
            base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        raw_text = resp.text
        if raw_text.endswith("data: [DONE]\n\n") or "\n" in raw_text:
            raw_text = raw_text.split("\n")[0]
        data = extract_json(json.loads(raw_text)["choices"][0]["message"]["content"])
        is_match = bool(data.get("match", False))
        reason = str(data.get("reason", "Evaluated by AI"))
        if not is_match and not reason.startswith("CONTENT_MISMATCH"):
            reason = f"CONTENT_MISMATCH: {reason}"
        return is_match, reason
    except Exception as e:
        logger.warning("AI content match evaluation failed (%s), falling back to heuristic", e)
        if has_dance_kw:
            return True, "Matched dance keywords via heuristic fallback"
        return False, "CONTENT_MISMATCH: No dance keywords detected (heuristic fallback)"


def generate_metadata_structured(
    context_text: str,
    pipeline: Pipeline | None = None,
    destination: Destination | None = None,
) -> dict[str, Any] | None:
    """Generate structured YouTube metadata using AI.

    Returns dict with keys:
    - title: str
    - description: str (clean caption text without trailing hashtags)
    - hashtags: list[str] (exactly 5 clean hashtags)
    - final_description: str (description + \\n\\n + hashtags)
    """
    ai_enabled = (
        bool(settings.ai_enabled)
        or os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    if not ai_enabled:
        logger.warning("AI_ENABLED is false")
        return None

    api_key = (
        settings.ai_api_key
        or os.getenv("AI_API_KEY", "")
    ).strip()

    if not api_key:
        logger.warning("AI_API_KEY missing")
        return None

    base_url = (
        settings.ai_base_url
        or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
    ).rstrip("/")

    model = (
        settings.ai_model
        or os.getenv("AI_MODEL", "youtube-douyin")
    )

    prompt = PROMPT_FILE.read_text(
        encoding="utf-8",
    )

    if destination is not None and destination.prompt_override and destination.prompt_override.strip():
        prompt = destination.prompt_override.strip()

    profile_section = ""
    if destination is not None:
        fixed_hashtags = (
            destination.fixed_hashtags
            if destination.fixed_hashtags is not None
            else (pipeline.fixed_hashtags if pipeline else [])
        ) or []
        adaptive_hashtags = (
            destination.adaptive_hashtags
            if destination.adaptive_hashtags is not None
            else (pipeline.adaptive_hashtags if pipeline else [])
        ) or []
        niche = (
            destination.metadata_profile
            or (pipeline.niche if pipeline else "")
        )
        language = (
            destination.metadata_language
            or (pipeline.language if pipeline else "en")
        )

        profile_section = (
            "\n\nDESTINATION AI PROFILE:\n"
            f"Channel: {destination.name} ({destination.platform})\n"
            f"Niche: {niche or ''}\n"
            f"Language: {language or 'en'}\n"
            f"Fixed hashtags: {', '.join(fixed_hashtags)}\n"
            f"Adaptive hashtags: {', '.join(adaptive_hashtags)}\n"
            "\n"
            "Use this channel profile to tailor title, description, and hashtags.\n"
            "You must include fixed hashtags if provided.\n"
            "Total hashtags must be EXACTLY 5 hashtags."
        )
    elif pipeline is not None:
        fixed_hashtags = pipeline.fixed_hashtags or []
        adaptive_hashtags = pipeline.adaptive_hashtags or []

        profile_section = (
            "\n\nPIPELINE PROFILE:\n"
            f"Name: {pipeline.name}\n"
            f"Niche: {pipeline.niche or ''}\n"
            f"Language: {pipeline.language or 'en'}\n"
            f"Fixed hashtags: {', '.join(fixed_hashtags)}\n"
            f"Adaptive hashtags: {', '.join(adaptive_hashtags)}\n"
            "\n"
            "Use this pipeline profile to keep channel identity in the metadata.\n"
            "You must include all fixed hashtags.\n"
            "For the remaining slots, prefer adaptive hashtags supported by the content,\n"
            "then add video-specific topic hashtags if needed."
        )

    user_content = (
        "ORIGINAL DOUYIN CONTEXT/SHARE TEXT:\n\n"
        + context_text
        + profile_section
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "temperature": 0.5,
        "max_tokens": 700,
    }

    try:
        response = httpx.post(
            (
                base_url
                + "/chat/completions"
            ),
            headers={
                "Authorization": (
                    "Bearer "
                    + api_key
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json=payload,
            timeout=45,
        )

        response.raise_for_status()

        raw_text = response.text
        if raw_text.endswith("data: [DONE]\n\n") or "\n" in raw_text:
            raw_text = raw_text.split("\n")[0]

        body = json.loads(raw_text)

        content = (
            body["choices"][0]
            ["message"]["content"]
        )

        data = extract_json(content)

        if data.get("status") == "CONTENT_MISMATCH" or data.get("content_match") is False:
            reason = str(data.get("reason", "Content does not match channel niche"))
            logger.warning("AI flagged CONTENT_MISMATCH: %s", reason)
            return {
                "title": "",
                "description": "",
                "hashtags": [],
                "final_description": "",
                "content_match": False,
                "content_match_reason": f"CONTENT_MISMATCH: {reason}",
            }

        title = str(
            data.get("title")
            or ""
        ).strip()

        if not title:
            raise RuntimeError(
                "AI returned empty title"
            )

        if "CONTENT_MISMATCH" in title.upper():
            logger.warning("AI title indicates CONTENT_MISMATCH: %s", title)
            return {
                "title": "",
                "description": "",
                "hashtags": [],
                "final_description": "",
                "content_match": False,
                "content_match_reason": title,
            }

        title = title[:100]

        description = str(
            data.get("description")
            or ""
        ).strip()

        # Sanitize against hallucinated creator attributions unless present in original context
        ctx_lower = context_text.lower()
        if "daniel xu" not in ctx_lower and "daniel" not in ctx_lower:
            title = re.sub(r"(?i)\bdaniel\s+xu\b", "", title).strip()
            description = re.sub(r"(?i)\bdaniel\s+xu\b", "", description).strip()
        if "joybeat" not in ctx_lower:
            title = re.sub(r"(?i)\bjoybeat\b", "", title).strip()
            description = re.sub(r"(?i)\bjoybeat\b", "", description).strip()

        raw_tags = data.get(
            "hashtags"
        )

        if not isinstance(
            raw_tags,
            list,
        ):
            raw_tags = []

        hashtags: list[str] = []

        for item in raw_tags:
            tag = clean_hashtag(
                str(item)
            )

            if not tag:
                continue

            if tag in hashtags:
                continue

            hashtags.append(tag)

            if len(hashtags) == 5:
                break

        # If fewer than 5 hashtags, fallback to fixed or adaptive tags
        if len(hashtags) < 5:
            fallback_candidates = []
            if destination and destination.fixed_hashtags:
                fallback_candidates.extend(destination.fixed_hashtags)
            elif pipeline and pipeline.fixed_hashtags:
                fallback_candidates.extend(pipeline.fixed_hashtags)

            if destination and destination.adaptive_hashtags:
                fallback_candidates.extend(destination.adaptive_hashtags)
            elif pipeline and pipeline.adaptive_hashtags:
                fallback_candidates.extend(pipeline.adaptive_hashtags)

            fallback_candidates.extend(["#shorts", "#dance", "#choreography", "#video"])
            for cand in fallback_candidates:
                cleaned = clean_hashtag(str(cand))
                if cleaned and cleaned not in hashtags:
                    hashtags.append(cleaned)
                    if len(hashtags) == 5:
                        break

        hashtag_text = " ".join(hashtags)

        final_description = (
            description
            + "\n\n"
            + hashtag_text
        ).strip()

        logger.info(
            "AI metadata generated title=%r hashtags=%s",
            title,
            hashtag_text,
        )

        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "final_description": final_description,
            "content_match": True,
            "content_match_reason": "Matched channel criteria",
        }

    except Exception:
        logger.exception(
            "AI metadata generation failed"
        )
        return None


def generate_youtube_metadata(
    context_text: str,
    pipeline: Pipeline | None = None,
    destination: Destination | None = None,
) -> tuple[str, str] | None:
    """Generate YouTube metadata using AI.

    Returns (title, final_description_with_hashtags)
    """
    res = generate_metadata_structured(
        context_text,
        pipeline=pipeline,
        destination=destination,
    )
    if not res or not res.get("title") or res.get("content_match") is False:
        return None
    return (res["title"], res["final_description"])
