"""Orchestration for Analytics snapshots + Trend Research runs.

Page loads NEVER call YouTube here; they read DB/AppSetting cache.
All network lives in ``refresh_*`` background functions.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.models import (
    AppSetting,
    Destination,
    Publication,
    YouTubeChannelAnalyticsDaily,
    YouTubeResearchItem,
    YouTubeResearchRun,
    YouTubeVideoAnalyticsDaily,
)

logger = logging.getLogger("douyin-youtube-research-svc")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Small AppSetting JSON cache helpers (traffic sources, search terms, tops)
# ---------------------------------------------------------------------------

def _cache_get(db, key: str) -> dict[str, Any] | None:
    row = db.get(AppSetting, key)
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return None


def _cache_set(db, key: str, payload: dict[str, Any]) -> None:
    row = db.get(AppSetting, key)
    blob = json.dumps(payload, ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key=key, value=blob))
    else:
        row.value = blob
    db.commit()


def insights_cache_key(destination_id: str, start: str, end: str) -> str:
    return f"yt_insights:{destination_id}:{start}:{end}"


# ---------------------------------------------------------------------------
# Analytics refresh (OWNED channel, Analytics API)
# ---------------------------------------------------------------------------

def analytics_status(db, destination: Destination) -> dict[str, Any]:
    from app.youtube import destination_analytics_scope_status

    ok, reason = destination_analytics_scope_status(destination)
    latest_date = db.execute(
        select(YouTubeChannelAnalyticsDaily.date)
        .where(YouTubeChannelAnalyticsDaily.destination_id == destination.id)
        .order_by(YouTubeChannelAnalyticsDaily.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    last_refresh = db.execute(
        select(AppSetting).where(
            AppSetting.key == f"yt_analytics_last_refresh:{destination.id}"
        )
    ).scalar_one_or_none()
    return {
        "oauth_ready": ok,
        "oauth_reason": reason,
        "reconnect_required": (not ok) and reason == "RECONNECT_REQUIRED",
        "latest_date": latest_date,
        "last_refresh_at": None,
    }


def queue_analytics_refresh(destination_id: str) -> dict[str, Any]:
    t = threading.Thread(
        target=_analytics_refresh_job, args=(destination_id,), daemon=True
    )
    t.start()
    return {"ok": True, "destination_id": destination_id, "status": "queued"}


def _analytics_refresh_job(destination_id: str) -> None:
    from app.db import SessionLocal
    from app.youtube import build_destination_client
    from app.youtube_analytics import (
        build_analytics_client,
        fetch_daily_report,
        fetch_search_terms,
        fetch_top_videos,
        fetch_traffic_sources,
        resolve_range,
    )

    try:
        with SessionLocal() as db:
            dest = db.get(Destination, destination_id)
            if dest is None:
                return
            from app.youtube import destination_analytics_scope_status

            ok, reason = destination_analytics_scope_status(dest)
            if not ok:
                logger.warning(
                    "analytics refresh skipped dest=%s reason=%s", destination_id, reason
                )
                return
            channel_id = dest.external_account_id
            if not channel_id:
                logger.warning("analytics refresh skipped dest=%s: no channel_id", destination_id)
                return
            creds, _yt = build_destination_client(db, destination_id)
            aclient = build_analytics_client(creds)
            # Refresh trailing 90d daily + insights for 28d window.
            start90, end = resolve_range("90d")
            rows = fetch_daily_report(aclient, channel_id, start90, end)
            for r in rows:
                _upsert_daily(db, dest, channel_id, r)
            start28, _ = resolve_range("28d")
            tops = fetch_top_videos(aclient, channel_id, start28, end)
            _upsert_top_videos(db, dest, start28, tops)
            traffic = fetch_traffic_sources(aclient, channel_id, start28, end)
            terms = fetch_search_terms(aclient, channel_id, start28, end)
            _cache_set(
                db,
                insights_cache_key(destination_id, start28, end),
                {
                    "traffic_sources": traffic,
                    "search_terms": terms,
                    "top_videos": tops,
                    "cached_at": utcnow().isoformat(),
                },
            )
            _cache_set(
                db,
                f"yt_analytics_last_refresh:{destination_id}",
                {"at": utcnow().isoformat()},
            )
            db.commit()
            logger.info(
                "analytics refresh done dest=%s days=%d tops=%d",
                destination_id, len(rows), len(tops),
            )
    except Exception:
        logger.exception("analytics refresh failed dest=%s", destination_id)


def _upsert_daily(db, dest: Destination, channel_id: str, r: dict[str, Any]) -> None:
    row = db.execute(
        select(YouTubeChannelAnalyticsDaily)
        .where(YouTubeChannelAnalyticsDaily.destination_id == dest.id)
        .where(YouTubeChannelAnalyticsDaily.date == r["date"])
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        row = YouTubeChannelAnalyticsDaily(
            destination_id=dest.id, channel_id=channel_id, date=r["date"]
        )
        db.add(row)
    row.views = r["views"]
    row.watch_minutes = r["watch_minutes"]
    row.avg_view_duration = r["avg_view_duration"]
    row.avg_view_percentage = r["avg_view_percentage"]
    row.likes = r["likes"]
    row.comments = r["comments"]
    row.shares = r["shares"]
    row.subs_gained = r["subs_gained"]
    row.subs_lost = r["subs_lost"]
    db.flush()


def _upsert_top_videos(db, dest: Destination, date_key: str, tops: list[dict]) -> None:
    for t in tops:
        vid = t.get("video_id") or ""
        if not vid:
            continue
        row = db.execute(
            select(YouTubeVideoAnalyticsDaily)
            .where(YouTubeVideoAnalyticsDaily.destination_id == dest.id)
            .where(YouTubeVideoAnalyticsDaily.video_id == vid)
            .where(YouTubeVideoAnalyticsDaily.date == date_key)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = YouTubeVideoAnalyticsDaily(
                destination_id=dest.id, video_id=vid, date=date_key
            )
            db.add(row)
        row.views = t.get("views", 0)
        row.watch_minutes = t.get("watch_minutes", 0.0)
        row.avg_view_duration = t.get("avg_view_duration", 0.0)
        row.likes = t.get("likes", 0)
        row.comments = t.get("comments", 0)
        row.subs_gained = t.get("subs_gained", 0)
        db.flush()


def maybe_background_analytics_refresh(db, destination: Destination) -> None:
    """Trigger a background refresh if stale (> 24/per_day h). Fire-and-forget."""
    try:
        per_day = max(1, min(4, int(getattr(settings, "youtube_analytics_refresh_per_day", 2) or 2)))
    except (TypeError, ValueError):
        per_day = 2
    interval = timedelta(hours=24.0 / per_day)
    row = db.get(AppSetting, f"yt_analytics_last_refresh:{destination.id}")
    if row is not None:
        try:
            last = datetime.fromisoformat(json.loads(row.value).get("at", ""))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if utcnow() - last < interval:
                return
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            pass
    queue_analytics_refresh(destination.id)


# ---------------------------------------------------------------------------
# Trend research runs (public Data API, quota-guarded, background)
# ---------------------------------------------------------------------------

def get_latest_run(db, destination_id: str) -> YouTubeResearchRun | None:
    return db.execute(
        select(YouTubeResearchRun)
        .where(YouTubeResearchRun.destination_id == destination_id)
        .order_by(YouTubeResearchRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def run_is_fresh(run: YouTubeResearchRun | None) -> bool:
    if run is None or run.status != "completed":
        return False
    try:
        cache_min = int(getattr(settings, "youtube_research_cache_minutes", 360) or 360)
    except (TypeError, ValueError):
        cache_min = 360
    created = run.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (utcnow() - created) < timedelta(minutes=cache_min)


def queue_research_refresh(destination_id: str, force: bool = False) -> dict[str, Any]:
    from app.db import SessionLocal

    with SessionLocal() as db:
        latest = get_latest_run(db, destination_id)
        if latest is not None and latest.status in ("queued", "fetching", "scoring", "ai_analysis"):
            return {
                "ok": True, "destination_id": destination_id,
                "status": latest.status, "run_id": latest.id, "cached": True,
            }
        if not force and run_is_fresh(latest):
            return {
                "ok": True, "destination_id": destination_id,
                "status": "completed", "run_id": latest.id, "cached": True,
            }
        run = YouTubeResearchRun(destination_id=destination_id, status="queued")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    t = threading.Thread(target=_research_job, args=(destination_id, run_id), daemon=True)
    t.start()
    return {"ok": True, "destination_id": destination_id, "status": "queued", "run_id": run_id}


def _set_run(db, run_id: str, **fields) -> None:
    run = db.get(YouTubeResearchRun, run_id)
    if run is None:
        return
    for k, v in fields.items():
        setattr(run, k, v)
    db.commit()


def _research_job(destination_id: str, run_id: str) -> None:
    from app import ai_research as _ai
    from app import trend_research as _tr
    from app.db import SessionLocal
    from app.youtube import build_destination_client

    try:
        with SessionLocal() as db:
            dest = db.get(Destination, destination_id)
            if dest is None:
                _set_run(db, run_id, status="failed", error="DESTINATION_NOT_FOUND")
                return
            try:
                max_search = int(getattr(settings, "youtube_research_max_search_calls_per_run", 5) or 5)
                max_videos = int(getattr(settings, "youtube_research_max_videos", 50) or 50)
            except (TypeError, ValueError):
                max_search, max_videos = 5, 50
            region = (getattr(dest, "research_region", None) or "VN").upper()
            regions = ["VN", "US"] if region == "MULTI" else [region if region in _tr.SUPPORTED_REGIONS else "VN"]
            _set_run(db, run_id, status="fetching", region=region)
            _, yt = build_destination_client(db, destination_id)
            # --- niche from OWN history (DB only, zero quota) ---
            pubs = db.execute(
                select(Publication)
                .where(Publication.destination_id == destination_id)
                .where(Publication.status == "published")
                .order_by(Publication.published_at.desc().nullslast())
                .limit(50)
            ).scalars().all()
            recent = [
                {"title": p.title or "", "tokens": _tr.tokenize(f"{p.title or ''} {p.description or ''}"),
                 "hashtags": _tr.extract_hashtags(p.description or "")}
                for p in pubs
            ]
            top_hist = db.execute(
                select(YouTubeVideoAnalyticsDaily)
                .where(YouTubeVideoAnalyticsDaily.destination_id == destination_id)
                .order_by(YouTubeVideoAnalyticsDaily.views.desc())
                .limit(20)
            ).scalars().all()
            top_hist_v = [
                {"title": t.title or "", "tokens": _tr.tokenize(t.title or "")} for t in top_hist
            ]
            # Channel identity (1 Data call, cheap).
            ch_title, ch_desc = dest.external_account_name or dest.name, ""
            try:
                ch_resp = yt.channels().list(
                    part="snippet", id=dest.external_account_id
                ).execute() if dest.external_account_id else {"items": []}
                items = ch_resp.get("items") or []
                if items:
                    sn = items[0].get("snippet") or {}
                    ch_title = sn.get("title") or ch_title
                    ch_desc = sn.get("description") or ""
            except Exception as exc:
                logger.warning("research channels.list failed: %s", exc)
            niche = _tr.infer_niche(
                ch_title, ch_desc, recent, top_hist_v,
                getattr(dest, "metadata_profile", None),
            )
            _set_run(db, run_id, niche=niche)
            # --- public discovery ---
            search_used = 0
            candidates: dict[str, dict] = {}
            for rg in regions:
                try:
                    for v in _tr.fetch_most_popular(yt, rg, max_results=25):
                        candidates.setdefault(v["video_id"], v)
                except Exception as exc:
                    logger.warning("mostPopular %s failed: %s", rg, exc)
            for kw in (niche.get("keywords") or [])[:max_search]:
                if search_used >= max_search:
                    break
                try:
                    ids = _tr.search_topic(yt, kw, regions[0], max_results=10)
                    search_used += 1
                    for v in _tr.fetch_video_details(yt, [i for i in ids if i not in candidates][:20]):
                        candidates.setdefault(v["video_id"], v)
                except Exception as exc:
                    logger.warning("search %r failed: %s", kw, exc)
            videos = list(candidates.values())[:max_videos]
            _set_run(db, run_id, status="scoring", search_calls_used=search_used, videos_analyzed=len(videos))
            ranked = _tr.rank_videos(videos, niche.get("keywords") or [])
            hashtag_stats = _tr.aggregate_hashtags(
                ranked, niche.get("hashtags"), limit=20
            )
            lang = niche.get("language") or "auto"
            # Fit for top 15 trend items.
            fit_map = {}
            for v in ranked[:15]:
                fit_map[v["video_id"]] = _tr.channel_fit_score(v, top_hist_v, niche.get("keywords") or [])
            # Persist items.
            for v in ranked[:50]:
                db.add(YouTubeResearchItem(
                    run_id=run_id, destination_id=destination_id, kind="video",
                    video_id=v.get("video_id"), title=(v.get("title") or "")[:400],
                    channel_title=(v.get("channel_title") or "")[:300],
                    thumbnail_url=v.get("thumbnail"),
                    views=v.get("views", 0),
                    views_per_hour=v.get("views_per_hour", 0.0),
                    age_hours=v.get("age_hours"),
                    trend_score=v.get("trend_score", 0),
                    channel_fit_score=(fit_map.get(v.get("video_id") or {}) or {}).get("channel_fit_score"),
                    evidence_json={
                        **(v.get("evidence_json") or {}),
                        "fit": fit_map.get(v.get("video_id") or {}),
                    },
                ))
            for h in hashtag_stats:
                db.add(YouTubeResearchItem(
                    run_id=run_id, destination_id=destination_id, kind="hashtag",
                    title=h.get("tag"), trend_score=h.get("trend_score", 0),
                    channel_fit_score=h.get("channel_fit_score"),
                    evidence_json={
                        "frequency": h.get("frequency"),
                        "recent_frequency": h.get("recent_frequency"),
                        "sample_video_ids": h.get("sample_video_ids", []),
                    },
                ))
            db.commit()
            # --- AI layer ---
            _set_run(db, run_id, status="ai_analysis")
            ai_out = _ai.analyze_trends(niche, ranked, hashtag_stats, lang)
            _set_run(db, run_id, status="completed", ai_output=ai_out, error=None)
            logger.info("research done dest=%s run=%s videos=%d", destination_id, run_id, len(videos))
    except Exception as exc:
        logger.exception("research job failed dest=%s run=%s", destination_id, run_id)
        try:
            from app.db import SessionLocal as _SL
            with _SL() as _db:
                _set_run(_db, run_id, status="failed", error=str(exc)[:1000])
        except Exception:
            pass
