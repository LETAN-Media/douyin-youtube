"""YouTube Analytics API client for OWNED channels.

Read-only. Never publishes, never replies, never modifies anything.
All functions take an authorised ``youtube``-style client or raw
credentials; scope required: yt-analytics.readonly.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("douyin-youtube-analytics")

RANGE_PRESETS: dict[str, int] = {
    "7d": 7,
    "28d": 28,
    "90d": 90,
    "365d": 365,
    "1y": 365,
}

CORE_METRICS = [
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
]


def resolve_range(
    range_key: str | None,
    start: str | None = None,
    end: str | None = None,
    today: date | None = None,
) -> tuple[str, str]:
    """Return (start_date, end_date) as YYYY-MM-DD strings.

    Analytics API excludes today; end defaults to yesterday.
    """
    now = today or datetime.now(timezone.utc).date()
    end_d = now - timedelta(days=1)
    if end:
        end_d = date.fromisoformat(end)
    if start:
        return date.fromisoformat(start).isoformat(), end_d.isoformat()
    days = RANGE_PRESETS.get((range_key or "28d").lower(), 28)
    return (end_d - timedelta(days=days - 1)).isoformat(), end_d.isoformat()


def build_analytics_client(credentials: Any) -> Any:
    from googleapiclient.discovery import build

    return build(
        "youtubeAnalytics",
        "v2",
        credentials=credentials,
        cache_discovery=False,
    )


def _query(
    client: Any,
    channel_id: str,
    start: str,
    end: str,
    metrics: str,
    dimensions: str = "day",
    sort: str = "day",
    filters: str | None = None,
    max_results: int = 200,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "ids": f"channel=={channel_id}",
        "startDate": start,
        "endDate": end,
        "metrics": metrics,
        "dimensions": dimensions,
        "sort": sort,
        "maxResults": max_results,
    }
    if filters:
        kwargs["filters"] = filters
    return client.reports().query(**kwargs).execute()


def fetch_daily_report(
    client: Any, channel_id: str, start: str, end: str
) -> list[dict[str, Any]]:
    """Daily rows for the channel. Pure normalization downstream."""
    resp = _query(
        client, channel_id, start, end, ",".join(CORE_METRICS), "day", "day"
    )
    return normalize_daily_rows(resp)


def normalize_daily_rows(resp: dict[str, Any]) -> list[dict[str, Any]]:
    headers = [h.get("name") for h in (resp.get("columnHeaders") or [])]
    rows = []
    for raw in resp.get("rows") or []:
        row = dict(zip(headers, raw))
        rows.append(
            {
                "date": str(row.get("day", "")),
                "views": int(row.get("views") or 0),
                "watch_minutes": float(row.get("estimatedMinutesWatched") or 0.0),
                "avg_view_duration": float(row.get("averageViewDuration") or 0.0),
                "avg_view_percentage": float(row.get("averageViewPercentage") or 0.0),
                "likes": int(row.get("likes") or 0),
                "comments": int(row.get("comments") or 0),
                "shares": int(row.get("shares") or 0),
                "subs_gained": int(row.get("subscribersGained") or 0),
                "subs_lost": int(row.get("subscribersLost") or 0),
            }
        )
    rows.sort(key=lambda r: r["date"])
    return rows


def summarize_daily(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _sum(k: str) -> float:
        return sum(float(r.get(k) or 0) for r in rows)

    views = _sum("views")
    watch_minutes = _sum("watch_minutes")
    avg_dur = (
        sum(float(r.get("avg_view_duration") or 0) * float(r.get("views") or 0) for r in rows)
        / views
        if views > 0
        else 0.0
    )
    avg_pct = (
        sum(float(r.get("avg_view_percentage") or 0) * float(r.get("views") or 0) for r in rows)
        / views
        if views > 0
        else 0.0
    )
    return {
        "views": int(views),
        "watch_minutes": watch_minutes,
        "watch_hours": round(watch_minutes / 60.0, 1),
        "avg_view_duration": round(avg_dur, 1),
        "avg_view_percentage": round(avg_pct, 1),
        "likes": int(_sum("likes")),
        "comments": int(_sum("comments")),
        "shares": int(_sum("shares")),
        "subs_gained": int(_sum("subs_gained")),
        "subs_lost": int(_sum("subs_lost")),
        "subs_net": int(_sum("subs_gained") - _sum("subs_lost")),
        "days": len(rows),
    }


def fetch_top_videos(
    client: Any,
    channel_id: str,
    start: str,
    end: str,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Top videos by views (dimension=video, sort=-views)."""
    resp = _query(
        client,
        channel_id,
        start,
        end,
        "views,estimatedMinutesWatched,averageViewDuration,likes,comments,subscribersGained",
        "video",
        "-views",
        max_results=min(max(1, max_results), 50),
    )
    headers = [h.get("name") for h in (resp.get("columnHeaders") or [])]
    out = []
    for raw in resp.get("rows") or []:
        row = dict(zip(headers, raw))
        out.append(
            {
                "video_id": str(row.get("video") or ""),
                "views": int(row.get("views") or 0),
                "watch_minutes": float(row.get("estimatedMinutesWatched") or 0.0),
                "avg_view_duration": float(row.get("averageViewDuration") or 0.0),
                "likes": int(row.get("likes") or 0),
                "comments": int(row.get("comments") or 0),
                "subs_gained": int(row.get("subscribersGained") or 0),
            }
        )
    return out


def fetch_traffic_sources(
    client: Any, channel_id: str, start: str, end: str
) -> list[dict[str, Any]]:
    """Views by traffic source type (insightTrafficSourceType)."""
    resp = _query(
        client,
        channel_id,
        start,
        end,
        "views,estimatedMinutesWatched",
        "insightTrafficSourceType",
        "-views",
    )
    headers = [h.get("name") for h in (resp.get("columnHeaders") or [])]
    out = []
    for raw in resp.get("rows") or []:
        row = dict(zip(headers, raw))
        out.append(
            {
                "source": str(row.get("insightTrafficSourceType") or "UNKNOWN"),
                "views": int(row.get("views") or 0),
                "watch_minutes": float(row.get("estimatedMinutesWatched") or 0.0),
            }
        )
    return out


def fetch_search_terms(
    client: Any,
    channel_id: str,
    start: str,
    end: str,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    """Top REAL YouTube Search terms driving this channel.

    Uses insightTrafficSourceDetail filtered to YT_SEARCH. Returns [] when
    the API reports no search traffic (never fabricated).
    """
    resp = _query(
        client,
        channel_id,
        start,
        end,
        "views",
        "insightTrafficSourceDetail",
        "-views",
        filters="insightTrafficSourceType==YT_SEARCH",
        max_results=min(max(1, max_results), 50),
    )
    headers = [h.get("name") for h in (resp.get("columnHeaders") or [])]
    out = []
    for raw in resp.get("rows") or []:
        row = dict(zip(headers, raw))
        term = str(row.get("insightTrafficSourceDetail") or "").strip()
        if term:
            out.append({"term": term, "views": int(row.get("views") or 0)})
    return out
