import asyncio
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import scheduler, worker
from app.db import Base
from app.models import Destination, Pipeline, VideoJob


class _HangingProcess:
    pid = 4321

    def __init__(self):
        self.returncode = None
        self.killed = False
        self._done = None

    async def wait(self):
        if self._done is None:
            self._done = asyncio.Event()
        await self._done.wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        if self._done is not None:
            self._done.set()


class TestSchedulerCycleIsolation(unittest.TestCase):
    def test_hung_cycle_is_killed_and_reported(self):
        process = _HangingProcess()

        async def fake_exec(*args, **kwargs):
            return process

        async def run():
            with patch.object(
                scheduler.asyncio,
                "create_subprocess_exec",
                fake_exec,
            ):
                return await scheduler.run_scheduler_cycle_isolated(1)

        self.assertFalse(asyncio.run(run()))
        self.assertTrue(process.killed)


class TestOAuthFailureState(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_invalid_grant_disables_destination_and_preserves_reason(self):
        pipeline = Pipeline(
            id=str(uuid4()),
            name="JoyBeat Dance",
            slug="joybeat-dance",
            enabled=True,
        )
        destination = Destination(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            platform="youtube",
            name="JoyBeat Dance",
            enabled=True,
            connected=True,
            credentials=json.dumps({"refresh_token": "revoked"}),
        )
        job = VideoJob(
            id=str(uuid4()),
            source_url="https://v.douyin.com/test/",
            status="uploading",
            pipeline_id=pipeline.id,
            destination_id=destination.id,
        )
        self.db.add_all([pipeline, destination, job])
        self.db.commit()

        with patch.object(worker, "SessionLocal", self.Session):
            worker.mark_failed(
                job.id,
                RuntimeError(
                    "('invalid_grant: Bad Request', "
                    "{'error': 'invalid_grant'})"
                ),
            )

        self.db.expire_all()
        saved = self.db.get(Destination, destination.id)
        self.assertFalse(saved.connected)
        self.assertEqual(
            saved.last_skip_reason,
            scheduler.REASON_OAUTH_REAUTH,
        )
        self.assertEqual(self.db.get(VideoJob, job.id).status, "failed")

        ready, reason = scheduler.is_destination_ready(saved)
        self.assertFalse(ready)
        self.assertEqual(reason, scheduler.REASON_OAUTH_REAUTH)


if __name__ == "__main__":
    unittest.main()
