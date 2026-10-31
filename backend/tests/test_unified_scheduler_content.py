"""Content verdicts must not prevent AUTO from considering source videos."""
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline, Publication
from app.scheduler import pick_video


@pytest.mark.parametrize('niche,source_linked', [
    ('Male dance performance and choreography', True),
    ('Male dance and fitness entertainment', True),
    ('Cute animals and pets', True),
    ('Male dance performance and choreography', False),
])
def test_content_profile_and_missing_caption_do_not_block_selection(niche, source_linked):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        pipeline = Pipeline(id=str(uuid4()), name='Test', slug=str(uuid4()), niche=niche,
                            timezone='UTC', daily_upload_limit=4)
        destination = Destination(id=str(uuid4()), pipeline_id=pipeline.id,
                                  name='Test', platform='youtube', enabled=True)
        db.add_all([pipeline, destination])
        source = None
        if source_linked:
            source = DouyinSource(id=str(uuid4()), pipeline_id=pipeline.id,
                                  name='Creator', enabled=True, mismatch_policy='reject', borderline_policy='hold')
            db.add(source)
        video = DouyinVideo(id=str(uuid4()), pipeline_id=pipeline.id,
                            source_id=source.id if source else None,
                            video_id='7702383117105674427', title='7702383117105674427',
                            description='', url='https://www.douyin.com/video/7702383117105674427',
                            status='new', is_backlog=False)
        db.add(video)
        db.commit()
        with patch('app.scheduler.evaluate_content_level', side_effect=AssertionError('Scheduler must not call AI')):
            selected = pick_video(db, pipeline, 'new', destination=destination)
        assert selected.id == video.id
        assert selected.status == 'new'
        db.refresh(video)
        assert video.status == 'new'
    engine.dispose()


def test_publication_still_prevents_duplicate_selection():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        p = Pipeline(id=str(uuid4()), name='Test', slug=str(uuid4()), timezone='UTC', daily_upload_limit=4)
        d = Destination(id=str(uuid4()), pipeline_id=p.id, name='Test', platform='youtube', enabled=True)
        v = DouyinVideo(id=str(uuid4()), pipeline_id=p.id, video_id='123', title='123',
                        description='', url='https://www.douyin.com/video/123', status='new', is_backlog=False)
        pub = Publication(id=str(uuid4()), pipeline_id=p.id, destination_id=d.id,
                          douyin_video_id=v.id, platform='youtube', status='published', external_post_id='existing')
        db.add_all([p, d, v, pub]); db.commit()
        assert pick_video(db, p, 'new', destination=d) is None
    engine.dispose()


def test_rcuts_video_name_is_forwarded_as_ai_context(tmp_path, monkeypatch):
    from app import douyin
    media = tmp_path / 'video.mp4'
    media.write_bytes(b'video')
    monkeypatch.setattr(douyin, 'call_rcuts_parser', lambda **_: {
        'title': '解析成功', 'video_name': '我已经对你上瘾了',
        'video_url': 'https://example.com/video.mp4',
    })
    monkeypatch.setattr(douyin, 'download_http_video', lambda *_: media)
    result = douyin.try_rcuts_download(
        api_url='https://example.com/parser', parser_name='test',
        source_url='https://www.douyin.com/video/123', job_id=str(uuid4()), share_text=None,
    )
    assert 'video_name: 我已经对你上瘾了' in result.source_context
