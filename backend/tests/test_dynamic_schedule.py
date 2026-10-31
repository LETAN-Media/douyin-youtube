from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import Pipeline, Destination, DouyinVideo, Publication, VideoJob
from app.schedule_policy import generate_slots, effective_schedule, prepare_schedule_update, ScheduleError
from app import scheduler


@pytest.mark.parametrize('count', [1,3,5,6,10,15,20])
@pytest.mark.parametrize('overnight,start,end', [(False,'08:00','23:00'),(True,'22:00','06:00')])
def test_distribution(count, overnight, start, end):
    slots = generate_slots(count,start,end,overnight)
    assert len(slots)==len(set(slots))==count
    assert slots[0]==start
    if count>1: assert slots[-1]==end
    minutes=[int(s[:2])*60+int(s[3:]) for s in slots]
    minutes=[x+1440 if overnight and x<int(start[:2])*60 else x for x in minutes]
    assert minutes==sorted(minutes)
    gaps=[b-a for a,b in zip(minutes,minutes[1:])]
    assert not gaps or max(gaps)-min(gaps)<=1


def test_exact_ten_slot_example():
    assert generate_slots(10)==['08:00','09:40','11:20','13:00','14:40','16:20','18:00','19:40','21:20','23:00']


@pytest.mark.parametrize('args', [(0,),(-1,),(1.5,),(True,), (5,'08:00','08:02'), (3,'23:00','02:00'), (3,'25:00','23:00')])
def test_invalid_schedules_explain_why(args):
    with pytest.raises(ScheduleError):generate_slots(*args)


def test_safety_ceiling_is_configurable(monkeypatch):
    monkeypatch.setattr(settings,'scheduler_max_daily_uploads',8)
    with pytest.raises(ScheduleError,match='configured safety limit 8'):generate_slots(10)


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as session:yield session
    engine.dispose()


def make(db,limit=10,tz='UTC'):
    pipe=Pipeline(name='Dynamic',slug='dynamic',daily_upload_limit=limit,upload_slots=generate_slots(limit),auto_distribute_upload_slots=True,backlog_slots_per_day=limit-3 if limit>=3 else 0,new_slots_per_day=3 if limit>=3 else limit,timezone=tz)
    db.add(pipe);db.flush()
    dest=Destination(pipeline_id=pipe.id,platform='youtube',name='Channel',enabled=True,connected=True,credentials='{"refresh_token":"test"}',schedule_override_enabled=False)
    db.add(dest);db.commit()
    return pipe,dest


def test_pipeline_inheritance_and_explicit_override(db):
    pipe,dest=make(db)
    assert scheduler.shorts_daily_limit(dest)==10
    assert len(scheduler.shorts_slots_for_day(dest))==10
    dest.schedule_override_enabled=True;dest.daily_upload_limit=3;dest.upload_slots=generate_slots(3)
    assert scheduler.shorts_daily_limit(dest)==3
    assert pipe.daily_upload_limit==10
    dest.schedule_override_enabled=False
    assert scheduler.shorts_daily_limit(dest)==10


def test_manual_slots_not_overwritten_and_validation(db):
    pipe,dest=make(db,3)
    pipe.auto_distribute_upload_slots=False;pipe.upload_slots=['08:05','12:17','22:59']
    data=prepare_schedule_update(pipe,{'publishing_end_time':'23:00'})
    assert 'upload_slots' not in data and pipe.upload_slots==['08:05','12:17','22:59']
    with pytest.raises(ScheduleError,match='exactly 5'):prepare_schedule_update(pipe,{'daily_upload_limit':5})
    with pytest.raises(ScheduleError,match='unique'):prepare_schedule_update(pipe,{'upload_slots':['08:05','08:05','22:59']})
    with pytest.raises(ScheduleError,match='override'):prepare_schedule_update(dest,{'daily_upload_limit':5},pipe)


def test_backlog_new_uses_slot_position(db):
    pipe,dest=make(db)
    schedule=effective_schedule(dest)
    assert [scheduler.get_slot_type(i,schedule.backlog_slots_per_day,schedule.new_slots_per_day) for i in range(10)]==['backlog']*7+['new']*3


