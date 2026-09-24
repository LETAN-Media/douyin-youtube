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

# Music / concert / stage context: not strictly dance, but strongly related.
# Heuristic verdict for these is BORDERLINE (advisory warning, still publishable);
# the AI evaluator may upgrade to MATCH when dance context is present.
MUSIC_CONTEXT_KEYWORDS = [
    "演唱会", "音乐", "歌曲", "舞台", "表演", "演出", "观众", "音乐节",
    "歌手", "巡演", "现场", "乐队", "俱乐部", "排练", "街头", "流行",
    "concert", "music", "song", "stage", "performance", "performing",
    "crowd", "audience", "festival", "singer", "artist", "rapper",
    "dj", "tour", "live", "show", "rehearsal", "street", "kpop",
    "k-pop", "pop", "band", "club", "challenge", "cover",
]

# Topics that are clearly unrelated to music/dance. Only treated as MISMATCH
# when NO dance and NO music/concert keywords are present.
CLEAR_MISMATCH_KEYWORDS = [
    "新闻", "联播", "时政",
    "美食", "吃播", "探店", "做饭", "餐厅", "外卖",
    "游戏", "电竞", "打游戏", "gaming", "gameplay",
    "汽车", "跑车", "买车", "修车",
    "猫", "狗", "宠物", "猫咪", "狗狗", "cat", "dog", "pet",
    "访谈", "采访", "聊天", "播客", "talkshow", "podcast",
    "购物", "带货", "直播卖货", "shopping",
    "财经", "股票", "股市", "政治", "贷款", "借贷",
    "news", "food", "mukbang", "cooking", "restaurant",
    "gaming", "esports", "car", "vehicle",
    "animal", "interview", "shopping",
    "finance", "stock", "crypto", "politics", "loan",
]

MATCH_LEVELS = ("match", "borderline", "mismatch")


def _has_any(text_lower: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text_lower for kw in keywords)


