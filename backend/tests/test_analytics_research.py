"""Unit + integration tests for Analytics + Trend Research (no real API calls)."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import trend_research as tr
from app.ai_research import validate_research_output
from app.main import app
from app.youtube_analytics import (
    normalize_daily_rows,
    resolve_range,
    summarize_daily,
)


def _video(**kw):
    base = {
        "video_id": "v1", "title": "Dance challenge fire", "description": "",
        "channel_id": "c1", "channel_title": "Chan", "published_at": None,
        "age_hours": 10.0, "views": 10000, "likes": 400, "comments": 50,
        "views_per_hour": 1000.0, "like_rate": 0.04, "comment_rate": 0.005,
        "tokens": ["dance", "challenge", "fire"], "hashtags": ["#dance"],
        "thumbnail": None,
    }
    base.update(kw)
    return base


def test_range_presets():
    s, e = resolve_range("7d")
    assert (datetime.fromisoformat(e) - datetime.fromisoformat(s)).days == 6
    s, e = resolve_range("custom", start="2026-01-01", end="2026-01-31")
    assert (s, e) == ("2026-01-01", "2026-01-31")


def test_normalize_and_summarize():
    resp = {
        "columnHeaders": [
            {"name": "day"}, {"name": "views"},
            {"name": "estimatedMinutesWatched"},
            {"name": "averageViewDuration"},
            {"name": "averageViewPercentage"},
            {"name": "likes"}, {"name": "comments"}, {"name": "shares"},
            {"name": "subscribersGained"}, {"name": "subscribersLost"},
        ],
        "rows": [["2026-09-20", 100, 50.0, 30.0, 60.0, 5, 1, 0, 2, 0]],
    }
    rows = normalize_daily_rows(resp)
    assert rows[0]["views"] == 100
    assert rows[0]["subs_gained"] == 2
    summary = summarize_daily(rows)
    assert summary["views"] == 100
    assert summary["subs_net"] == 2
    assert summary["watch_hours"] == round(50.0 / 60.0, 1)


def test_trend_score_deterministic():
    v1 = _video()
    v2 = _video(video_id="v2", views_per_hour=10.0, like_rate=0.001, comment_rate=0.0, age_hours=2000.0)
    s1 = tr.score_video(v1, ["dance"])["trend_score"]
    s2 = tr.score_video(v2, ["dance"])["trend_score"]
    assert 0 <= s1 <= 100 and 0 <= s2 <= 100
    assert s1 > s2
    # Deterministic: same input twice.
    assert tr.score_video(v1, ["dance"])["trend_score"] == s1


def test_ranking_and_hashtags():
    videos = [_video(video_id=f"v{i}", views_per_hour=100.0 * (i + 1)) for i in range(5)]
    ranked = tr.rank_videos(videos, ["dance"])
    assert ranked[0]["views_per_hour"] >= ranked[-1]["views_per_hour"]
    tags = tr.aggregate_hashtags(ranked, ["#dance"])
    assert tags and tags[0]["tag"] == "#dance"
    assert tags[0]["sample_video_ids"]


def test_channel_fit_and_warning():
    trend = _video(trend_score=85)
    hist = [{"title": "cooking pasta recipe", "tokens": ["cooking", "pasta", "recipe"]}]
    fit = tr.channel_fit_score(trend, hist, ["dance"])
    assert fit["channel_fit_score"] < 45
    assert fit["warning"]


def test_title_json_validation():
    ok, norm, err = validate_research_output({"channel_niche": "x"})
    assert ok and err is None
    assert norm["title_ideas"] == []
    bad, _, err2 = validate_research_output({"title_ideas": [{"angle": "no title"}]})
    assert not bad and err2


def test_niche_inference_no_hardcode():
    niche = tr.infer_niche(
        "Fluffy Friends", "cute pets",
        [{"title": "puppy plays", "tokens": ["puppy", "plays"], "hashtags": ["#puppy"]}],
        [], None,
    )
    assert "puppy" in niche["keywords"]
    assert niche["language"] in ("en", "vi", "zh", "auto")


def test_oauth_missing_analytics_scope(client=None):
    from unittest.mock import MagicMock

    from app.youtube import destination_analytics_scope_status

    dest = MagicMock()
    dest.credentials = None
    ok, reason = destination_analytics_scope_status(dest)
    assert not ok and reason == "YOUTUBE_REAUTH_REQUIRED"
    dest.credentials = '{"scopes": ["https://www.googleapis.com/auth/youtube.readonly"]}'
    ok, reason = destination_analytics_scope_status(dest)
    assert not ok and reason == "RECONNECT_REQUIRED"
    dest.credentials = (
        '{"scopes": ["https://www.googleapis.com/auth/yt-analytics.readonly"]}'
    )
    ok, reason = destination_analytics_scope_status(dest)
    assert ok and reason is None


def test_analytics_endpoints_no_external_calls():
    from unittest.mock import patch

    from app.config import settings
    from app.db import SessionLocal
    from app.models import Destination

    authed = TestClient(app, headers={"X-Admin-Token": settings.admin_token})
    with SessionLocal() as db:
        dest = db.query(Destination).filter(Destination.connected == True).first()  # noqa: E712
        if not dest:
            import pytest

            pytest.skip("No connected destination")
        dest_id = dest.id
    # Cached GET must not touch googleapiclient.
    with patch("googleapiclient.discovery.build") as mock_build:
        r = authed.get(f"/api/channels/{dest_id}/analytics?range=28d")
        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is True
        assert "summary" in body and "daily" in body
        mock_build.assert_not_called()
    with patch("googleapiclient.discovery.build") as mock_build:
        r = authed.get(f"/api/channels/{dest_id}/research")
        assert r.status_code == 200
        mock_build.assert_not_called()


def test_research_cache_second_load_no_search():
    from unittest.mock import patch

    from app.config import settings
    from app.db import SessionLocal
    from app.models import Destination, YouTubeResearchRun

    authed = TestClient(app, headers={"X-Admin-Token": settings.admin_token})
    with SessionLocal() as db:
        dest = db.query(Destination).filter(Destination.connected == True).first()  # noqa: E712
        if not dest:
            import pytest

            pytest.skip("No connected destination")
        dest_id = dest.id
        run = YouTubeResearchRun(
            destination_id=dest_id, status="completed", region="VN",
            niche={"keywords": ["dance"]}, ai_output={"hot_topics": []},
        )
        db.add(run)
        db.commit()
        run_id = run.id
    try:
        with patch("app.trend_research.search_topic") as mock_search:
            r = authed.post(f"/api/channels/{dest_id}/research/refresh")
            assert r.status_code == 202
            assert r.json().get("cached") is True
            mock_search.assert_not_called()
    finally:
        with SessionLocal() as db:
            db.query(YouTubeResearchRun).filter(
                YouTubeResearchRun.id == run_id
            ).delete()
            db.commit()


def test_apply_metadata_bundle():
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Destination

    authed = TestClient(app, headers={"X-Admin-Token": settings.admin_token})
    with SessionLocal() as db:
        dest = db.query(Destination).filter(Destination.connected == True).first()  # noqa: E712
        if not dest:
            import pytest

            pytest.skip("No connected destination")
        dest_id = dest.id
    r = authed.post(
        f"/api/channels/{dest_id}/research/apply",
        json={"title": "T", "keywords": ["k"], "hashtags": ["dance"]},
    )
    assert r.status_code == 200
    assert r.json()["hashtags"] == ["#dance"]
