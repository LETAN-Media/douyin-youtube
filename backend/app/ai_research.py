"""AI layer for trend research (ToolNet OpenAI-compatible chat).

Runs ONLY after deterministic scoring. Produces validated structured JSON.
Never invents metrics: every claim must reference evidence video IDs.
Falls back to a deterministic-only summary when AI is disabled/fails.
"""
from __future__ import annotations

import json
import logging
import os
import re
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
    model = (
        getattr(settings, "ai_research_model", "")
        or os.getenv("AI_RESEARCH_MODEL", "")
        or settings.ai_model
        or os.getenv("AI_MODEL", "youtube-douyin")
    )
    return enabled, api_key, base_url, model


def _chat(
    system: str,
    user: str,
    max_tokens: int = 1500,
    temperature: float = 0.2,
) -> str | None:
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
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        # The gateway may return the OpenAI envelope (sometimes with
        # trailing junk that breaks resp.json()) or raw text; never assume
        # a clean JSON body here.
        body = resp.text or ""
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if content:
                    return content
        except (json.JSONDecodeError, ValueError):
            pass
        # Fall back to the message content inside a (possibly trailed)
        # envelope before treating the whole body as model text.
        content = _envelope_content(body)
        if content:
            return content
        return body.strip() or None
    except Exception as exc:
        logger.warning("AI research call failed: %s", exc)
        return None


def _envelope_content(body: str) -> str | None:
    """Extract choices[0].message.content from a possibly-trailing envelope."""
    try:
        match = re.search(r'"content"\s*:\s*"', body)
        if not match:
            return None
        value, _ = json.JSONDecoder().raw_decode(body, match.end() - 1)
        return value if isinstance(value, str) and value.strip() else None
    except (json.JSONDecodeError, ValueError):
        return None


def _balanced_spans(text: str, open_ch: str, close_ch: str) -> list[str]:
    """Yield top-level balanced spans via bracket matching (string-aware)."""
    spans: list[str] = []
    depth = 0
    start: int | None = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch:
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    spans.append(text[start : i + 1])
                    start = None
    return spans


def _balanced_objects(text: str) -> list[str]:
    return _balanced_spans(text, "{", "}")


def _schema_score(data: dict) -> int:
    return sum(1 for k in RESEARCH_SCHEMA_KEYS if k in data)


def _extract_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    # Prefer fenced code blocks (may be several); schema-matching first.
    if "```" in cleaned:
        blocks = re.findall(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        best: dict[str, Any] | None = None
        best_score = 0
        for b in blocks:
            try:
                parsed = json.loads(b.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                score = _schema_score(parsed)
                if score > best_score:
                    best, best_score = parsed, score
        if best is not None and best_score > 0:
            return best
        for b in blocks:
            try:
                parsed = json.loads(b.strip())
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                continue
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to the balanced object with the most schema keys (models
    # often emit prose + JSON; the API envelope scores 0 and is skipped).
    best = None
    best_score = 0
    fallback = None
    for span in _balanced_objects(cleaned):
        try:
            parsed = json.loads(span)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            if fallback is None:
                fallback = parsed
            score = _schema_score(parsed)
            if score > best_score:
                best, best_score = parsed, score
    if best is not None and best_score > 0:
        return best
    return None


def _extract_json_list(text: str | None, item_key: str) -> list[Any]:
    """Best balanced [...] whose items carry item_key (title/tag)."""
    if not text:
        return []
    cleaned = text.strip()
    if "```" in cleaned:
        for b in re.findall(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL):
            try:
                parsed = json.loads(b.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, list) and parsed:
                return parsed
            if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                return parsed["items"]
    best: list[Any] = []
    best_score = -1
    for span in _balanced_spans(cleaned, "[", "]"):
        try:
            parsed = json.loads(span)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, list) or not parsed:
            continue
        score = sum(
            1 for it in parsed
            if isinstance(it, dict) and it.get(item_key)
        )
        if score > best_score:
            best, best_score = parsed, score
    if best_score > 0:
        return best
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return []


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
    for v in (ranked_videos or [])[: min(max_videos, 12)]:
        compact.append(
            {
                "id": v.get("video_id"),
                "title": (v.get("title") or "")[:80],
                "views": v.get("views"),
                "score": v.get("trend_score"),
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
        "START your response with the character { and END with }. No prose "
        "before or after the JSON. JSON keys: channel_niche, trend_summary "
        "(2 sentences), hot_topics[{topic, score, why, video_ids[]}] "
        "(max 5), keywords[] (max 12), hashtags[{tag, why}] (max 8), "
        "title_ideas[{title, angle, hook, primary_keyword, "
        "secondary_keywords[], channel_fit_score, trend_relevance_score, "
        "reason}] (5 items, no misleading clickbait), hooks[] (max 5), "
        "channel_fit_analysis[{topic, fit_score, note}] (max 5), "
        "avoid_topics[] (max 5), evidence[{video_id, note}] (max 8)."
    )
    user = json.dumps(
        {
            "niche_kw": (niche.get("keywords") or [])[:10],
            "videos": compact,
            "tags": [h.get("tag") for h in (hashtag_stats or [])[:8]],
        },
        ensure_ascii=False,
    )
    raw = _chat(system, user)
    data = _extract_json(raw)
    if data is None and raw:
        # One strict retry: models sometimes answer in prose first.
        logger.info("ai research retrying with JSON-only nudge (len=%d)", len(raw))
        raw = _chat(
            system + " Reply with ONLY the JSON object, no prose before or after.",
            user,
        )
        data = _extract_json(raw)
    if data is None:
        logger.info("ai research fallback (no parseable JSON)")
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
        "clickbait; each must fit the channel niche. START your response "
        "with [ and END with ]. No prose before or after the JSON array. "
        "Array of objects with keys: title, angle, hook, primary_keyword, "
        "secondary_keywords[], channel_fit_score (0-100), "
        "trend_relevance_score (0-100), reason."
    )
    user = json.dumps({"niche": niche, "hot_topics": hot_topics[:10]}, ensure_ascii=False)
    raw = _chat(system, user)
    items = _extract_json_list(raw, "title")
    if not items:
        data = _extract_json(raw)
        items = data.get("items") if isinstance(data, dict) else None
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
        "tags). START your response with [ and END with ]. No prose before "
        "or after the JSON array of {tag, why, channel_fit_score}."
    )
    user = json.dumps(
        {"niche": niche, "stats": hashtag_stats[:25], "language": language, "count": count},
        ensure_ascii=False,
    )
    raw = _chat(system, user)
    items = _extract_json_list(raw, "tag")
    if not items:
        data = _extract_json(raw)
        items = data.get("items") if isinstance(data, dict) else None
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
