"""Public trend research via YouTube Data API + deterministic scoring.

No external calls at import time. All network goes through the injected
``client`` (googleapiclient youtube v3 resource) so tests can mock it.

Trend score is deterministic (0-100) computed BEFORE any AI call:
  velocity (views/hour, log-scaled)      35 pts
  engagement (like+comment rate)          25 pts
  recency (fresher = hotter)              15 pts
  topic recurrence (keyword overlap)      15 pts
  cross-video recurrence (channel appears
    in multiple result sets)              10 pts

The LLM never invents the hot score; it only explains/clusters.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("douyin-youtube-trends")

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "video", "videos", "official", "full", "new", "best", "top", "vs",
    "của", "và", "là", "các", "những", "một", "trong", "với", "cho",
    "的", "了", "在", "是", "和", "有", "这", "个",
}

SUPPORTED_REGIONS = ("VN", "US", "TH", "JP", "KR")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def age_hours(published_at: datetime | None, now: datetime | None = None) -> float | None:
    if published_at is None:
        return None
    ref = now or utcnow()
    return max(0.0, (ref - published_at).total_seconds() / 3600.0)


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[A-Za-zÀ-ỹ\u4e00-\u9fff]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


def extract_hashtags(text: str | None) -> list[str]:
    if not text:
        return []
    tags = re.findall(r"#([\wÀ-ỹ\u4e00-\u9fff]+)", text)
    seen: list[str] = []
    for t in tags:
        tag = "#" + t.lower()
        if tag not in seen:
            seen.append(tag)
    return seen


# ---------------------------------------------------------------------------
# Data API fetchers (quota-tracked by caller)
# ---------------------------------------------------------------------------

def fetch_most_popular(
    client: Any,
    region: str,
    category_id: str | None = None,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": min(max(1, max_results), 50),
    }
    if category_id:
        kwargs["videoCategoryId"] = category_id
    resp = client.videos().list(**kwargs).execute()
    return [_normalize_video(v) for v in (resp.get("items") or [])]


def search_topic(
    client: Any,
    query: str,
    region: str | None = None,
    order: str = "viewCount",
    published_after: str | None = None,
    max_results: int = 25,
) -> list[str]:
    """Return video IDs matching a topic search."""
    kwargs: dict[str, Any] = {
        "part": "id",
        "q": query,
        "type": "video",
        "order": order,
        "maxResults": min(max(1, max_results), 50),
    }
    if region:
        kwargs["regionCode"] = region
    if published_after:
        kwargs["publishedAfter"] = published_after
    resp = client.search().list(**kwargs).execute()
    ids = []
    for item in resp.get("items") or []:
        vid = ((item.get("id") or {}).get("videoId")) if isinstance(item.get("id"), dict) else None
        if vid:
            ids.append(vid)
    return ids


def fetch_video_details(client: Any, video_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        if not chunk:
            continue
        resp = client.videos().list(
            part="snippet,statistics", id=",".join(chunk)
        ).execute()
        out.extend(_normalize_video(v) for v in (resp.get("items") or []))
    return out


def _normalize_video(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    published = parse_published_at(snippet.get("publishedAt"))
    views = parse_count(stats.get("viewCount"))
    likes = parse_count(stats.get("likeCount"))
    comments = parse_count(stats.get("commentCount"))
    title = str(snippet.get("title") or "")
    desc = str(snippet.get("description") or "")
    age = age_hours(published)
    vph = (views / age) if age and age > 0 else 0.0
    like_rate = (likes / views) if views > 0 else 0.0
    comment_rate = (comments / views) if views > 0 else 0.0
    return {
        "video_id": str(item.get("id") or ""),
        "title": title,
        "description": desc,
        "channel_id": str(snippet.get("channelId") or ""),
        "channel_title": str(snippet.get("channelTitle") or ""),
        "published_at": published.isoformat() if published else None,
        "age_hours": round(age, 1) if age is not None else None,
        "views": views,
        "likes": likes,
        "comments": comments,
        "views_per_hour": round(vph, 1),
        "like_rate": round(like_rate, 5),
        "comment_rate": round(comment_rate, 5),
        "tokens": tokenize(title + " " + desc[:500]),
        "hashtags": extract_hashtags(title + " " + desc[:1500]),
        "thumbnail": ((snippet.get("thumbnails") or {}).get("medium") or {}).get("url"),
    }


# ---------------------------------------------------------------------------
# Niche inference (no hardcoding)
# ---------------------------------------------------------------------------

def infer_niche(
    channel_title: str | None,
    channel_description: str | None,
    recent_videos: list[dict[str, Any]],
    top_videos: list[dict[str, Any]],
    metadata_profile: str | None = None,
) -> dict[str, Any]:
    """Infer niche from channel identity + own video history."""
    pool: list[dict[str, Any]] = list(top_videos or []) + list(recent_videos or [])[:50]
    counter: Counter[str] = Counter()
    for v in pool:
        weight = 2 if v in (top_videos or []) else 1
        for tok in (v.get("tokens") or [])[:20]:
            counter[tok] += weight
    keywords = [w for w, _ in counter.most_common(15)]
    tags: Counter[str] = Counter()
    for v in pool:
        for h in v.get("hashtags") or []:
            tags[h] += 1
    lang = detect_language(
        " ".join(
            [
                channel_title or "",
                channel_description or "",
                " ".join(str(v.get("title") or "") for v in pool[:10]),
            ]
        )
    )
    return {
        "keywords": keywords,
        "hashtags": [t for t, _ in tags.most_common(10)],
        "language": lang,
        "profile_hint": (metadata_profile or "")[:500],
    }


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "auto"
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    vi_marks = len(re.findall(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", text.lower()))
    total = max(1, len(text))
    if cjk / total > 0.05:
        return "zh"
    if vi_marks > 3:
        return "vi"
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    if ascii_letters / total > 0.5:
        return "en"
    return "auto"


# ---------------------------------------------------------------------------
# Deterministic trend scoring (0-100)
# ---------------------------------------------------------------------------

def _velocity_points(vph: float) -> float:
    if vph <= 0:
        return 0.0
    # log scale: 10/h -> ~8pts, 100/h -> ~16, 1k -> ~24, 10k -> ~32, 100k -> 35
    return min(35.0, 8.0 * math.log10(vph + 10.0))


def _engagement_points(like_rate: float, comment_rate: float) -> float:
    # like 3% + comment 0.3% ~= strong
    like_pts = min(17.0, (like_rate / 0.03) * 17.0)
    comment_pts = min(8.0, (comment_rate / 0.003) * 8.0)
    return max(0.0, like_pts + comment_pts)


def _recency_points(age_h: float | None) -> float:
    if age_h is None:
        return 5.0
    if age_h <= 24:
        return 15.0
    if age_h <= 72:
        return 12.0
    if age_h <= 168:
        return 9.0
    if age_h <= 720:
        return 5.0
    return 2.0


def score_video(
    video: dict[str, Any],
    niche_keywords: list[str],
    channel_counter: Counter[str] | None = None,
) -> dict[str, Any]:
    niche_set = {k.lower() for k in (niche_keywords or [])}
    tokens = {t.lower() for t in (video.get("tokens") or [])}
    topic_hits = len(niche_set & tokens) if niche_set else 0
    topic_pts = min(15.0, topic_hits * 3.0)
    cross_pts = 0.0
    if channel_counter is not None:
        ch = str(video.get("channel_id") or "")
        if ch and channel_counter.get(ch, 0) > 1:
            cross_pts = 10.0
    total = (
        _velocity_points(float(video.get("views_per_hour") or 0.0))
        + _engagement_points(
            float(video.get("like_rate") or 0.0),
            float(video.get("comment_rate") or 0.0),
        )
        + _recency_points(video.get("age_hours"))
        + topic_pts
        + cross_pts
    )
    evidence = {
        "views": video.get("views"),
        "views_per_hour": video.get("views_per_hour"),
        "like_rate": video.get("like_rate"),
        "comment_rate": video.get("comment_rate"),
        "age_hours": video.get("age_hours"),
        "topic_hits": topic_hits,
        "cross_channel": bool(cross_pts),
    }
    return {
        "trend_score": int(round(min(100.0, max(0.0, total)))),
        "evidence": evidence,
        "components": {
            "velocity": round(_velocity_points(float(video.get("views_per_hour") or 0.0)), 1),
            "engagement": round(
                _engagement_points(
                    float(video.get("like_rate") or 0.0),
                    float(video.get("comment_rate") or 0.0),
                ),
                1,
            ),
            "recency": _recency_points(video.get("age_hours")),
            "topic": topic_pts,
            "cross": cross_pts,
        },
    }


def rank_videos(
    videos: list[dict[str, Any]], niche_keywords: list[str]
) -> list[dict[str, Any]]:
    channel_counter: Counter[str] = Counter(
        str(v.get("channel_id") or "") for v in videos if v.get("channel_id")
    )
    ranked = []
    for v in videos:
        scored = score_video(v, niche_keywords, channel_counter)
        ranked.append({**v, "trend_score": scored["trend_score"], "evidence_json": scored["evidence"], "score_components": scored["components"]})
    ranked.sort(key=lambda r: r["trend_score"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Hashtag aggregation with evidence
# ---------------------------------------------------------------------------

def aggregate_hashtags(
    ranked_videos: list[dict[str, Any]],
    channel_hashtags: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    now_h = 72.0
    for v in ranked_videos:
        age = v.get("age_hours")
        recent = age is not None and age <= now_h
        for tag in v.get("hashtags") or []:
            s = stats.setdefault(
                tag,
                {
                    "tag": tag, "frequency": 0, "recent_frequency": 0,
                    "trend_score": 0, "sample_video_ids": [],
                },
            )
            s["frequency"] += 1
            if recent:
                s["recent_frequency"] += 1
            s["trend_score"] = max(int(s["trend_score"]), int(v.get("trend_score") or 0))
            if v.get("video_id") and v["video_id"] not in s["sample_video_ids"]:
                s["sample_video_ids"].append(v["video_id"])
    channel_set = {(h or "").lower() for h in (channel_hashtags or [])}
    out = []
    for s in stats.values():
        fit = 90 if s["tag"].lower() in channel_set else min(
            70, 20 + s["frequency"] * 10 + s["recent_frequency"] * 10
        )
        out.append({**s, "channel_fit_score": fit})
    out.sort(key=lambda s: (s["trend_score"], s["recent_frequency"], s["frequency"]), reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# Channel fit (own history vs trend item)
# ---------------------------------------------------------------------------

def channel_fit_score(
    trend_video: dict[str, Any],
    top_historical: list[dict[str, Any]],
    niche_keywords: list[str],
) -> dict[str, Any]:
    """0-100 fit of a trend item against OWN channel history."""
    hist_tokens: Counter[str] = Counter()
    for v in top_historical or []:
        for tok in (v.get("tokens") or v.get("title", "").lower().split())[:20]:
            tok = str(tok).lower()
            if tok and tok not in STOPWORDS and len(tok) > 2:
                hist_tokens[tok] += 1
    hist_set = set(hist_tokens)
    item_tokens = {str(t).lower() for t in (trend_video.get("tokens") or [])}
    overlap = len(hist_set & item_tokens) if hist_set else 0
    topic_pts = min(40.0, overlap * 5.0)
    niche_set = {k.lower() for k in (niche_keywords or [])}
    niche_overlap = len(niche_set & item_tokens) if niche_set else 0
    niche_pts = min(30.0, niche_overlap * 6.0)
    style_pts = 15.0 if overlap >= 2 else (8.0 if overlap == 1 else 0.0)
    lang_bonus = 15.0  # refined by AI layer per channel language
    total = min(100.0, topic_pts + niche_pts + style_pts + lang_bonus)
    warning = None
    if int(trend_video.get("trend_score") or 0) >= 70 and total < 45:
        warning = (
            "High YouTube trend but low channel fit — "
            "adapt the angle to your niche before publishing."
        )
    return {
        "channel_fit_score": int(round(total)),
        "warning": warning,
        "evidence": {
            "token_overlap": overlap,
            "niche_overlap": niche_overlap,
            "history_size": len(top_historical or []),
        },
    }