@pytest.mark.parametrize('tz', ['UTC','Asia/Ho_Chi_Minh'])
@pytest.mark.parametrize('limit', [1,3,5,6,10,15,20])
def test_scheduler_uses_configured_count_and_stops_at_limit(db,tz,limit):
    pipe,dest=make(db,limit,tz)
    for i in range(limit+2):
        db.add(DouyinVideo(pipeline_id=pipe.id,video_id=str(i),title='dance',url='https://example.test/'+str(i),status='new',is_backlog=i<max(0,limit-3)))
    db.commit()
    from zoneinfo import ZoneInfo
    for time in generate_slots(limit):
        h,m=map(int,time.split(':'));now=datetime(2026,11,2,h,m,tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)
        with patch('app.scheduler.evaluate_content_level',return_value=('match','dance')):
            scheduler.schedule_for_destination(db,dest,now)
            scheduler.schedule_for_destination(db,dest,now) # idempotent replay
    pubs=db.scalars(select(Publication)).all();jobs=db.scalars(select(VideoJob)).all()
    assert len(pubs)==len(jobs)==limit
    assert len({j.schedule_slot_key for j in jobs})==limit
    assert scheduler.count_day_usage(db,dest,datetime(2026,11,2).date())==(0,limit)


def test_schedule_edit_keeps_reserved_times_and_no_catchup(db):
    pipe,dest=make(db)
    video=DouyinVideo(pipeline_id=pipe.id,video_id='1',title='dance',url='https://example.test/1',status='new');db.add(video);db.flush()
    before=datetime(2026,11,2,8,tzinfo=timezone.utc)
    pub=Publication(pipeline_id=pipe.id,destination_id=dest.id,douyin_video_id=video.id,platform='youtube',status='scheduled',scheduled_at=before);db.add(pub);db.commit()
    pipe.schedule_updated_at=datetime(2026,11,2,17,tzinfo=timezone.utc);dest.last_scheduler_check_at=before
    with patch('app.scheduler.pick_video') as pick:
        scheduler.schedule_for_destination(db,dest,pipe.schedule_updated_at)
        pick.assert_not_called()
    assert pub.scheduled_at==before


def test_provider_quota_pause_survives_new_session(db):
    from app.upload_quota import pause_after_quota_error, quota_block_reason
    now=datetime(2026,11,2,12,tzinfo=timezone.utc)
    pause_after_quota_error(db,now);db.commit()
    assert 'QUOTA_EXHAUSTED' in quota_block_reason(db,now)
    with Session(db.bind) as restarted:
        assert 'QUOTA_EXHAUSTED' in quota_block_reason(restarted,now)
        assert quota_block_reason(restarted,now+timedelta(days=1)) is None


def test_worker_limit_survives_restart_and_does_not_claim_excess(db,monkeypatch):
    from app import worker
    from sqlalchemy.orm import sessionmaker
    pipe,dest=make(db,3)
    now=datetime(2026,11,2,12,tzinfo=timezone.utc)
    for i in range(3):
        v=DouyinVideo(pipeline_id=pipe.id,video_id=str(i),title='dance',url='https://x.test');db.add(v);db.flush()
        db.add(Publication(pipeline_id=pipe.id,destination_id=dest.id,douyin_video_id=v.id,platform='youtube',status='published',published_at=now-timedelta(hours=1)))
    job=VideoJob(pipeline_id=pipe.id,destination_id=dest.id,source_url='https://x.test',status='pending');db.add(job);db.commit()
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=db.bind))
    monkeypatch.setattr(worker,'utcnow',lambda:now)
    assert worker.claim_job() is None
    db.expire_all();assert db.get(VideoJob,job.id).status=='pending'


def test_backlog_fallback_can_be_disabled(db):
    pipe,dest=make(db)
    pipe.slot_fallback_enabled=False
    with patch('app.scheduler._try_pick_video',return_value=None) as pick:
        assert scheduler.pick_video(db,pipe,'backlog',dest) is None
        assert pick.call_count==1 and pick.call_args.args[2]=='backlog'
    pipe.slot_fallback_enabled=True
    with patch('app.scheduler._try_pick_video',return_value=None) as pick:
        scheduler.pick_video(db,pipe,'backlog',dest)
        assert [c.args[2] for c in pick.call_args_list]==['backlog','new']


def test_quota_exhaustion_does_not_create_jobs(db,monkeypatch):
    from app.upload_quota import pause_after_quota_error
    pipe,dest=make(db)
    now=datetime.now(timezone.utc)
    pause_after_quota_error(db,now);db.commit()
    scheduler.schedule_for_destination(db,dest,now)
    assert 'QUOTA_EXHAUSTED' in dest.last_skip_reason
    assert db.scalar(select(VideoJob.id)) is None


