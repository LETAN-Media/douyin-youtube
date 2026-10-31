from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models import DouyinVideo, Pipeline
from app.scheduler import _hold_video, _reject_video
import pytest

@pytest.mark.parametrize('handler,status', [(_hold_video, 'held'), (_reject_video, 'rejected')])
def test_verdict_and_reason_survive_new_session(handler, status):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        pipeline = Pipeline(name='Dance', slug='dance')
        db.add(pipeline)
        db.flush()
        video = DouyinVideo(pipeline_id=pipeline.id, video_id='123', title='Video', description='', url='https://example.com/123')
        db.add(video)
        db.commit()
        vid = video.id
        handler(db, video, level='mismatch', reason='No relevant content evidence')
    with Session(engine) as db:
        saved = db.get(DouyinVideo, vid)
        assert (saved.status, saved.match_level, saved.hold_reason) == (status, 'mismatch', 'No relevant content evidence')
    engine.dispose()
