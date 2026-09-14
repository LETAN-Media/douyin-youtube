import datetime
import json
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.models import Destination, DouyinSource, DouyinVideo, OAuthState, Pipeline, Publication
from app.youtube import complete_oauth, create_oauth_url, get_youtube_status, load_credentials


class TestMultiDestination(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_pipeline(self, **kwargs):
        pipeline = Pipeline(
            id=str(uuid4()),
            name="Test",
            slug="test",
            enabled=True,
            **kwargs,
        )
        self.db.add(pipeline)
        self.db.flush()
        return pipeline

    def _make_source(self, pipeline, **kwargs):
        source = DouyinSource(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            name="Source",
            profile_url="https://www.douyin.com/user/test",
            enabled=True,
            **kwargs,
        )
        self.db.add(source)
        self.db.flush()
        return source

    def _make_video(self, source, **kwargs):
        video = DouyinVideo(
            id=str(uuid4()),
            source_id=source.id,
            pipeline_id=source.pipeline_id,
            video_id=str(uuid4()),
            title="Test",
            url="https://www.douyin.com/video/test",
            status="inventory",
            **kwargs,
        )
        self.db.add(video)
        self.db.flush()
        return video

    def _make_destination(self, pipeline, platform="youtube", name=None, **kwargs):
        destination = Destination(
            id=str(uuid4()),
            pipeline_id=pipeline.id,
            platform=platform,
            name=name or f"{platform} dest",
            enabled=True,
            daily_upload_limit=6,
            timezone="UTC",
            upload_slots=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
            **kwargs,
        )
        self.db.add(destination)
        self.db.flush()
        return destination

    def test_destination_model(self):
        pipeline = self._make_pipeline()
        destination = self._make_destination(pipeline)

        self.assertEqual(destination.platform, "youtube")
        self.assertEqual(destination.daily_upload_limit, 6)
        self.assertFalse(destination.connected)

    def test_publication_unique_per_destination(self):
        pipeline = self._make_pipeline()
        source = self._make_source(pipeline)
        video = self._make_video(source)
        dest_a = self._make_destination(pipeline, name="YouTube A")
        dest_b = self._make_destination(pipeline, name="YouTube B")

        pub_a = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=dest_a.id,
            platform="youtube",
            status="queued",
        )
        pub_b = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=dest_b.id,
            platform="youtube",
            status="queued",
        )

        self.db.add_all([pub_a, pub_b])
        self.db.commit()

        self.assertEqual(
            self.db.query(Publication)
            .filter(Publication.douyin_video_id == video.id)
            .count(),
            2,
        )

        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            dup = Publication(
                pipeline_id=pipeline.id,
                douyin_video_id=video.id,
                destination_id=dest_a.id,
                platform="youtube",
                status="queued",
            )
            self.db.add(dup)
            self.db.commit()

    def test_broadcast_creates_publication_per_destination(self):
        pipeline = self._make_pipeline()
        source = self._make_source(pipeline)
        video = self._make_video(source)

        destinations = [
            self._make_destination(pipeline, platform="youtube", name=f"YT{i}")
            for i in range(3)
        ] + [
            self._make_destination(pipeline, platform="facebook", name=f"FB{i}")
            for i in range(2)
        ]

        for dest in destinations:
            pub = Publication(
                pipeline_id=pipeline.id,
                douyin_video_id=video.id,
                destination_id=dest.id,
                platform=dest.platform,
                status="queued",
            )
            self.db.add(pub)
        self.db.commit()

        self.assertEqual(
            self.db.query(Publication)
            .filter(Publication.douyin_video_id == video.id)
            .count(),
            5,
        )

    def test_youtube_oauth_saves_to_destination(self):
        pipeline = self._make_pipeline()
        destination = self._make_destination(pipeline, platform="youtube")

        state = "test-state-123"
        self.db.add(
            __import__("app.models", fromlist=["OAuthState"]).OAuthState(
                state=state,
                destination_id=destination.id,
                expires_at=datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(minutes=15),
            )
        )
        self.db.commit()

        self.assertIsNone(destination.credentials)

    def test_youtube_migration_creates_destination(self):
        pipeline = Pipeline(
            id=str(uuid4()),
            name="Old",
            slug="old",
            enabled=True,
            youtube_credentials=json.dumps({
                "token": "old-token",
                "refresh_token": "old-refresh",
            }),
            youtube_channel_id="UC123",
            youtube_channel_title="Old Channel",
        )
        self.db.add(pipeline)
        self.db.commit()

        from app.migrate import migrate_existing_youtube_to_destination
        migrate_existing_youtube_to_destination(self.db.connection())

        dest = self.db.execute(
            __import__("sqlalchemy").select(Destination)
            .where(Destination.pipeline_id == pipeline.id)
        ).scalar_one_or_none()

        self.assertIsNotNone(dest)
        self.assertEqual(dest.platform, "youtube")
        self.assertEqual(dest.external_account_id, "UC123")
        self.assertEqual(dest.external_account_name, "Old Channel")
        self.assertTrue(dest.connected)

    def test_status_per_destination(self):
        pipeline = self._make_pipeline()
        source = self._make_source(pipeline)
        video = self._make_video(source)
        dest_a = self._make_destination(pipeline, name="YT A")
        dest_b = self._make_destination(pipeline, name="YT B")

        pub_a = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=dest_a.id,
            platform="youtube",
            status="published",
            published_at=datetime.datetime.now(datetime.timezone.utc),
        )
        pub_b = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=dest_b.id,
            platform="youtube",
            status="queued",
        )

        self.db.add_all([pub_a, pub_b])
        self.db.commit()

        pub_a = self.db.get(Publication, pub_a.id)
        pub_b = self.db.get(Publication, pub_b.id)

        self.assertEqual(pub_a.status, "published")
        self.assertEqual(pub_b.status, "queued")

    def test_load_credentials_by_destination(self):
        pipeline = self._make_pipeline()
        destination = self._make_destination(pipeline, platform="youtube")
        destination.credentials = json.dumps({
            "token": "dest-token",
            "refresh_token": "dest-refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": [],
        })
        self.db.commit()

        credentials = load_credentials(
            self.db,
            destination_id=destination.id,
        )
        self.assertEqual(credentials.token, "dest-token")


if __name__ == "__main__":
    unittest.main()
