import pytest
from sqlalchemy import func, select

from app.db.models import Pipeline, YouTubeSource, YouTubeVideo
from app.db.repositories import pipelines as pipeline_repo
from app.db.repositories import sources as sources_repo
from app.db.repositories import videos as videos_repo


@pytest.mark.asyncio
async def test_create_and_get_pipeline(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="Test Pipeline")
    assert p.id.startswith("youtube_")
    fetched = await pipeline_repo.get_pipeline(db_session, p.id)
    assert fetched is not None
    assert fetched.name == "Test Pipeline"


@pytest.mark.asyncio
async def test_update_pipeline(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    updated = await pipeline_repo.update_pipeline(db_session, p.id, status="paused", max_daily_publish=10)
    assert updated.status == "paused"
    assert updated.max_daily_publish == 10


@pytest.mark.asyncio
async def test_add_and_list_sources(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    src = await sources_repo.add_source(db_session, p.id, channel_id="UC123", channel_title="Test Channel")
    assert src.id.startswith("yt_")
    srcs = await sources_repo.list_sources(db_session, p.id)
    assert len(srcs) == 1
    assert srcs[0].channel_id == "UC123"


@pytest.mark.asyncio
async def test_upsert_video_insert_only_dedup(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    v1 = await videos_repo.upsert_video(db_session, p.id, "vid1", title="Title", is_insert_only=True)
    v2 = await videos_repo.upsert_video(db_session, p.id, "vid1", title="Title2", is_insert_only=True, raw={"new": True})
    assert v1.video_id == "vid1"
    assert v2.video_id == "vid1"
    assert v2 is v1 or v2.video_id == v1.video_id
    assert v2.raw == {"new": True}


@pytest.mark.asyncio
async def test_videos_count(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    await videos_repo.upsert_video(db_session, p.id, "v1", title="one", is_insert_only=True)
    await videos_repo.upsert_video(db_session, p.id, "v2", is_insert_only=True)
    assert await pipeline_repo.count_videos(db_session, p.id) == 2