def test_api_save_syncs_limit_slots_and_inherited_destination(db,monkeypatch):
    from app import main
    from app.schemas import PipelineUpdate,DestinationUpdate
    pipe,dest=make(db,3)
    monkeypatch.setattr(main,'require_pipeline',lambda session,id: session.get(Pipeline,id))
    monkeypatch.setattr(main,'require_destination',lambda session,id: session.get(Destination,id))
    result=main.update_pipeline(pipe.id,PipelineUpdate(daily_upload_limit=10,auto_distribute_upload_slots=True,publishing_start_time='08:00',publishing_end_time='23:00',backlog_slots_per_day=7,new_slots_per_day=3),db)
    assert result.upload_slots==generate_slots(10)
    assert len(scheduler.shorts_slots_for_day(dest))==10
    main.update_destination(dest.id,DestinationUpdate(schedule_override_enabled=True,daily_upload_limit=5,auto_distribute_upload_slots=True,backlog_slots_per_day=3,new_slots_per_day=2,min_upload_interval_minutes=1),db)
    assert scheduler.shorts_daily_limit(dest)==5
    assert pipe.daily_upload_limit==10


def test_limit_reduction_cannot_silently_change_existing_reservations(db,monkeypatch):
    from fastapi import HTTPException
    from app import main
    from app.schemas import PipelineUpdate
    pipe,dest=make(db,5)
    now=datetime.now(timezone.utc)
    for i in range(4):
        v=DouyinVideo(pipeline_id=pipe.id,video_id=str(i),title='dance',url='https://example.test');db.add(v);db.flush()
        db.add(Publication(pipeline_id=pipe.id,destination_id=dest.id,douyin_video_id=v.id,platform='youtube',status='scheduled',scheduled_at=now+timedelta(minutes=i)))
    db.commit()
    before=db.scalars(select(Publication.scheduled_at).order_by(Publication.scheduled_at)).all()
    monkeypatch.setattr(main,'require_pipeline',lambda session,id: session.get(Pipeline,id))
    with pytest.raises(HTTPException) as e:main.update_pipeline(pipe.id,PipelineUpdate(daily_upload_limit=3,auto_distribute_upload_slots=True),db)
    assert e.value.status_code==409
    db.rollback()
    assert db.scalars(select(Publication.scheduled_at).order_by(Publication.scheduled_at)).all()==before
    assert db.get(Pipeline,pipe.id).daily_upload_limit==5


def test_manual_preview_does_not_write_settings(db):
    from app.main import preview_schedule
    from app.schemas import PipelineUpdate
    pipe,dest=make(db,3)
    response=preview_schedule(PipelineUpdate(daily_upload_limit=10,auto_distribute_upload_slots=True,backlog_slots_per_day=7,new_slots_per_day=3))
    assert len(response['upload_slots'])==10
    assert db.get(Pipeline,pipe.id).daily_upload_limit==3


def test_migration_preserves_distinct_legacy_schedule_and_is_idempotent(tmp_path):
    from app.migrate import SchemaCache,_apply_019
    from sqlalchemy import text,inspect
    engine=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE pipelines (id TEXT PRIMARY KEY,daily_upload_limit INTEGER,timezone TEXT,upload_slots TEXT,backlog_slots_per_day INTEGER DEFAULT 4,new_slots_per_day INTEGER DEFAULT 2)'))
        conn.execute(text('CREATE TABLE destinations (id TEXT PRIMARY KEY,pipeline_id TEXT,daily_upload_limit INTEGER,timezone TEXT,upload_slots TEXT,backlog_slots_per_day INTEGER DEFAULT 4,new_slots_per_day INTEGER DEFAULT 2,min_upload_interval_minutes INTEGER DEFAULT 0)'))
        conn.execute(text("INSERT INTO pipelines(id,daily_upload_limit,timezone,upload_slots) VALUES ('p',6,'UTC','[\"08:00\"]')"))
        conn.execute(text("INSERT INTO destinations(id,pipeline_id,daily_upload_limit,timezone,upload_slots) VALUES ('same','p',6,'UTC','[\"08:00\"]'),('custom','p',10,'UTC','[\"09:00\"]')"))
    with engine.connect() as conn:cache=SchemaCache(conn,True)
    _apply_019(cache,engine)
    _apply_019(cache,engine)
    with engine.connect() as conn:
        rows=conn.execute(text('SELECT id,schedule_override_enabled FROM destinations ORDER BY id')).all()
        assert rows==[('custom',1),('same',0)]
        assert conn.execute(text('SELECT daily_upload_limit,upload_slots FROM pipelines')).first()==(6,'["08:00"]')


