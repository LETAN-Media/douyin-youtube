"""Tests for Channel Content DNA (per-channel isolation, locked core)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import channel_dna as dna
from app.db import Base
from app.models import Destination, Pipeline, Publication, DouyinVideo


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _dest(db, name="Chan"):
    pipe = Pipeline(name=f"P-{name}", slug=f"p-{name}".lower(), enabled=True)
    db.add(pipe)
    db.flush()
    d = Destination(
        pipeline_id=pipe.id, platform="youtube", name=name,
        enabled=True, connected=True, credentials="{}",
        fixed_hashtags=["#HandsomeBoys"], metadata_language="en",
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_dna_isolation_per_channel(db):
    a = _dest(db, "ChanA")
    b = _dest(db, "ChanB")
    da = dna.get_or_create_dna(db, a)
    db.commit()
    dna.update_dna(db, da, {"primary_niche": "boys love", "locked_hashtags": ["#BL"]})
    db2 = dna.get_or_create_dna(db, b)
    assert (db2.locked_hashtags or []) != ["#bl"]
    assert (da.locked_hashtags or []) == ["#bl"]


def test_locked_hashtags_preserved_verbatim(db):
    merged, kept, added = dna.merge_final_hashtags(
        ["#HandsomeBoys", "#BL"], ["bl", "HandsomeBoys", "newtag", "#NewTag"]
    )
    assert kept == ["#handsomeboys", "#bl"]
    assert added == ["#newtag"]
    assert merged == ["#handsomeboys", "#bl", "#newtag"]


def test_locked_tags_normalized_deduped(db):
    merged, kept, added = dna.merge_final_tags(
        ["Handsome Boys", "  handsome  boys "], ["handsome boys", "New Tag"]
    )
    assert merged == ["handsome boys", "new tag"]
    assert kept == ["handsome boys"]


def test_fingerprint_keys_before_title(db):
    fp = dna.generate_fingerprint("Sunset dance", "caption #dance", "en")
    assert set(fp.keys()) >= {
        "topic", "subtopics", "characters", "setting", "story_angle",
        "emotion", "audience_intent", "primary_keywords", "language",
    }
    assert "title" not in fp


def test_title_candidates_shape(db):
    dest = _dest(db)
    record = dna.get_or_create_dna(db, dest)
    db.commit()
    fp = dna.build_fingerprint_heuristic("Night dance battle", "caption", "en")
    titles = dna.generate_title_candidates(fp, dna.dna_to_dict(record), [], count=5)
    assert len(titles) == 5
    for t in titles:
        assert t["title"]
        assert {"channel_fit_score", "trend_fit_score", "reason"} <= set(t.keys())


def test_learning_never_auto_mutates_locked(db):
    dest = _dest(db)
    record = dna.get_or_create_dna(db, dest)
    db.commit()
    dna.update_dna(db, record, {"locked_hashtags": ["#HandsomeBoys"]})
    before = list(record.locked_hashtags or [])
    # suggest_from_performance only creates pending suggestions.
    dna.record_performance_snapshot(
        db, dest.id, "vid1", "24h",
        {"views": 15000, "watch_minutes": 300, "avg_view_duration": 20,
         "likes": 500, "comments": 50, "subs_gained": 10},
    )
    dna.record_performance_snapshot(
        db, dest.id, "vid1", "7d",
        {"views": 20000, "watch_minutes": 400, "avg_view_duration": 20,
         "likes": 600, "comments": 60, "subs_gained": 12},
    )
    made = dna.suggest_from_performance(db, dest.id)
    assert isinstance(made, list)
    db.refresh(record)
    assert list(record.locked_hashtags or []) == before


def test_suggestion_apply_and_dismiss(db):
    from app.models import YouTubeDNASuggestion

    dest = _dest(db)
    record = dna.get_or_create_dna(db, dest)
    db.commit()
    sug = YouTubeDNASuggestion(
        destination_id=dest.id, kind="suggest_core_hashtag",
        payload={"tag": "#BL"}, reason="test", status="pending",
    )
    db.add(sug)
    db.commit()
    db.refresh(sug)
    out = dna.apply_suggestion(db, sug.id, dest.id)
    assert out["ok"] is True
    db.refresh(record)
    assert "#bl" in (record.locked_hashtags or [])
    # Double-apply rejected.
    with pytest.raises(ValueError):
        dna.apply_suggestion(db, sug.id, dest.id)


def test_fingerprint_saved_per_publication(db):
    dest = _dest(db)
    video = DouyinVideo(
        pipeline_id=dest.pipeline_id, video_id="v1",
        title="T", description="D", url="https://x",
    )
    db.add(video)
    db.flush()
    pub = Publication(
        pipeline_id=dest.pipeline_id, douyin_video_id=video.id,
        destination_id=dest.id, platform="youtube", status="queued",
    )
    db.add(pub)
    db.flush()
    dna.save_fingerprint(db, pub.id, dest.id, {"topic": "T"})
    db.commit()
    from app.models import YouTubeContentFingerprint

    row = db.query(YouTubeContentFingerprint).filter(
        YouTubeContentFingerprint.publication_id == pub.id
    ).one()
    assert row.fingerprint["topic"] == "T"
