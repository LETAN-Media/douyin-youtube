import unittest
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.models import Destination, OAuthState, Pipeline
from app.youtube import create_oauth_url


class TestYoutubeOauthUrl(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        # Fake-but-present Google config (no network is touched by URL gen).
        self._old_id = settings.google_client_id
        self._old_secret = settings.google_client_secret
        settings.google_client_id = "test-client-id.apps.googleusercontent.com"
        settings.google_client_secret = "test-secret"

    def tearDown(self):
        settings.google_client_id = self._old_id
        settings.google_client_secret = self._old_secret
        self.db.close()
        self.engine.dispose()

    def _make_destination(self):
        pipeline = Pipeline(id=str(uuid4()), name="P", slug=f"s-{uuid4().hex[:8]}", enabled=True)
        self.db.add(pipeline)
        self.db.flush()
        dest = Destination(
            id=str(uuid4()), pipeline_id=pipeline.id, platform="youtube",
            name="YouTube A", enabled=True, daily_upload_limit=6,
            timezone="UTC", upload_slots=["08:00"],
        )
        self.db.add(dest)
        self.db.commit()
        return pipeline, dest

    def test_oauth_url_is_real_google_url(self):
        _, dest = self._make_destination()
        url = create_oauth_url(self.db, destination_id=dest.id)

        parsed = urlparse(url)
        self.assertEqual(parsed.hostname, "accounts.google.com")
        q = parse_qs(parsed.query)
        self.assertIn("test-client-id.apps.googleusercontent.com", q.get("client_id", [""])[0])
        self.assertIn("consent", q.get("prompt", [""])[0])
        self.assertIn("select_account", q.get("prompt", [""])[0])
        self.assertEqual(q.get("access_type", [""])[0], "offline")
        self.assertTrue(q.get("state", [""])[0], "state must be present")

    def test_oauth_state_bound_to_destination(self):
        _, dest = self._make_destination()
        url = create_oauth_url(self.db, destination_id=dest.id)
        state = parse_qs(urlparse(url).query).get("state", [""])[0]

        row = self.db.execute(
            select(OAuthState).where(OAuthState.state == state)
        ).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.destination_id, dest.id)

    def test_missing_config_raises_explicitly(self):
        _, dest = self._make_destination()
        settings.google_client_id = ""
        with self.assertRaises(RuntimeError):
            create_oauth_url(self.db, destination_id=dest.id)


if __name__ == "__main__":
    unittest.main()
