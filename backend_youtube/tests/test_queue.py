import pytest

from app.db.repositories import queue as queue_repo
from app.db.repositories import pipelines as pipeline_repo
from app.db.models import QueueStatus


@pytest.mark.asyncio
async def test_enqueue_and_claim(db_session):
    from app.db.repositories import facebook_pages as fb_repo
    from app.db.repositories import media_files as media_repo
    from app.db.repositories import videos as videos_repo
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    await videos_repo.upsert_video(db_session, p.id, "vid1", is_insert_only=True)
    page = await fb_repo.add_facebook_page(db_session, p.id, page_id="pageid1", is_default=True)
    media = await media_repo.create_media_file(db_session, p.id, "vid1", status="ready", publish_status="ready")
    item = await queue_repo.enqueue(
        db_session, pipeline_id=p.id, youtube_video_id="vid1",
        facebook_page_id=page.id, media_file_id=media.id, priority=5,
    )
    assert item.status == QueueStatus.PENDING
    claimed = await queue_repo.claim_next(db_session, p.id, "worker1", concurrency=1, stale_ttl=300)
    assert len(claimed) == 1
    assert claimed[0].status == QueueStatus.PROCESSING
    assert claimed[0].reservation_token is not None


@pytest.mark.asyncio
async def test_claim_is_idempotent_skip_locked(db_session):
    """A second worker should not claim the same in-process item due to reservation."""
    from app.db.repositories import facebook_pages as fb_repo
    from app.db.repositories import media_files as media_repo
    from app.db.repositories import videos as videos_repo
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    await videos_repo.upsert_video(db_session, p.id, "vid1", is_insert_only=True)
    page = await fb_repo.add_facebook_page(db_session, p.id, page_id="pageid1", is_default=True)
    media = await media_repo.create_media_file(db_session, p.id, "vid1", status="ready", publish_status="ready")
    await queue_repo.enqueue(
        db_session, pipeline_id=p.id, youtube_video_id="vid1", facebook_page_id=page.id, media_file_id=media.id,
    )
    first = await queue_repo.claim_next(db_session, p.id, "w1", concurrency=1)
    second = await queue_repo.claim_next(db_session, p.id, "w2", concurrency=1)
    assert len(first) == 1
    assert len(second) == 0


@pytest.mark.asyncio
async def test_is_already_queued(db_session):
    from app.db.repositories import facebook_pages as fb_repo
    from app.db.repositories import media_files as media_repo
    from app.db.repositories import videos as videos_repo
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    await videos_repo.upsert_video(db_session, p.id, "vid1", is_insert_only=True)
    page = await fb_repo.add_facebook_page(db_session, p.id, page_id="pageid1", is_default=True)
    media = await media_repo.create_media_file(db_session, p.id, "vid1", status="ready", publish_status="ready")
    await queue_repo.enqueue(
        db_session, pipeline_id=p.id, youtube_video_id="vid1", facebook_page_id=page.id, media_file_id=media.id,
    )
    assert await queue_repo.is_already_queued(db_session, p.id, "vid1", page.id) is True
    assert await queue_repo.is_already_queued(db_session, p.id, "vid9", page.id) is False
