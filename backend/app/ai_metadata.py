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

    return tag[:60]


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

        title = str(
            data.get("title")
            or ""
        ).strip()

        if not title:
            raise RuntimeError(
                "AI returned empty title"
            )

        title = title[:100]

        description = str(
            data.get("description")
            or ""
        ).strip()

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

        # If fewer than 5 hashtags, fallback to fixed or generic tags
        if len(hashtags) < 5:
            fallback_candidates = []
            if destination and destination.fixed_hashtags:
                fallback_candidates.extend(destination.fixed_hashtags)
            elif pipeline and pipeline.fixed_hashtags:
                fallback_candidates.extend(pipeline.fixed_hashtags)
            fallback_candidates.extend(["#shorts", "#trending", "#viral", "#video"])
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
    if not res:
        return None
    return (res["title"], res["final_description"])
