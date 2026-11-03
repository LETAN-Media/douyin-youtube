import pytest

from app.services.scheduler import ensure_today_schedule, today_str, _slot_datetime


@pytest.mark.asyncio
async def test_today_str(db_session):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    p = await __import__("app.db.repositories.pipelines", fromlist=["pipelines"]).create_pipeline(db_session, name="P1", timezone="Asia/Ho_Chi_Minh")
    s = today_str(p.timezone)
    assert len(s) == 10


@pytest.mark.asyncio
async def test_ensure_today_schedule(db_session):
    from app.db.repositories import pipelines as pipeline_repo
    from app.db.repositories import schedules as sched_repo
    p = await pipeline_repo.create_pipeline(
        db_session, name="P1", timezone="Asia/Ho_Chi_Minh",
        publish_slots=["09:00", "15:00"], slot_max_daily=5,
    )
    rows = await ensure_today_schedule(db_session, p.id)
    assert len(rows) == 2
    assert rows[0].slot_time == "09:00"
    assert rows[1].slot_time == "15:00"
