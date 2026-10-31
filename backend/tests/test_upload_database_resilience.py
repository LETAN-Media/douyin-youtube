"""No external uploads: exercise the worker with real SQLite transactions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import worker
from app.db import Base
from app.db_retry import run_db, is_retriable_db_error
from app.models import Pipeline, Destination, DouyinVideo, Publication, VideoJob
from app.upload_attempts import read_attempt, read_receipt, guard_retry, UploadReconciliationRequired

RESET = 'Hrana: http error: connection error: Connection reset by peer (os error 104)'


@pytest.fixture
def case(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'worker.db'))
    Base.metadata.create_all(engine)
    sessions = []
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    def new_session():
        db = factory()
        sessions.append(db)
        return db
    monkeypatch.setattr(worker, 'SessionLocal', new_session)
    monkeypatch.setattr(worker.settings, 'upload_journal_dir', str(tmp_path / 'receipts'))
    monkeypatch.setattr('app.db_retry.time.sleep', lambda _: None)
    monkeypatch.setattr(worker, 'cleanup_job_files', Mock())
    monkeypatch.setattr(worker, '_upload_policy_block', lambda *_: None)
    monkeypatch.setattr('app.youtube._load_from_json', lambda *_a, **_kw: object())
    monkeypatch.setattr(worker, 'download_video', lambda *_a, **_kw: SimpleNamespace(
        title='Original caption', source_context='Original caption',
        parser_name='test', file_path=tmp_path / 'video.mp4',
    ))
    with factory.begin() as db:
        pipe = Pipeline(id=str(uuid4()), name='Vibe', slug='vibe')
        dest = Destination(id=str(uuid4()), pipeline_id=pipe.id, name='Vibe',
                           platform='youtube', connected=True, credentials='{}')
        video = DouyinVideo(id=str(uuid4()), pipeline_id=pipe.id, video_id='source',
                            url='https://douyin.com/video/source')
        pub = Publication(id=str(uuid4()), pipeline_id=pipe.id, destination_id=dest.id,
                          douyin_video_id=video.id, platform='youtube', status='downloading', publication_mode='manual')
        job = VideoJob(id=str(uuid4()), pipeline_id=pipe.id, destination_id=dest.id,
                       publication_id=pub.id, source_video_id='source', status='downloading',
                       source_url=video.url, title='Smart choices for a better day',
                       description='A thoughtful moment about choosing your direction. #mindset #growth')
        db.add_all([pipe, dest, video, pub, job])
    def upload(**kwargs):
        assert kwargs['db'] is None
        assert all(not db.in_transaction() for db in sessions), 'DB transaction held across upload'
        return 'youtube-id'
    mock = Mock(side_effect=upload)
    monkeypatch.setattr(worker, 'upload_video', mock)
    yield SimpleNamespace(factory=factory, job_id=job.id, pub_id=pub.id, upload=mock, sessions=sessions)
    engine.dispose()


def test_connection_reset_reconnects_new_session_and_backoff(monkeypatch):
    factory = Mock(side_effect=[Mock(), Mock(), Mock()])
    operation = Mock(side_effect=[ValueError(RESET), ValueError(RESET), 'ok'])
    sleep = Mock()
    monkeypatch.setattr('app.db_retry.time.sleep', sleep)
    monkeypatch.setattr('app.db_retry.random.uniform', lambda low, high: high)
    assert run_db(operation, session_factory=factory) == 'ok'
    assert factory.call_count == 3
    assert [x.args[0] for x in sleep.call_args_list] == [0.1, 0.2]
    for call in operation.call_args_list[:2]:
        call.args[0].invalidate.assert_called_once()
        call.args[0].close.assert_called_once()


def test_retry_exhaustion_is_bounded_and_nontransient_not_retried(monkeypatch):
    monkeypatch.setattr('app.db_retry.time.sleep', lambda _: None)
    for error, count in [(ValueError(RESET), 3), (ValueError('bad metadata'), 1)]:
        factory = Mock(side_effect=lambda: Mock())
        operation = Mock(side_effect=error)
        with pytest.raises(ValueError):
            run_db(operation, session_factory=factory)
        assert operation.call_count == count
    assert is_retriable_db_error(ValueError('Hrana: interactive transaction was rolled back because the stream was idle for too long'))


def test_post_upload_database_reset_retries_only_database(case, monkeypatch):
    original = worker._finalize_upload
    calls = []
    def flaky(db, job_id, receipt):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError(RESET)
        return original(db, job_id, receipt)
    monkeypatch.setattr(worker, '_finalize_upload', flaky)
    worker.process_job(case.job_id)
    worker.process_job(case.job_id)
    assert case.upload.call_count == 1
    with case.factory() as db:
        assert db.get(VideoJob, case.job_id).youtube_video_id == 'youtube-id'
        assert db.get(Publication, case.pub_id).status == 'published'
        assert read_attempt(db, case.job_id)['phase'] == 'finalized'


def test_database_down_after_upload_receipt_reconciles_without_upload(case, monkeypatch):
    original = worker._finalize_upload
    monkeypatch.setattr(worker, '_finalize_upload', Mock(side_effect=ValueError(RESET)))
    worker.process_job(case.job_id)
    assert read_receipt(case.job_id)['video_id'] == 'youtube-id'
    with case.factory() as db:
        assert db.get(VideoJob, case.job_id).status == 'upload_unknown'
        assert db.get(Publication, case.pub_id).external_post_id == 'youtube-id'
        with pytest.raises(UploadReconciliationRequired):
            guard_retry(db, db.get(Publication, case.pub_id))
    monkeypatch.setattr(worker, '_finalize_upload', original)
    worker.reconcile_known_uploads()
    assert case.upload.call_count == 1
    with case.factory() as db:
        assert db.get(Publication, case.pub_id).status == 'published'


def test_unknown_upload_never_automatically_requeued(case):
    case.upload.side_effect = TimeoutError('Response lost during upload')
    worker.process_job(case.job_id)
    worker.recover_incomplete_jobs()
    worker.process_job(case.job_id)
    assert case.upload.call_count == 1
    with case.factory() as db:
        assert db.get(VideoJob, case.job_id).status == 'upload_unknown'
        assert not db.get(Publication, case.pub_id).external_post_id


def test_ai_runs_without_database_transaction_and_mismatch_is_advisory(case, monkeypatch):
    with case.factory.begin() as db:
        db.get(VideoJob, case.job_id).title = None
        db.get(VideoJob, case.job_id).description = None
    def ai(*_a, **_kw):
        assert all(not db.in_transaction() for db in case.sessions)
        # No content-match rule in worker validation; unrelated profile hints
        # must not turn Manual Publish into a failed upload.
        return 'A moment of reflection', 'Choosing your own direction thoughtfully. #mindset'
    monkeypatch.setattr(worker, 'generate_youtube_metadata', ai)
    worker.process_job(case.job_id)
    assert case.upload.call_count == 1


def test_preupload_database_failure_never_uploads_or_crashes(case, monkeypatch):
    monkeypatch.setattr(worker, '_load_upload_context', Mock(side_effect=ValueError(RESET)))
    monkeypatch.setattr(worker, 'mark_failed', Mock(side_effect=ValueError(RESET)))
    worker.process_job(case.job_id)
    case.upload.assert_not_called()


def test_legacy_reset_requires_reconciliation_without_id(case):
    with case.factory.begin() as db:
        job = db.get(VideoJob, case.job_id)
        job.status = 'failed'
        job.error = RESET
    with case.factory() as db:
        with pytest.raises(UploadReconciliationRequired):
            guard_retry(db, db.get(Publication, case.pub_id))


def test_lost_commit_acknowledgement_before_upload_holds_without_upload(case, monkeypatch):
    original = Session.commit
    injected = []
    def commit(db):
        attempt = read_attempt(db, case.job_id)
        intent = attempt and attempt['phase'] == 'upload_started'
        original(db)
        if intent and not injected:
            injected.append(1)
            raise ValueError(RESET)
    monkeypatch.setattr(Session, 'commit', commit)
    worker.process_job(case.job_id)
    case.upload.assert_not_called()
    assert injected == [1]
    with case.factory() as db:
        assert read_attempt(db, case.job_id)['phase'] == 'upload_started'
        assert db.get(VideoJob, case.job_id).status == 'upload_unknown'


def test_preupload_failures_can_be_retried_after_reconnect(case):
    with case.factory.begin() as db:
        job = db.get(VideoJob, case.job_id)
        job.status = 'failed'
        job.error = 'BEFORE_UPLOAD: ' + RESET
    with case.factory() as db:
        guard_retry(db, db.get(Publication, case.pub_id))


@pytest.mark.parametrize("source_id", ["source", None])
def test_manual_resubmit_does_not_duplicate_active_job(case, monkeypatch, source_id):
    from app import main
    from app.schemas import ManualPublishRequest
    from fastapi import HTTPException
    from sqlalchemy import select, func
    monkeypatch.setattr(main, 'require_destination', lambda db, did: db.get(Destination, did))
    with case.factory() as db:
        job = db.get(VideoJob, case.job_id)
        payload = ManualPublishRequest(source_url=job.source_url, video_id=source_id,
                                       destination_ids=[job.destination_id], title=job.title, description=job.description)
        with pytest.raises(HTTPException) as caught:
            main.manual_publish_endpoint(payload=payload, db=db)
        assert caught.value.status_code == 409
        assert db.scalar(select(func.count(VideoJob.id))) == 1


def test_database_http_error_reports_503_without_crashing():
    import asyncio, json
    from starlette.requests import Request
    from app.main import database_unavailable_response
    response = asyncio.run(database_unavailable_response(
        Request({'type': 'http', 'method': 'POST', 'path': '/api/manual/publish', 'headers': []}), ValueError(RESET)))
    assert response.status_code == 503
    assert json.loads(response.body)['code'] == 'DATABASE_TEMPORARILY_UNAVAILABLE'
    assert b'Hrana' not in response.body


def test_two_jobs_for_same_publication_cannot_upload_twice(case):
    with case.factory.begin() as db:
        old = db.get(VideoJob, case.job_id)
        second = VideoJob(id=str(uuid4()), pipeline_id=old.pipeline_id, destination_id=old.destination_id,
                          publication_id=old.publication_id, source_video_id=old.source_video_id,
                          source_url=old.source_url, status='downloading', title=old.title, description=old.description)
        db.add(second)
    def upload(**_kwargs):
        worker.process_job(second.id)  # overlapping job sees committed intent
        return 'youtube-id'
    case.upload.side_effect = upload
    worker.process_job(case.job_id)
    assert case.upload.call_count == 1
    with case.factory() as db:
        assert db.get(Publication, case.pub_id).external_post_id == 'youtube-id'
        assert db.get(VideoJob, second.id).status == 'upload_unknown'


def test_lost_finalize_commit_ack_is_idempotent(case, monkeypatch):
    original = Session.commit
    injected = []
    def commit(db):
        attempt = read_attempt(db, case.job_id)
        finalized = attempt and attempt['phase'] == 'finalized'
        original(db)
        if finalized and not injected:
            injected.append(1)
            raise ValueError(RESET)
    monkeypatch.setattr(Session, 'commit', commit)
    worker.process_job(case.job_id)
    worker.process_job(case.job_id)
    assert case.upload.call_count == 1
    assert injected == [1]
    with case.factory() as db:
        assert db.get(Publication, case.pub_id).status == 'published'
        assert db.get(VideoJob, case.job_id).status == 'published'


def test_driver_value_error_invalidates_connection_and_logs_statement_without_parameters(caplog):
    from app.db import _diagnose_database_error
    statement = 'UPDATE publications SET status=? WHERE id=?'
    context = SimpleNamespace(original_exception=ValueError(RESET), statement=statement,
                              parameters={'auth_token': 'do-not-log-this'}, is_disconnect=False)
    _diagnose_database_error(context)
    assert context.is_disconnect
    assert statement in caplog.text
    assert 'do-not-log-this' not in caplog.text


def test_confirmed_quota_rejection_preserves_pause_but_transport_failure_does_not_release_intent(case):
    from app.youtube import YouTubeUploadRejected
    case.upload.side_effect = YouTubeUploadRejected('quotaExceeded: YouTube API quota exceeded')
    worker.process_job(case.job_id)
    with case.factory() as db:
        assert db.get(VideoJob, case.job_id).status == 'pending'
        assert 'YOUTUBE_QUOTA_EXHAUSTED' in db.get(VideoJob, case.job_id).error
        assert read_attempt(db, case.job_id)['phase'] == 'rejected'
        guard_retry(db, db.get(Publication, case.pub_id))
    worker.recover_incomplete_jobs()
    assert case.upload.call_count == 1


def test_turso_pool_connections_allow_sequential_cross_thread_checkout():
    from app.config import Settings
    config = Settings(database_url='sqlite://', admin_token='test',
                      database_provider='turso', turso_url='https://example.turso.io', turso_token='test-token')
    assert config.sqlalchemy_connect_args == {'auth_token': 'test-token', 'check_same_thread': False}


def test_failure_recording_reset_retries_the_whole_database_unit(case, monkeypatch):
    original = worker._find_linked_publication
    calls = []
    def reset_once(db, job):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError(RESET)
        return original(db, job)
    monkeypatch.setattr(worker, '_find_linked_publication', reset_once)
    worker.mark_failed(case.job_id, RuntimeError('BEFORE_UPLOAD: metadata unavailable'))
    assert len(calls) == 2
    with case.factory() as db:
        assert db.get(VideoJob, case.job_id).status == 'failed'
        assert db.get(Publication, case.pub_id).status == 'failed'
    case.upload.assert_not_called()
