"""Channel Content DNA: per-destination identity + locked core tags.

Rules enforced here:
- DNA is per-destination; never shared across channels.
- locked_hashtags / locked_tags are admin-owned. AI must preserve them
  verbatim (no delete/replace/translate/rewrite). Only PROPOSALS via
  suggestions table; admin confirms.
- final_hashtags = locked + dynamic (deduplicated).
- final_tags = locked + dynamic (deduplicated, normalized).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models import (
    Destination,
    Publication,
    YouTubeChannelDNA,
    YouTubeContentFingerprint,
    YouTubeDNASuggestion,
    YouTubePerformanceSnapshot,
)

logger = logging.getLogger("douyin-youtube-dna")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


FINGERPRINT_KEYS = {
    "topic", "subtopics", "characters", "setting", "story_angle",
    "emotion", "audience_intent", "primary_keywords", "language",
}

PERF_CHECKPOINTS = ("1h", "6h", "24h", "72h", "7d")


# ---------------------------------------------------------------------------
# DNA CRUD
# ---------------------------------------------------------------------------

def get_dna(db, destination_id: str) -> YouTubeChannelDNA | None:
    return db.execute(
        select(YouTubeChannelDNA)
        .where(YouTubeChannelDNA.destination_id == destination_id)
        .limit(1)
    ).scalar_one_or_none()


def get_or_create_dna(db, destination: Destination) -> YouTubeChannelDNA:
    dna = get_dna(db, destination.id)
    if dna is not None:
        return dna
    lang = (destination.metadata_language or "en").lower()
    dna = YouTubeChannelDNA(
        destination_id=destination.id,
        primary_niche=destination.metadata_profile or destination.name,
        secondary_topics=[],
        audience_profile="",
        target_language=lang if len(lang) <= 10 else "en",
        target_regions=[(getattr(destination, "research_region", None) or "VN")],
        content_style="",
        title_style="",
        title_patterns=[],
        core_keywords=list(destination.fixed_hashtags or [])[:10],
        locked_hashtags=list(destination.fixed_hashtags or [])[:5],
        locked_tags=[],
        winning_topics=[],
        weak_topics=[],
        avoid_topics=[],
    )
    db.add(dna)
    db.flush()
    return dna


def normalize_tag(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_hashtag(value: str) -> str:
    tag = (value or "").strip()
    if not tag:
        return ""
    if not tag.startswith("#"):
        tag = "#" + tag
    return "#" + re.sub(r"\s+", "", tag[1:].lower())


def update_dna(
    db, dna: YouTubeChannelDNA, payload: dict[str, Any], *, admin_confirmed: bool = True
) -> YouTubeChannelDNA:
    """Apply admin edits. Locked fields change ONLY via explicit admin save."""
    if not admin_confirmed:
        raise ValueError("DNA locked fields require admin confirmation")
    for field in (
        "primary_niche", "audience_profile", "target_language",
        "content_style", "title_style",
    ):
        if field in payload and payload[field] is not None:
            setattr(dna, field, str(payload[field])[:2000])
    for field in (
        "secondary_topics", "target_regions", "title_patterns",
        "core_keywords", "winning_topics", "weak_topics", "avoid_topics",
    ):
        if field in payload and payload[field] is not None:
            setattr(dna, field, list(payload[field])[:50])
    if "locked_hashtags" in payload and payload["locked_hashtags"] is not None:
        cleaned = [normalize_hashtag(h) for h in payload["locked_hashtags"]]
        dna.locked_hashtags = [h for h in cleaned if h][:10]
    if "locked_tags" in payload and payload["locked_tags"] is not None:
        cleaned = [normalize_tag(t) for t in payload["locked_tags"]]
        dna.locked_tags = [t for t in cleaned if t][:20]
    db.commit()
    db.refresh(dna)
    return dna


def dna_to_dict(dna: YouTubeChannelDNA | None) -> dict[str, Any] | None:
    if dna is None:
        return None
    return {
        "primary_niche": dna.primary_niche,
        "secondary_topics": dna.secondary_topics or [],
        "audience_profile": dna.audience_profile,
        "target_language": dna.target_language,
        "target_regions": dna.target_regions or [],
        "content_style": dna.content_style,
        "title_style": dna.title_style,
        "title_patterns": dna.title_patterns or [],
        "core_keywords": dna.core_keywords or [],
        "locked_hashtags": dna.locked_hashtags or [],
        "locked_tags": dna.locked_tags or [],
        "winning_topics": dna.winning_topics or [],
        "weak_topics": dna.weak_topics or [],
        "avoid_topics": dna.avoid_topics or [],
        "updated_at": dna.updated_at.isoformat() if dna.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Content fingerprint (pre-title understanding step)
# ---------------------------------------------------------------------------

def build_fingerprint_heuristic(
    source_title: str | None,
    source_description: str | None,
    language: str = "auto",
) -> dict[str, Any]:
    from app.trend_research import detect_language, tokenize

    text = f"{source_title or ''}\n{source_description or ''}"
    tokens = tokenize(text)
    return {
        "topic": (source_title or "")[:200],
        "subtopics": tokens[:10],
        "characters": [],
        "setting": "",
        "story_angle": "",
        "emotion": [],
        "audience_intent": "",
        "primary_keywords": tokens[:12],
        "language": language if language != "auto" else detect_language(text),
    }


def generate_fingerprint(
    source_title: str | None,
    source_description: str | None,
    language: str = "auto",
) -> dict[str, Any]:
    """AI fingerprint with heuristic fallback. Never blocks metadata."""
    heuristic = build_fingerprint_heuristic(source_title, source_description, language)
    try:
        from app.ai_research import _chat, _extract_json
    except ImportError:
        return heuristic
    import json as _json

    system = (
        "Analyze the video content. START with { and END with }. No prose. "
        "JSON keys: topic, subtopics[], characters[], setting, story_angle, "
        "emotion[], audience_intent, primary_keywords[], language. "
        "Do NOT write any title."
    )
    raw = _chat(
        system,
        _json.dumps(
            {"title": source_title or "", "caption": (source_description or "")[:1500]},
            ensure_ascii=False,
        ),
        max_tokens=600,
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return heuristic
    out = dict(heuristic)
    for k in FINGERPRINT_KEYS:
        if data.get(k) not in (None, "", []):
            out[k] = data[k]
    return out


def save_fingerprint(
    db, publication_id: str, destination_id: str, fingerprint: dict[str, Any]
) -> None:
    row = db.execute(
        select(YouTubeContentFingerprint)
        .where(YouTubeContentFingerprint.publication_id == publication_id)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        row = YouTubeContentFingerprint(
            publication_id=publication_id, destination_id=destination_id
        )
        db.add(row)
    row.fingerprint = fingerprint
    db.flush()


# ---------------------------------------------------------------------------
# Locked enforcement (final merge)
# ---------------------------------------------------------------------------

def merge_final_hashtags(
    locked: list[str] | None, dynamic: list[str] | None
) -> tuple[list[str], list[str], list[str]]:
    """Returns (final, kept_locked, dynamic_added). Locked never altered."""
    kept = []
    for h in locked or []:
        n = normalize_hashtag(h)
        if n and n not in kept:
            kept.append(n)
    added = []
    for h in dynamic or []:
        n = normalize_hashtag(h)
        if n and n not in kept and n not in added:
            added.append(n)
    return kept + added, kept, added


def merge_final_tags(
    locked: list[str] | None, dynamic: list[str] | None
) -> tuple[list[str], list[str], list[str]]:
    kept = []
    for t in locked or []:
        n = normalize_tag(t)
        if n and n not in kept:
            kept.append(n)
    added = []
    for t in dynamic or []:
        n = normalize_tag(t)
        if n and n not in kept and n not in added:
            added.append(n)
    return kept + added, kept, added


# ---------------------------------------------------------------------------
# Title engine (5 candidates, DNA-grounded)
# ---------------------------------------------------------------------------

def generate_title_candidates(
    fingerprint: dict[str, Any],
    dna: dict[str, Any] | None,
    trend_context: list[dict[str, Any]] | None = None,
    count: int = 5,
) -> list[dict[str, Any]]:
    """Deterministic-first titles; AI refines when available."""
    dna = dna or {}
    lang = dna.get("target_language") or fingerprint.get("language") or "auto"
    topic = fingerprint.get("topic") or ""
    keywords = list(fingerprint.get("primary_keywords") or [])[:5]
    patterns = list(dna.get("title_patterns") or [])
    base = []
    for i in range(count):
        title = topic[:90] if topic else " ".join(keywords[:6])[:90]
        if patterns and i < len(patterns):
            try:
                title = patterns[i].format(topic=topic[:60], keyword=(keywords[0] if keywords else ""))[:100]
            except (IndexError, KeyError, ValueError):
                pass
        base.append(
            {
                "title": title,
                "primary_keyword": keywords[0] if keywords else "",
                "angle": ["how", "best", "story", "reaction", "showcase"][i % 5],
                "hook": (keywords[1] if len(keywords) > 1 else topic[:40]),
                "channel_fit_score": 60,
                "trend_fit_score": 50,
                "reason": "heuristic candidate from content fingerprint",
            }
        )
    try:
        from app.ai_research import _chat, _extract_json_list
    except ImportError:
        return base
    import json as _json

    lang_name = {"en": "English", "vi": "Vietnamese", "zh": "Chinese"}.get(lang, lang)
    system = (
        f"Write {count} YouTube titles in {lang_name}. Match this channel style: "
        f"{(dna.get('title_style') or '')[:300]}. No keyword stuffing, no misleading "
        "clickbait, keep titles distinct from each other. START with [ and END with ]. "
        "No prose. Array of {title, primary_keyword, angle, hook, "
        "channel_fit_score (0-100), trend_fit_score (0-100), reason}."
    )
    raw = _chat(
        system,
        _json.dumps(
            {
                "fingerprint": fingerprint,
                "dna": {k: dna.get(k) for k in (
                    "primary_niche", "audience_profile", "title_style",
                    "core_keywords", "avoid_topics",
                )},
                "trends": (trend_context or [])[:8],
            },
            ensure_ascii=False,
        ),
        max_tokens=1200,
    )
    items = _extract_json_list(raw, "title")
    if not items:
        return base
    out = []
    for t in items[:count]:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        out.append(
            {
                "title": str(t["title"])[:100],
                "primary_keyword": str(t.get("primary_keyword") or ""),
                "angle": str(t.get("angle") or ""),
                "hook": str(t.get("hook") or ""),
                "channel_fit_score": int(t.get("channel_fit_score") or 0),
                "trend_fit_score": int(t.get("trend_fit_score") or t.get("trend_relevance_score") or 0),
                "reason": str(t.get("reason") or ""),
            }
        )
    return out or base


# ---------------------------------------------------------------------------
# Learning: performance snapshots + suggestions (never auto-mutate locked)
# ---------------------------------------------------------------------------

def record_performance_snapshot(
    db,
    destination_id: str,
    video_id: str,
    checkpoint: str,
    metrics: dict[str, Any],
) -> None:
    if checkpoint not in PERF_CHECKPOINTS:
        raise ValueError(f"bad checkpoint: {checkpoint}")
    row = db.execute(
        select(YouTubePerformanceSnapshot)
        .where(YouTubePerformanceSnapshot.destination_id == destination_id)
        .where(YouTubePerformanceSnapshot.video_id == video_id)
        .where(YouTubePerformanceSnapshot.checkpoint == checkpoint)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        row = YouTubePerformanceSnapshot(
            destination_id=destination_id, video_id=video_id, checkpoint=checkpoint
        )
        db.add(row)
    row.views = int(metrics.get("views") or 0)
    row.watch_minutes = float(metrics.get("watch_minutes") or 0.0)
    row.avg_view_duration = float(metrics.get("avg_view_duration") or 0.0)
    row.likes = int(metrics.get("likes") or 0)
    row.comments = int(metrics.get("comments") or 0)
    row.subs_gained = int(metrics.get("subs_gained") or 0)
    row.traffic_source = (metrics.get("traffic_source") or "")[:60] or None
    db.flush()


def suggest_from_performance(db, destination_id: str) -> list[dict[str, Any]]:
    """Derive topic/hashtag suggestions from 7d vs 24h velocity.

    Creates pending suggestion rows (admin confirms). Returns summaries.
    """
    snaps = list(
        db.execute(
            select(YouTubePerformanceSnapshot)
            .where(YouTubePerformanceSnapshot.destination_id == destination_id)
            .where(YouTubePerformanceSnapshot.checkpoint.in_(["24h", "7d"]))
        )
        .scalars()
        .all()
    )
    by_video: dict[str, dict[str, Any]] = {}
    for s in snaps:
        by_video.setdefault(s.video_id, {})[s.checkpoint] = s
    pub_titles: dict[str, str] = {}
    pubs = db.execute(
        select(Publication)
        .where(Publication.destination_id == destination_id)
        .where(Publication.external_post_id.is_not(None))
    ).scalars().all()
    for p in pubs:
        if p.external_post_id:
            pub_titles[p.external_post_id] = p.title or ""
    made = []
    for vid, marks in by_video.items():
        d1 = marks.get("24h")
        d7 = marks.get("7d")
        if d1 is None or d7 is None or not d7.views:
            continue
        velocity_ratio = d1.views / max(1.0, float(d7.views) / 7.0)
        title = pub_titles.get(vid, "")
        if velocity_ratio >= 1.5 and title:
            exists = db.execute(
                select(YouTubeDNASuggestion)
                .where(YouTubeDNASuggestion.destination_id == destination_id)
                .where(YouTubeDNASuggestion.kind == "winning_topic")
                .where(YouTubeDNASuggestion.status == "pending")
            ).scalars().all()
            if any((e.payload or {}).get("video_id") == vid for e in exists):
                continue
            row = YouTubeDNASuggestion(
                destination_id=destination_id, kind="winning_topic",
                payload={"video_id": vid, "title": title[:200], "velocity_ratio": round(velocity_ratio, 2)},
                reason=f"24h velocity {velocity_ratio:.1f}x the 7d daily average",
            )
            db.add(row)
            made.append({"kind": "winning_topic", "video_id": vid, "title": title[:200]})
    db.commit()
    return made


def apply_suggestion(db, suggestion_id: str, destination_id: str) -> dict[str, Any]:
    """Admin-confirmed apply. The ONLY path that mutates DNA from learning."""
    sug = db.get(YouTubeDNASuggestion, suggestion_id)
    if sug is None or sug.destination_id != destination_id:
        raise LookupError("suggestion not found")
    if sug.status != "pending":
        raise ValueError(f"suggestion already {sug.status}")
    dna = get_dna(db, destination_id)
    if dna is None:
        raise LookupError("DNA not found")
    payload = sug.payload or {}
    if sug.kind == "winning_topic":
        topics = list(dna.winning_topics or [])
        label = str(payload.get("title") or payload.get("video_id") or "")[:200]
        if label and label not in topics:
            topics.append(label)
            dna.winning_topics = topics[-30:]
    elif sug.kind == "suggest_core_hashtag":
        tags = list(dna.locked_hashtags or [])
        tag = normalize_hashtag(str(payload.get("tag") or ""))
        if tag and tag not in tags:
            tags.append(tag)
            dna.locked_hashtags = tags[:10]
    elif sug.kind == "suggest_core_tag":
        tags = list(dna.locked_tags or [])
        tag = normalize_tag(str(payload.get("tag") or ""))
        if tag and tag not in tags:
            tags.append(tag)
            dna.locked_tags = tags[:20]
    else:
        raise ValueError(f"unsupported suggestion kind: {sug.kind}")
    sug.status = "applied"
    db.commit()
    return {"ok": True, "kind": sug.kind}
