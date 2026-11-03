import pytest

from app.db.repositories import pipelines as pipeline_repo
from app.db.repositories import facebook_pages as fb_repo
from app.db.repositories import sources as sources_repo
from app.db.repositories import videos as videos_repo
from app.db.repositories import history as history_repo
from app.db.repositories import queue as queue_repo
from app.db.repositories import media_files as media_repo
from app.db.models import PublicationOutcome, QueueStatus


@pytest.mark.asyncio
async def test_idempotent_publication(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    await videos_repo.upsert_video(db_session, p.id, "v1", is_insert_only=True)
    page = await fb_repo.add_facebook_page(db_session, p.id, page_id="pg1", is_default=True)
    media = await media_repo.create_media_file(db_session, p.id, "v1", status="ready", publish_status="ready")
    await history_repo.create_publication_history(
        db_session, pipeline_id=p.id, youtube_video_id="v1", facebook_page_id=page.id, media_file_id=media.id,
        facebook_post_id="post1", status=PublicationOutcome.SUCCESS,
    )
    dup = await history_repo.create_publication_history(
        db_session, pipeline_id=p.id, youtube_video_id="v1", facebook_page_id=page.id, media_file_id=media.id,
        facebook_post_id="post1", status=PublicationOutcome.SUCCESS, is_update=True,
    )
    assert dup is not None
    assert await history_repo.is_already_published(db_session, p.id, "v1", page.id) is True


@pytest.mark.asyncio
async def test_quota_enforcement(db_session):
    from app.db.repositories import quota as quota_repo
    from datetime import datetime, timezone
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    date_str = "2026-01-01"
    assert await quota_repo.can_publish_today(db_session, p.id, date_str, 5) is True
    await quota_repo.increment_quota(db_session, p.id, date_str)
    await quota_repo.increment_quota(db_session, p.id, date_str)
    await quota_repo.increment_quota(db_session, p.id, date_str)
    await quota_repo.increment_quota(db_session, p.id, date_str)
    await quota_repo.increment_quota(db_session, p.id, date_str)
    assert await quota_repo.can_publish_today(db_session, p.id, date_str, 5) is False
