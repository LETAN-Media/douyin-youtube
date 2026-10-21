import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.models import Destination, OAuthState, Pipeline, Workspace
from app.youtube import (
    OAuthFlowError,
    _load_from_json,
    complete_oauth,
    create_oauth_url,
)

PUBLIC_BASE = "https://douyin-api.toolnet.tech"


def _credentials(refresh_token="old-refresh-token"):
    return json.dumps(
        {
            "token": "old-access",
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "old-client",
            "client_secret": "old-secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        }
    )


class OAuthStateHardeningTest(unittest.TestCase):
    def setUp(self):
        self._old_base = settings.public_base_url
        self._old_client_id = settings.google_client_id
        self._old_client_secret = settings.google_client_secret
        settings.public_base_url = PUBLIC_BASE
        settings.google_client_id = "test.apps.googleusercontent.com"
        settings.google_client_secret = "test-secret"

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.db.add_all(
            [
                Workspace(id="ws-a", name="A"),
                Workspace(id="ws-b", name="B"),
            ]
        )
        self.pipeline = Pipeline(
            id=str(uuid4()),
            name="JoyBeat",
            slug=f"joybeat-{uuid4().hex[:8]}",
            enabled=True,
            workspace_id="ws-a",
        )
        self.db.add(self.pipeline)
        self.db.flush()
        self.dest = Destination(
            id=str(uuid4()),
            pipeline_id=self.pipeline.id,
            platform="youtube",
            name="JoyBeat",
            enabled=True,
            daily_upload_limit=6,
            timezone="UTC",
            upload_slots=["08:00"],
            connected=True,
            credentials=_credentials(),
            workspace_id="ws-a",
        )
        self.db.add(self.dest)
        self.db.commit()

    def tearDown(self):
        settings.public_base_url = self._old_base
        settings.google_client_id = self._old_client_id
        settings.google_client_secret = self._old_client_secret
        self.db.close()
        self.engine.dispose()

    def _add_state(self, state="st", **overrides):
        values = {
            "state": state,
            "pipeline_id": self.pipeline.id,
            "destination_id": self.dest.id,
            "workspace_id": "ws-a",
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ),
        }
        values.update(overrides)
        self.db.add(OAuthState(**values))
        self.db.commit()

    def _flow(self, state="st", refresh_token="new-refresh-token", error=None):
        flow = MagicMock()
        flow.oauth2session.state = state
        flow.credentials.token = "new-access"
        flow.credentials.refresh_token = refresh_token
        flow.credentials.token_uri = "https://oauth2.googleapis.com/token"
        flow.credentials.client_id = "client-id"
        flow.credentials.client_secret = "client-secret"
        flow.credentials.scopes = [
            "https://www.googleapis.com/auth/youtube.upload"
        ]
        if error is not None:
            flow.fetch_token.side_effect = error
        return flow

    def _youtube(self, items=None):
        youtube = MagicMock()
        if items is None:
            items = [
                {
                    "id": "UCjoybeat",
                    "snippet": {"title": "JoyBeat", "thumbnails": {}},
                }
            ]
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": items
        }
        return youtube

    def _complete(
        self,
        state="st",
        code="code-1",
        flow=None,
        youtube=None,
        **kwargs,
    ):
        flow = flow or self._flow(state)
        youtube = youtube or self._youtube()
        with patch("app.youtube.Flow") as flow_mock, patch(
            "app.youtube.build", return_value=youtube
        ):
            flow_mock.from_client_config.return_value = flow
            result = complete_oauth(
                self.db,
                state=state,
                code=code,
                **kwargs,
            )
        return flow, result

    def test_create_oauth_url_persists_same_state_as_url(self):
        url = create_oauth_url(
            self.db,
            destination_id=self.dest.id,
            workspace_id="ws-a",
        )
        row = self.db.execute(select(OAuthState)).scalars().one()
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["state"][0], row.state)
        self.assertEqual(row.destination_id, self.dest.id)
        self.assertEqual(row.workspace_id, "ws-a")
        self.assertEqual(query["redirect_uri"][0], PUBLIC_BASE + "/auth/youtube/callback")

    def test_valid_state_saves_token_to_correct_destination(self):
        self._add_state()
        _flow, result = self._complete()

        self.db.refresh(self.dest)
        data = json.loads(self.dest.credentials)
        self.assertEqual(data["token"], "new-access")
        self.assertEqual(data["refresh_token"], "new-refresh-token")
        self.assertEqual(self.dest.external_account_id, "UCjoybeat")
        self.assertEqual(self.dest.external_account_name, "JoyBeat")
        self.assertTrue(self.dest.connected)
        self.assertEqual(result["destination_id"], self.dest.id)
        self.assertIsNone(self.db.get(OAuthState, "st"))

    def test_unknown_state_rejected_and_token_unchanged(self):
        old_credentials = self.dest.credentials
        with self.assertRaises(OAuthFlowError) as ctx:
            complete_oauth(self.db, state="tampered", code="code-1")
        self.assertEqual(ctx.exception.code, "oauth_state_invalid")
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)

    def test_expired_state_rejected_and_removed(self):
        self._add_state(
            state="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        with self.assertRaises(OAuthFlowError) as ctx:
            complete_oauth(self.db, state="expired", code="code-1")
        self.assertEqual(ctx.exception.code, "oauth_state_expired")
        self.assertIsNone(self.db.get(OAuthState, "expired"))

    def test_duplicate_callback_cannot_exchange_code_twice(self):
        self._add_state()
        first_flow, _ = self._complete()

        with self.assertRaises(OAuthFlowError) as ctx:
            complete_oauth(self.db, state="st", code="code-2")
        self.assertEqual(ctx.exception.code, "oauth_state_invalid")
        self.assertEqual(first_flow.fetch_token.call_count, 1)

    def test_destination_override_mismatch_is_rejected(self):
        other = Destination(
            id=str(uuid4()),
            pipeline_id=self.pipeline.id,
            platform="youtube",
            name="Other",
            enabled=True,
            daily_upload_limit=6,
            timezone="UTC",
            upload_slots=["08:00"],
            workspace_id="ws-a",
        )
        self.db.add(other)
        self.db.commit()
        self._add_state(state="dm")
        old_credentials = self.dest.credentials

        with self.assertRaises(OAuthFlowError) as ctx:
            complete_oauth(
                self.db,
                state="dm",
                code="code-1",
                destination_id=other.id,
            )
        self.assertEqual(
            ctx.exception.code,
            "oauth_state_destination_mismatch",
        )
        self.assertIsNone(self.db.get(OAuthState, "dm"))
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)
        self.assertIsNone(other.credentials)

    def test_pipeline_override_mismatch_is_rejected(self):
        other_pipeline = Pipeline(
            id=str(uuid4()),
            name="Other",
            slug=f"other-{uuid4().hex[:8]}",
            enabled=True,
            workspace_id="ws-a",
        )
        self.db.add(other_pipeline)
        self.db.commit()
        self._add_state(state="pm")

        with self.assertRaises(OAuthFlowError) as ctx:
            complete_oauth(
                self.db,
                state="pm",
                code="code-1",
                pipeline_id=other_pipeline.id,
            )
        self.assertEqual(
            ctx.exception.code,
            "oauth_state_pipeline_mismatch",
        )
        self.assertIsNone(self.db.get(OAuthState, "pm"))

    def test_cross_workspace_state_rejected(self):
        other_pipeline = Pipeline(
            id=str(uuid4()),
            name="Other",
            slug=f"other-{uuid4().hex[:8]}",
            enabled=True,
            workspace_id="ws-b",
        )
        self.db.add(other_pipeline)
        self.db.flush()
        other_dest = Destination(
            id=str(uuid4()),
            pipeline_id=other_pipeline.id,
            platform="youtube",
            name="Other",
            enabled=True,
            daily_upload_limit=6,
            timezone="UTC",
            upload_slots=["08:00"],
            workspace_id="ws-b",
        )
        self.db.add(other_dest)
        self.db.commit()
        self._add_state(
            state="tenant",
            pipeline_id=other_pipeline.id,
            destination_id=other_dest.id,
            workspace_id="ws-a",
        )

        with self.assertRaises(OAuthFlowError) as ctx:
            complete_oauth(self.db, state="tenant", code="code-1")
        self.assertEqual(ctx.exception.code, "oauth_tenant_mismatch")
        self.assertIsNone(self.db.get(OAuthState, "tenant"))
        self.assertIsNone(other_dest.credentials)

    def test_internal_flow_state_mismatch_is_rejected(self):
        self._add_state(state="internal")
        old_credentials = self.dest.credentials
        flow = self._flow(state="internal")
        flow.oauth2session.state = "different-state"

        with self.assertRaises(OAuthFlowError) as ctx:
            self._complete(state="internal", code="code-1", flow=flow)
        self.assertEqual(
            ctx.exception.code,
            "oauth_state_internal_mismatch",
        )
        self.assertEqual(flow.fetch_token.call_count, 0)
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)
        self.assertIsNone(self.db.get(OAuthState, "internal"))

    def test_invalid_grant_keeps_old_token(self):
        self._add_state(state="grant")
        old_credentials = self.dest.credentials
        flow = self._flow(
            state="grant",
            error=Exception(
                "('invalid_grant: Token has been expired or revoked.', ...)"
            ),
        )

        with self.assertRaises(OAuthFlowError) as ctx:
            self._complete(state="grant", code="code-1", flow=flow)
        self.assertEqual(ctx.exception.code, "oauth_invalid_grant")
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)
        self.assertIsNone(self.db.get(OAuthState, "grant"))

    def test_missing_refresh_token_keeps_old_token(self):
        self.dest.credentials = json.dumps(
            {
                "token": "old-access",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "old-client",
                "client_secret": "old-secret",
                "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
            }
        )
        self.db.commit()
        old_credentials = self.dest.credentials
        self._add_state(state="norefresh")

        with self.assertRaises(OAuthFlowError) as ctx:
            self._complete(
                state="norefresh",
                code="code-1",
                flow=self._flow(state="norefresh", refresh_token=None),
            )
        self.assertEqual(
            ctx.exception.code,
            "oauth_missing_refresh_token",
        )
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)

    def test_no_channel_found_keeps_old_token(self):
        self._add_state(state="nochannel")
        old_credentials = self.dest.credentials

        with self.assertRaises(OAuthFlowError) as ctx:
            self._complete(
                state="nochannel",
                code="code-1",
                youtube=self._youtube(items=[]),
            )
        self.assertEqual(
            ctx.exception.code,
            "oauth_channel_not_found",
        )
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)

    def test_permission_denied_keeps_old_token(self):
        from googleapiclient.errors import HttpError

        self._add_state(state="denied")
        old_credentials = self.dest.credentials
        response = MagicMock()
        response.status = 403
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.side_effect = (
            HttpError(response, b"{}")
        )

        with self.assertRaises(OAuthFlowError) as ctx:
            self._complete(
                state="denied",
                code="code-1",
                youtube=youtube,
            )
        self.assertEqual(
            ctx.exception.code,
            "oauth_permission_denied",
        )
        self.db.refresh(self.dest)
        self.assertEqual(self.dest.credentials, old_credentials)

    def test_saved_refresh_token_can_refresh(self):
        raw = _credentials("rt")
        with patch("app.youtube.Credentials") as credentials_mock:
            credentials = credentials_mock.return_value
            credentials.expired = True
            credentials.refresh_token = "rt"
            credentials.token = "old-access"

            def _refresh(_request):
                credentials.token = "refreshed-access"

            credentials.refresh.side_effect = _refresh
            loaded = _load_from_json(raw)

        credentials.refresh.assert_called_once()
        self.assertIs(loaded, credentials)
        self.assertEqual(loaded.token, "refreshed-access")


class OAuthCallbackEndpointTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from sqlalchemy.pool import StaticPool

        from app.db import get_db
        from app.main import app

        self._old_frontend = settings.frontend_url
        settings.frontend_url = "https://douyin.toolnet.tech"

        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.db.add(Workspace(id="ws-a", name="A"))
        self.pipeline = Pipeline(
            id=str(uuid4()),
            name="JoyBeat",
            slug=f"joybeat-{uuid4().hex[:8]}",
            enabled=True,
            workspace_id="ws-a",
        )
        self.db.add(self.pipeline)
        self.db.flush()
        self.dest = Destination(
            id=str(uuid4()),
            pipeline_id=self.pipeline.id,
            platform="youtube",
            name="JoyBeat",
            enabled=True,
            daily_upload_limit=6,
            timezone="UTC",
            upload_slots=["08:00"],
            workspace_id="ws-a",
        )
        self.db.add(self.dest)
        self.db.commit()

        def _override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = _override_db
        self.client = TestClient(app)
        self.app = app

    def tearDown(self):
        self.app.dependency_overrides.clear()
        settings.frontend_url = self._old_frontend
        self.db.close()
        self.engine.dispose()

    def _add_state(self, state, expires_in=600):
        self.db.add(
            OAuthState(
                state=state,
                pipeline_id=self.pipeline.id,
                destination_id=self.dest.id,
                workspace_id="ws-a",
                expires_at=(
                    datetime.now(timezone.utc)
                    + timedelta(seconds=expires_in)
                ),
            )
        )
        self.db.commit()

    def test_access_denied_redirects_with_error_code(self):
        self._add_state("denied-st")
        response = self.client.get(
            "/auth/youtube/callback"
            "?error=access_denied&state=denied-st",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f"/pipelines/{self.pipeline.id}",
            response.headers["location"],
        )
        self.assertIn("oauth_error=oauth_access_denied", response.headers["location"])
        self.assertIsNone(self.db.get(OAuthState, "denied-st"))

    def test_unknown_state_redirects_to_channels_error(self):
        response = self.client.get(
            "/auth/youtube/callback?state=missing&code=code-1",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/channels?", response.headers["location"])
        self.assertIn("oauth_error=oauth_state_invalid", response.headers["location"])

    def test_missing_code_redirects_with_error_code(self):
        self._add_state("nocode-st")
        response = self.client.get(
            "/auth/youtube/callback?state=nocode-st",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "oauth_error=oauth_callback_missing_code",
            response.headers["location"],
        )
        self.assertIsNone(self.db.get(OAuthState, "nocode-st"))


if __name__ == "__main__":
    unittest.main()
