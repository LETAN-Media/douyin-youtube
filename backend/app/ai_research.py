"""AI layer for trend research (ToolNet OpenAI-compatible chat).

Runs ONLY after deterministic scoring. Produces validated structured JSON.
Never invents metrics: every claim must reference evidence video IDs.
Falls back to a deterministic-only summary when AI is disabled/fails.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("douyin-youtube-ai-research")


def _ai_conf() -> tuple[bool, str, str, str]:
    enabled = bool(settings.ai_enabled) or os.getenv("AI_ENABLED", "false").lower() in (
        "true", "1", "yes",
    )
    api_key = (settings.ai_api_key or os.getenv("AI_API_KEY", "")).strip()
    base_url = (
        settings.ai_base_url or os.getenv("AI_BASE_URL", "https://api.toolnet.tech/v1")
    ).rstrip("/")
    model = settings.ai_model or os.getenv("AI_MODEL", "youtube-douyin")
    return enabled, api_key, base_url, model


def _chat(system: str, user: str, max_tokens: int = 1500) -> str | None:
    enabled, api_key, base_url, model = _ai_conf()
    if not enabled or not api_key:
        return None
    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.4,
                "max_tokens": max_tokens,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    except Exception as exc:
        logger.warning("AI research call failed: %s", exc)
        return None


def _extract_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re_sub_fence(cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def re_sub_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


RESEARCH_SCHEMA_KEYS = {
    "channel_niche", "trend_summary", "hot_topics", "keywords", "hashtags",
    "title_ideas", "hooks", "channel_fit_analysis", "avoid_topics", "evidence",
}


def validate_research_output(data: Any) -> tuple[bool, dict[str, Any], str | None]:
    """Validate AI JSON; returns (ok, normalized, error)."""
    if not isinstance(data, dict):
        return False, {}, "top-level JSON must be an object"
    norm: dict[str, Any] = {
        "channel_niche": str(data.get("channel_niche") or ""),
        "trend_summary": str(data.get("trend_summary") or ""),
        "hot_topics": list(data.get("hot_topics") or []),
        "keywords": [str(k) for k in (data.get("keywords") or [])][:30],
        "hashtags": [str(h) for h in (data.get("hashtags") or [])][:30],
        "title_ideas": list(data.get("title_ideas") or []),
        "hooks": [str(h) for h in (data.get("hooks") or [])][:20],
        "channel_fit_analysis": list(data.get("channel_fit_analysis") or []),
        "avoid_topics": [str(a) for a in (data.get("avoid_topics") or [])][:20],
        "evidence": list(data.get("evidence") or []),
    }
    # Validate title ideas shape (non-fatal: keep raw, flag error)
    for t in norm["title_ideas"]:
        if not isinstance(t, dict) or not t.get("title"):
            return False, norm, "each title_idea must have a title"
    return True, norm, None


def analyze_trends(
    niche: dict[str, Any],
    ranked_videos: list[dict[str, Any]],
    hashtag_stats: list[dict[str, Any]],
    language: str,
    max_videos: int = 20,
) -> dict[str, Any]:
    """Deterministic-first AI analysis with validated JSON + fallback."""
    compact = []
    for v in (ranked_videos or [])[:max_videos]:
        compact.append(
            {
                "id": v.get("video_id"),
                "title": (v.get("title") or "")[:120],
                "channel": v.get("channel_title"),
                "views": v.get("views"),
                "vph": v.get("views_per_hour"),
                "age_h": v.get("age_hours"),
                "score": v.get("trend_score"),
                "tags": (v.get("hashtags") or [])[:8],
            }
        )
    lang_name = {"en": "English", "vi": "Vietnamese", "zh": "Chinese"}.get(
        language, "the channel's own language (infer from titles)"
    )
    system = (
        "You are a YouTube trend analyst. You receive PRE-SCORED trend data "
        "(deterministic 0-100 scores with evidence). Never invent metrics, "
        "view counts, or scores. Every claim must cite video ids from the "
        f"evidence set. Output language: {lang_name}. "
        "Return ONLY valid JSON with keys: channel_niche, trend_summary, "
        "hot_topics[{topic, score, why, video_ids[]}], keywords[], "
        "hashtags[{tag, why}], title_ideas[{title, angle, hook, "
        "primary_keyword, secondary_keywords[], channel_fit_score, "
        "trend_relevance_score, reason}] (5-10 items, no misleading "
        "clickbait), hooks[], channel_fit_analysis[{topic, fit_score, "
        "note}], avoid_topics[], evidence[{video_id, note}]."
    )
    user = json.dumps(
        {
            "niche": niche,
            "videos": compact,
            "hashtags": hashtag_stats[:15],
        },
        ensure_ascii=False,
    )
    raw = _chat(system, user)
    data = _extract_json(raw)
    if data is None:
        return {
            "fallback": True,
            "channel_niche": ", ".join((niche.get("keywords") or [])[:8]),
            "trend_summary": (
                "AI unavailable — deterministic ranking only. "
                f"Top: {((ranked_videos or [{}])[0].get('title') or 'n/a')}"
            ),
            "hot_topics": [],
            "keywords": list(niche.get("keywords") or [])[:15],
            "hashtags": [
                {"tag": h.get("tag"), "why": "recurring in trending videos"}
                for h in (hashtag_stats or [])[:10]
            ],
            "title_ideas": [],
            "hooks": [],
            "channel_fit_analysis": [],
            "avoid_topics": [],
            "evidence": [
                {"video_id": v.get("video_id"), "note": f"score {v.get('trend_score')}"}
                for v in (ranked_videos or [])[:10]
            ],
        }
    ok, norm, err = validate_research_output(data)
    norm["fallback"] = False
    if not ok:
        norm["validation_warning"] = err
    return norm


def generate_titles(
    niche: dict[str, Any],
    hot_topics: list[dict[str, Any]],
    language: str,
    count: int = 8,
) -> list[dict[str, Any]]:
    lang_name = {"en": "English", "vi": "Vietnamese", "zh": "Chinese"}.get(
        language, "the channel's own language"
    )
    system = (
        f"Write {count} YouTube Shorts titles in {lang_name}. No misleading "
        "clickbait; each must fit the channel niche. Return ONLY a JSON "
        "array of objects with keys: title, angle, hook, primary_keyword, "
        "secondary_keywords[], channel_fit_score (0-100), "
        "trend_relevance_score (0-100), reason."
    )
    user = json.dumps({"niche": niche, "hot_topics": hot_topics[:10]}, ensure_ascii=False)
    raw = _chat(system, user)
    data = _extract_json(raw)
    items = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    if not isinstance(items, list):
        return []
    out = []
    for t in items[:count]:
        if isinstance(t, dict) and t.get("title"):
            out.append(
                {
                    "title": str(t["title"])[:100],
                    "angle": str(t.get("angle") or ""),
                    "hook": str(t.get("hook") or ""),
                    "primary_keyword": str(t.get("primary_keyword") or ""),
                    "secondary_keywords": list(t.get("secondary_keywords") or [])[:5],
                    "channel_fit_score": int(t.get("channel_fit_score") or 0),
                    "trend_relevance_score": int(t.get("trend_relevance_score") or 0),
                    "reason": str(t.get("reason") or ""),
                }
            )
    return out


def generate_hashtags(
    niche: dict[str, Any],
    hashtag_stats: list[dict[str, Any]],
    language: str,
    count: int = 15,
) -> list[dict[str, Any]]:
    """AI semantic clustering over evidence-backed hashtag stats."""
    system = (
        "Cluster the given hashtag statistics into a final suggestion list. "
        "Only suggest tags grounded in the evidence stats (no invented viral "
        "tags). Return ONLY a JSON array of {tag, why, channel_fit_score}."
    )
    user = json.dumps(
        {"niche": niche, "stats": hashtag_stats[:25], "language": language, "count": count},
        ensure_ascii=False,
    )
    raw = _chat(system, user)
    data = _extract_json(raw)
    items = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    if not isinstance(items, list):
        # Deterministic fallback: top evidence stats as-is.
        return [
            {
                "tag": s.get("tag"),
                "why": f"frequency {s.get('frequency')}, recent {s.get('recent_frequency')}",
                "channel_fit_score": int(s.get("channel_fit_score") or 0),
            }
            for s in (hashtag_stats or [])[:count]
        ]
    return [
        {
            "tag": str(t.get("tag") or ""),
            "why": str(t.get("why") or ""),
            "channel_fit_score": int(t.get("channel_fit_score") or 0),
        }
        for t in items[:count]
        if isinstance(t, dict) and t.get("tag")
    ]
