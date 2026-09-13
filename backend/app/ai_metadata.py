import json
import logging
import os
import re
from pathlib import Path

import httpx


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


def generate_youtube_metadata(
    context_text: str,
) -> tuple[str, str] | None:
    """
    Generate YouTube metadata using AI.
    Returns (title, final_description_with_hashtags)
    """
    if not os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes"):
        logger.warning("AI_ENABLED is false")
        return None

    api_key = os.getenv(
        "AI_API_KEY",
        "",
    ).strip()

    if not api_key:
        logger.warning(
            "AI_API_KEY missing"
        )
        return None

    base_url = os.getenv(
        "AI_BASE_URL",
        "https://api.toolnet.tech/v1",
    ).rstrip("/")

    model = os.getenv(
        "AI_MODEL",
        "tn/claude-3.5-sonnet-20241022",
    )

    prompt = PROMPT_FILE.read_text(
        encoding="utf-8",
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
                "content": (
                    "ORIGINAL DOUYIN CONTEXT/SHARE TEXT:\n\n"
                    + context_text
                ),
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
            
        import json
        body = json.loads(raw_text)

        content = (
            body["choices"][0]
            ["message"]["content"]
        )

        data = extract_json(
            content
        )

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

        hashtags = []

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

        hashtag_text = " ".join(
            hashtags
        )

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

        return (
            title,
            final_description,
        )

    except Exception:
        logger.exception(
            "AI metadata generation failed"
        )
        return None
