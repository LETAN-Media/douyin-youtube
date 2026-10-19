import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.models import Destination, OAuthState, Pipeline
from app.youtube import (
    _load_from_json,
    canonical_authorization_response,
    complete_oauth,
    create_oauth_url,
    public_callback_url,
)

PUBLIC_BASE = "https://douyin-api.toolnet.tech"
CALLBACK = f"{PUBLIC_BASE}/auth/youtube/callback"


class TestCanonicalAuthorizationResponse(unittest.TestCase):
    def setUp(self):
        self._old_base = settings.public_base_url
        settings.public_base_url = PUBLIC_BASE

    def tearDown(self):
        settings.public_base_url = self._old_base

    def test_public_callback_url_is_https(self):
        self.assertEqual(public_callback_url(), CALLBACK)

    def test_http_internal_url_is_rebuilt_on_public_https(self):
        raw = (
            "http://10.128.0.9:8000/auth/youtube/callback"
            "?code=4/abc&state=st4te&scope=email+profile"
        )
        out = canonical_authorization_response(raw)
        self.assertEqual(
            out,
            f"{CALLBACK}?code=4/abc&state=st4te&scope=email+profile",
        )
        self.assertTrue(out.startswith("https://"))

    def test_query_only_input_gets_public_https_prefix(self):
        out = canonical_authorization_response("code=x&state=y")
        self.assertEqual(out, f"{CALLBACK}?code=x&state=y")

    def test_https_url_keeps_single_query(self):
        raw = f"{CALLBACK}?code=x&state=y"
        self.assertEqual(canonical_authorization_response(raw), raw)

    def test_empty_input_rejected(self):
        with self.assertRaises(RuntimeError):
            canonical_authorization_response("")

    def test_http_public_base_url_is_rejected(self):
        settings.public_base_url = "http://internal-host:8000"
        with self.assertRaises(RuntimeError):
            canonical_authorization_response("code=x&state=y")
        with self.assertRaises(RuntimeError):
            public_callback_url()

    def test_create_oauth_url_uses_https_callback(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            pipeline = Pipeline(
                id=str(uuid4()), name="JoyBeat Dance",
                slug=f"joybeat-{uuid4().hex[:8]}", enabled=True,
            )
            db.add(pipeline)
            db.flush()
            dest = Destination(
                id=str(uuid4()), pipeline_id=pipeline.id, platform="youtube",
                name="JoyBeat Dance", enabled=True, daily_upload_limit=6,
                timezone="UTC", upload_slots=["08:00"],
            )
            db.add(dest)
            db.commit()

            old_id = settings.google_client_id
            old_secret = settings.google_client_secret
            settings.google_client_id = "test.apps.googleusercontent.com"
            settings.google_client_secret = "test-secret"
            try:
                url = create_oauth_url(db, destination_id=dest.id)
            finally:
                settings.google_client_id = old_id
                settings.google_client_secret = old_secret

            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["redirect_uri"][0], CALLBACK)
        finally:
            db.close()
            engine.dispose()

    def test_create_oauth_url_rejects_http_public_base(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        old_id = settings.google_client_id
        old_secret = settings.google_client_secret
        settings.public_base_url = "http://localhost:8000"
        settings.google_client_id = "test.apps.googleusercontent.com"
        settings.google_client_secret = "test-secret"
        try:
            with self.assertRaises(RuntimeError):
                create_oauth_url(db, pipeline_id=str(uuid4()))
        finally:
            settings.google_client_id = old_id
            settings.google_client_secret = old_secret
            db.close()
            engine.dispose()


class TestCompleteOauthHttps(unittest.TestCase):
    def setUp(self):
        self._old_base = settings.public_base_url
        settings.public_base_url = PUBLIC_BASE

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        pipeline = Pipeline(
            id=str(uuid4()), name="JoyBeat Dance",
            slug=f"joybeat-{uuid4().hex[:8]}", enabled=True,
        )
        self.db.add(pipeline)
        self.db.flush()
        self.dest = Destination(
            id=str(uuid4()), pipeline_id=pipeline.id, platform="youtube",
            name="JoyBeat Dance", enabled=True, daily_upload_limit=6,
            timezone="UTC", upload_slots=["08:00"],
            connected=True,
            credentials=json.dumps({
                "token": "old-access",
                "refresh_token": "old-revoked-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "old-client",
                "client_secret": "old-secret",
                "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
            }),
        )
        self.db.add(self.dest)
        self.db.add(OAuthState(
            state="st4te",
            pipeline_id=pipeline.id,
            destination_id=self.dest.id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        ))
        self.db.commit()

    def tearDown(self):
        settings.public_base_url = self._old_base
        self.db.close()
        self.engine.dispose()

    def _run_complete(self, refresh_token="new-refresh-token"):
        flow = MagicMock()
        flow.credentials.token = "new-access"
        flow.credentials.refresh_token = refresh_token
        flow.credentials.token_uri = "https://oauth2.googleapis.com/token"
        flow.credentials.client_id = "client-id"
        flow.credentials.client_secret = "client-secret"
        flow.credentials.scopes = ["https://www.googleapis.com/auth/youtube.upload"]

        youtube_client = MagicMock()
        youtube_client.channels.return_value.list.return_value.execute.return_value = {
            "items": [{
                "id": "UCjoybeat",
                "snippet": {"title": "JoyBeat", "thumbnails": {}},
            }]
        }

        with patch("app.youtube.Flow") as FlowMock, patch(
            "app.youtube.build", return_value=youtube_client
        ):
            FlowMock.from_client_config.return_value = flow
            result = complete_oauth(
                self.db,
                state="st4te",
                authorization_response=(
                    "http://10.128.0.9:8000/auth/youtube/callback"
                    "?code=4/abc&state=st4te"
                ),
            )
        return flow, result

    def test_http_authorization_response_rebuilt_before_fetch_token(self):
        flow, result = self._run_complete()

        fetch_kwargs = flow.fetch_token.call_args.kwargs
        self.assertEqual(
            fetch_kwargs["authorization_response"],
            f"{CALLBACK}?code=4/abc&state=st4te",
        )
        self.assertEqual(flow.redirect_uri, CALLBACK)
        self.assertEqual(result["destination_id"], self.dest.id)

    def test_reconnect_replaces_invalid_refresh_token(self):
        self._run_complete(refresh_token="new-refresh-token")

        self.db.refresh(self.dest)
        data = json.loads(self.dest.credentials)
        self.assertEqual(data["refresh_token"], "new-refresh-token")
        self.assertEqual(data["token"], "new-access")
        self.assertTrue(self.dest.connected)
        self.assertEqual(self.dest.external_account_id, "UCjoybeat")
        self.assertEqual(self.dest.external_account_name, "JoyBeat")

    def test_oauth_state_consumed_after_success(self):
        self._run_complete()
        self.assertIsNone(self.db.get(OAuthState, "st4te"))


class TestInvalidGrantMessage(unittest.TestCase):
    def test_invalid_grant_surfaces_reconnect_hint(self):
        raw = json.dumps({
            "token": "expired",
            "refresh_token": "revoked",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        })
        with patch("app.youtube.Credentials") as CredMock:
            cred = CredMock.return_value
            cred.expired = True
            cred.refresh_token = "revoked"
            cred.refresh.side_effect = Exception(
                "('invalid_grant: Token has been expired or revoked.', ...)"
            )
            with self.assertRaises(RuntimeError) as ctx:
                _load_from_json(raw)
        self.assertIn("Reconnect OAuth", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