def _ai_verdict_niche(
    context_text: str,
    niche: str,
    model: str,
    base_url: str,
    api_key: str,
) -> tuple[str, str]:
    """Ask the AI for a 3-way verdict against the channel's own niche.

    Used for non-dance channels (e.g. cute pets) where the dance keyword
    lists do not apply. Returns (level, reason); failures fall back to
    "borderline" (advisory) rather than blocking.
    """
    system_prompt = (
        "You are a content relevance evaluator for a YouTube channel.\n"
        f"Channel niche: {niche}\n"
        "Decide a verdict for the Douyin video context (caption + hashtags + "
        "artist/event signals; exact keywords are NOT required, judge "
        "semantic fit):\n"
        '- "match": clearly fits the channel niche.\n'
        '- "borderline": plausibly related but weak evidence. Still publishable.\n'
        '- "mismatch": ONLY for clearly unrelated content with no connection '
        "to the niche.\n\n"
        "Return ONLY a JSON object:\n"
        '{"verdict": "match|borderline|mismatch", "reason": "explanation in English"}'
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
        verdict = str(
            data.get("verdict")
            or data.get("match_level")
            or ("match" if data.get("match") is True else "")
            or ("mismatch" if data.get("match") is False else "")
            or "borderline"
        ).lower()
        if verdict not in MATCH_LEVELS:
            verdict = "borderline"
        reason = str(data.get("reason", "Evaluated by AI"))
        if verdict == "mismatch" and not reason.startswith("CONTENT_MISMATCH"):
            reason = f"CONTENT_MISMATCH: {reason}"
        return verdict, reason
    except Exception as e:
        logger.warning("AI niche verdict failed (%s), falling back to borderline", e)
        return (
            "borderline",
            "Evaluator unavailable (heuristic fallback); advisory review, "
            "publish allowed",
        )


def evaluate_content_level(
    context_text: str,
    niche: str | None = None,
    prompt_override: str | None = None,
) -> tuple[str, str]:
    """Evaluate content relevance on a 3-level scale.

    Returns (level, reason) where level is one of:
    - "match": clearly relevant, auto-generate metadata.
    - "borderline": related context (concert/music/crowd) or weak signals.
      Still generate metadata and allow publish, with a light warning.
    - "mismatch": clearly unrelated (news/food/gaming/cars/animals/
      talking-only/shopping/lifestyle with no music-dance context).
      Strong warning, but metadata is STILL generated (advisory only).

    The matcher is a recommendation/filter and must never blank metadata.
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
        or "content relevance" in prompt_text
        or is_dance_channel
    )

    if not has_strict_match:
        return "match", "Channel does not enforce strict content match"

    ai_enabled = (
        bool(settings.ai_enabled)
        or os.getenv("AI_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    api_key = (settings.ai_api_key or os.getenv("AI_API_KEY", "")).strip()

    if not is_dance_channel:
        # Non-dance channel (e.g. cute pets): the dance keyword lists do not
        # apply. Judge against the channel's own niche via AI; without AI,
        # stay advisory (borderline) instead of guessing.
        if not ai_enabled or not api_key:
            return (
                "borderline",
                "Non-dance channel without AI evaluator; advisory review, "
                "publish allowed",
            )
        return _ai_verdict_niche(
            context_text=context_text,
            niche=niche or "",
            model=settings.ai_model or os.getenv("AI_MODEL", "youtube-douyin"),
            base_url=(
                settings.ai_base_url
                or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
            ).rstrip("/"),
            api_key=api_key,
        )

    has_dance_kw = _has_any(context_lower, DANCE_POSITIVE_KEYWORDS)
    has_music_kw = _has_any(context_lower, MUSIC_CONTEXT_KEYWORDS)
    has_disqualify_kw = _has_any(
        context_lower, NON_DANCE_DISQUALIFY_KEYWORDS
    ) or _has_any(context_lower, CLEAR_MISMATCH_KEYWORDS)

    # Strong positive: explicit dance context.
    if has_dance_kw:
        return "match", "Matched dance keywords"

    # Clear mismatch only when unrelated topics appear with no
    # dance AND no music/concert context at all.
    if has_disqualify_kw and not has_music_kw:
        return (
            "mismatch",
            "CONTENT_MISMATCH: Contains non-dance/non-music keywords "
            "without dance or music context",
        )

    if not ai_enabled or not api_key:
        if has_music_kw:
            return (
                "borderline",
                "Music/concert context without explicit dance keywords "
                "(heuristic); advisory review",
            )
        return (
            "borderline",
            "No strong dance/music signals (heuristic fallback); "
            "advisory review, publish allowed",
        )

    base_url = (
        settings.ai_base_url
        or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
    ).rstrip("/")
    model = settings.ai_model or os.getenv("AI_MODEL", "youtube-douyin")

    system_prompt = (
        "You are a content relevance evaluator for a YouTube dance channel "
        "(JoyBeat: dance, choreography, street dance, K-pop/pop performance).\n"
        "Decide a verdict for the Douyin video context:\n"
        '- "match": dance performance, choreography, dance practice, dance '
        "challenge, dancers, artist dancing on stage, concert with visible "
        "dance/performance, crowd/audience dancing, music performance with "
        "strong dance context, rehearsal, street dance, K-pop/pop "
        "performance involving dance. The caption does NOT need to say the "
        'word "dance" — judge the semantic context (caption + hashtags + '
        "artist/event signals).\n"
        '- "borderline": music/concert/show context without clear dance '
        "evidence, but plausibly related. Still publishable.\n"
        '- "mismatch": ONLY for clearly unrelated content with no '
        "music/dance context: news, food, gaming, cars, animals, "
        "talking-only, shopping, random lifestyle.\n\n"
        "Return ONLY a JSON object:\n"
        '{"verdict": "match|borderline|mismatch", "reason": "explanation in English"}'
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
        # Accept new 3-way shape and legacy boolean shape.
        verdict = str(
            data.get("verdict")
            or data.get("match_level")
            or ("match" if data.get("match") is True else "")
            or ("mismatch" if data.get("match") is False else "")
            or "borderline"
        ).lower()
        if verdict not in MATCH_LEVELS:
            verdict = "borderline"
        reason = str(data.get("reason", "Evaluated by AI"))
        if verdict == "mismatch" and not reason.startswith("CONTENT_MISMATCH"):
            reason = f"CONTENT_MISMATCH: {reason}"
        return verdict, reason
    except Exception as e:
        logger.warning("AI content match evaluation failed (%s), falling back to heuristic", e)
        if has_music_kw:
            return (
                "borderline",
                "Music/concert context (heuristic fallback); advisory review",
            )
        return (
            "borderline",
            "No dance keywords detected (heuristic fallback); "
            "advisory review, publish allowed",
        )


def evaluate_content_match(
    context_text: str,
    niche: str | None = None,
    prompt_override: str | None = None,
) -> tuple[bool, str]:
    """Backward-compatible boolean wrapper around evaluate_content_level.

    True for "match" and "borderline" (both publishable), False only for
    a clear "mismatch". Used by the auto scheduler: mismatch videos are
    skipped, everything else is eligible.
    """
    level, reason = evaluate_content_level(
        context_text=context_text,
        niche=niche,
        prompt_override=prompt_override,
    )
    return (level != "mismatch"), reason


def generate_metadata_structured(
    context_text: str,
    pipeline: Pipeline | None = None,
    destination: Destination | None = None,
) -> dict[str, Any] | None:
    """Generate structured YouTube metadata using AI.

    Returns dict with keys:
    - title: str (never blank when generation succeeds)
    - description: str (clean caption text without trailing hashtags)
    - hashtags: list[str] (exactly 5 clean hashtags)
    - final_description: str (description + \\n\\n + hashtags)
    - content_match: bool (False only on clear mismatch; advisory)
    - content_match_reason: str
    - match_level: "match" | "borderline" | "mismatch" (advisory only;
      metadata is always generated so Generate/Publish keeps working)
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

    # Pre-evaluate content relevance (advisory only). The verdict guides the
    # generation prompt but NEVER blanks the metadata: the matcher is a
    # recommendation/filter, and the Generate/ Publish flow must keep working.
    niche_val = (
        (destination.metadata_profile if destination else None)
        or (pipeline.niche if pipeline else "")
    )
    prompt_val = (
        (destination.prompt_override if destination else None)
        or ""
    )
    pre_level, match_reason = evaluate_content_level(
        context_text=context_text,
        niche=niche_val,
        prompt_override=prompt_val,
    )

    user_content = (
        "ORIGINAL DOUYIN CONTEXT/SHARE TEXT:\n\n"
        + context_text
        + profile_section
        + (
            f"\n\nCONTENT RELEVANCE (advisory verdict={pre_level}): "
            f"{match_reason}. Always generate YouTube title, description, "
            "and hashtags in valid JSON format regardless of verdict, "
            'and include "match_level" (match|borderline|mismatch) with a '
            "short reason."
            if (niche_val or prompt_val)
            else ""
        )
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

        # Advisory verdict from the generator itself (new 3-way shape or
        # legacy mismatch shape). Never blank the fields: fall back to the
        # pre-evaluation level and keep whatever title/description the AI
        # provided (or draft from context below).
        ai_verdict = str(
            data.get("match_level")
            or data.get("verdict")
            or ""
        ).lower()
        if ai_verdict not in MATCH_LEVELS:
            ai_verdict = ""
        legacy_mismatch = (
            data.get("status") == "CONTENT_MISMATCH"
            or data.get("content_match") is False
        )
        if legacy_mismatch and not ai_verdict:
            ai_verdict = "mismatch"
        ai_reason = str(data.get("reason") or "").strip()

        # Final level: the stricter of pre-evaluation and AI verdict only
        # when the AI explicitly flags mismatch; otherwise prefer the more
        # permissive signal so borderline content keeps flowing.
        order = {"match": 0, "borderline": 1, "mismatch": 2}
        if ai_verdict == "mismatch":
            final_level = "mismatch"
            final_reason = (
                f"CONTENT_MISMATCH: {ai_reason or 'Flagged by generator'}"
                if not (ai_reason.startswith("CONTENT_MISMATCH"))
                else ai_reason
            )
        elif ai_verdict and order[ai_verdict] < order.get(pre_level, 1):
            final_level = ai_verdict
            final_reason = ai_reason or match_reason
        else:
            final_level = pre_level if pre_level in MATCH_LEVELS else "borderline"
            final_reason = match_reason

        title = str(
            data.get("title")
            or ""
        ).strip()

        if not title:
            # Legacy mismatch-only shape (no usable fields): draft a minimal
            # title from the original context instead of returning blanks,
            # so Generate/Publish keeps working. User can edit before posting.
            if legacy_mismatch or ai_verdict == "mismatch":
                logger.warning(
                    "AI returned mismatch without fields; drafting from context"
                )
                draft = re.sub(r"https?://[^\s]+", "", context_text).strip()
                draft = re.sub(r"\s+", " ", draft)[:80] or "Douyin Video"
                title = draft
                if not str(data.get("description") or "").strip():
                    data["description"] = draft
            else:
                raise RuntimeError(
                    "AI returned empty title"
                )

        if "CONTENT_MISMATCH" in title.upper():
            # AI leaked its verdict into the title: keep the verdict, but
            # still draft a usable title from context (never blank).
            logger.warning("AI title indicates CONTENT_MISMATCH: %s", title)
            final_reason = title
            final_level = "mismatch"
            draft = re.sub(r"https?://[^\s]+", "", context_text).strip()
            draft = re.sub(r"\s+", " ", draft)[:80] or "Douyin Video"
            title = re.sub(
                r"(?i)content_mismatch[:\s-]*", "", draft
            ).strip() or "Douyin Video"

        title = title[:100]

        description = str(
            data.get("description")
            or ""
        ).strip()

        # The model often appends hashtags inside the description even when
        # told not to. Strip any trailing hashtag block so final_description
        # (= description + hashtags) contains exactly 5 tags, otherwise the
        # worker hashtag validation fails and forces wasteful AI retries.
        description = re.sub(r"(\s*#\w+\s*)+$", "", description).strip()

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
            "content_match": final_level != "mismatch",
            "content_match_reason": final_reason,
            "match_level": final_level,
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

    Returns (title, final_description_with_hashtags).

    The content verdict is advisory only: metadata is returned whenever a
    title was generated, even for borderline/mismatch levels.
    """
    res = generate_metadata_structured(
        context_text,
        pipeline=pipeline,
        destination=destination,
    )
    if not res or not res.get("title"):
        return None
    return (res["title"], res["final_description"])