def test_known_project_budget_rejects_infeasible_save(db,monkeypatch):
    pipe,dest=make(db,3)
    monkeypatch.setattr(settings,'youtube_project_daily_upload_budget',5)
    with pytest.raises(ScheduleError,match='project upload budget 5'):
        prepare_schedule_update(pipe,{'daily_upload_limit':10})


def test_invalid_legacy_config_is_editable_but_scheduler_pauses(db,monkeypatch):
    pipe,dest=make(db,10)
    monkeypatch.setattr(settings,'scheduler_max_daily_uploads',5)
    assert dest.effective_schedule['daily_upload_limit']==10
    assert 'INVALID_SCHEDULE' in dest.effective_schedule['warnings'][0]
    scheduler.schedule_for_destination(db,dest,datetime.now(timezone.utc))
    assert 'INVALID_SCHEDULE' in dest.last_skip_reason


def test_identical_save_does_not_restart_schedule_cutover(db):
    pipe,dest=make(db)
    original=datetime(2026,11,1,7,tzinfo=timezone.utc);pipe.schedule_updated_at=original
    data=prepare_schedule_update(pipe,{'daily_upload_limit':10,'auto_distribute_upload_slots':True,'upload_slots':generate_slots(10)})
    assert 'schedule_updated_at' not in data
    assert pipe.schedule_updated_at==original


def test_overnight_scheduler_uses_window_positions(db):
    from zoneinfo import ZoneInfo
    pipe,dest=make(db,5,'Asia/Ho_Chi_Minh')
    pipe.publishing_start_time='22:00';pipe.publishing_end_time='02:00';pipe.publishing_overnight=True
    for i in range(5):db.add(DouyinVideo(pipeline_id=pipe.id,video_id=f'night-{i}',title='dance',url=f'https://example.test/{i}',status='new',is_backlog=i<2))
    db.commit()
    for day,hour in [(2,22),(2,23),(3,0),(3,1),(3,2)]:
        now=datetime(2026,11,day,hour,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')).astimezone(timezone.utc)
        with patch('app.scheduler.evaluate_content_level',return_value=('match','dance')):scheduler.schedule_for_destination(db,dest,now)
    jobs=list(db.scalars(select(VideoJob).order_by(VideoJob.created_at)))
    assert len(jobs)==5
    assert [j.source_video_id for j in jobs[:2]]==['night-0','night-1']
    assert len({j.schedule_slot_key for j in jobs})==5


def test_channel_quota_pause_does_not_pause_other_destinations(db):
    from app.upload_quota import pause_after_quota_error,quota_block_reason
    now=datetime(2026,11,2,12,tzinfo=timezone.utc)
    pause_after_quota_error(db,now,destination_id='a');db.commit()
    assert quota_block_reason(db,now,destination_id='a')
    assert quota_block_reason(db,now,destination_id='b') is None


def test_channel_hot_path_with_noload_still_inherits_pipeline(db,monkeypatch):
    from app.main import get_channel_detail_endpoint
    pipe,dest=make(db,10)
    monkeypatch.setattr('app.tenancy.tenant_ctx',lambda:SimpleNamespace(is_system_admin=True))
    # Force a fresh identity map so no previously loaded relationship masks noload.
    dest_id=dest.id;db.expunge_all()
    result=get_channel_detail_endpoint(dest_id,db)
    assert result.daily_upload_limit==10
    assert len(result.effective_schedule['upload_slots'])==10
    assert result.effective_schedule['source']=='pipeline'


@pytest.mark.parametrize('tz,expected', [('UTC','2026-11-02T08:00:00+00:00'),('Asia/Ho_Chi_Minh','2026-11-02T01:00:00+00:00')])
def test_status_next_slot_uses_effective_timezone(db,monkeypatch,tz,expected):
    from app import main
    pipe,dest=make(db,10,tz)
    monkeypatch.setattr(main,'_utcnow',lambda:datetime(2026,11,2,0,55,tzinfo=timezone.utc))
    assert main._destination_next_upload(dest)==expected
