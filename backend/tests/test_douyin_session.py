import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import douyin_session as session_module
from app.db import Base
from app import models as _models  # noqa: F401  (register tables)


def make_test_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


class FakePage:
    def __init__(self, modal_visible=False, account=None):
        self._modal_visible = modal_visible
        self._account = account

    def query_selector(self, selector):
        if "扫码登录" in selector:
            return object() if self._modal_visible else None
        if self._account and ("avatar" in selector or "name" in selector or "nick" in selector):
            return FakeElement(self._account)
        return None


class FakeElement:
    def __init__(self, text):
        self._text = text

    def get_attribute(self, name):
        return self._text if name in ("alt", "title") else None

    def inner_text(self):
        return self._text


class FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return self._cookies


LOGIN_COOKIES = [
    {"name": "sessionid", "value": "x" * 32, "domain": ".douyin.com", "path": "/"},
]


class TestSessionCrypto(unittest.TestCase):
    def test_roundtrip(self):
        from app.douyin_session_crypto import (
            decrypt_storage_state,
            encrypt_storage_state,
        )

        raw = json.dumps({"cookies": LOGIN_COOKIES, "origins": []})
        token = encrypt_storage_state(raw)
        self.assertNotIn("sessionid", token)
        self.assertEqual(decrypt_storage_state(token), raw)

    def test_bad_token(self):
        from app.douyin_session_crypto import decrypt_storage_state

        with self.assertRaises(ValueError):
            decrypt_storage_state("not-a-token")


class TestLoginDetection(unittest.TestCase):
    def test_success_requires_cookie_and_dismissed_modal(self):
        ok, _, account = session_module.detect_login_success(
            FakePage(modal_visible=False, account="tester"),
            FakeContext(LOGIN_COOKIES),
        )
        self.assertTrue(ok)
        self.assertEqual(account, "tester")

    def test_modal_still_visible_is_not_success(self):
        ok, reason, _ = session_module.detect_login_success(
            FakePage(modal_visible=True), FakeContext(LOGIN_COOKIES)
        )
        self.assertFalse(ok)
        self.assertIn("modal", reason)

    def test_no_cookie_is_not_success(self):
        # QR display alone never counts — no fake success.
        ok, _, _ = session_module.detect_login_success(
            FakePage(modal_visible=False), FakeContext([])
        )
        self.assertFalse(ok)

    def test_wall_content_detection(self):
        self.assertTrue(
            session_module._login_modal_visible(FakePage(modal_visible=True))
        )
        self.assertFalse(
            session_module._login_modal_visible(FakePage(modal_visible=False))
        )


class TestSessionFlows(unittest.TestCase):
    def setUp(self):
        self.Session, self.engine = make_test_session_factory()
        patcher = patch.object(session_module, "SessionLocal", self.Session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.engine.dispose()

    def test_concurrent_start_rejected(self):
        from datetime import timedelta

        flow_id = str(uuid4())
        session_module._active_flows[flow_id] = {
            "deadline": session_module.utcnow() + timedelta(seconds=60)
        }
        self.addCleanup(session_module._active_flows.pop, flow_id, None)
        with self.assertRaises(ValueError):
            session_module.start_login_flow()

    def test_disconnect_empty(self):
        self.assertEqual(session_module.disconnect_session(), 0)

    def test_aggregate_empty(self):
        status = session_module.get_aggregate_status()
        self.assertFalse(status["connected"])
        self.assertIsNone(status["account_name"])

    def test_flow_status_unknown(self):
        with self.assertRaises(KeyError):
            session_module.get_flow_status(str(uuid4()))

    def test_saved_cookies_roundtrip(self):
        from app.douyin_session_crypto import encrypt_storage_state
        from app.models import DouyinSession

        raw = json.dumps({"cookies": LOGIN_COOKIES, "origins": []})
        with self.Session.begin() as db:
            row = DouyinSession(
                status="connected",
                account_name="tester",
                storage_state_encrypted=encrypt_storage_state(raw),
            )
            db.add(row)
        cookies = session_module.load_saved_session_cookies()
        self.assertEqual(len(cookies), 1)
        self.assertEqual(cookies[0]["name"], "sessionid")

        snapshot = session_module.get_active_session_snapshot()
        self.assertEqual(snapshot["account_name"], "tester")

        aggregate = session_module.get_aggregate_status()
        self.assertTrue(aggregate["connected"])
        self.assertEqual(aggregate["account_name"], "tester")

        removed = session_module.disconnect_session()
        self.assertEqual(removed, 1)
        self.assertFalse(session_module.get_aggregate_status()["connected"])

    def test_validate_without_session_needs_no_browser(self):
        result = session_module.validate_saved_session()
        self.assertFalse(result["valid"])
        self.assertIn("Connect Douyin", result["error"])


if __name__ == "__main__":
    unittest.main()
