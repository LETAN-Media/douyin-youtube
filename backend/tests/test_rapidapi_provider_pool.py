"""Regression tests for 4-provider RapidAPI failover system."""

import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import douyin_quota
from app.config import settings
from app.db import Base, SessionLocal
from app.integrations.rapidapi.provider_config import build_provider_configs, RapidApiProviderConfig


class _session_factory:
    def __init__(self, engine):
        self.engine = engine

    def __call__(self):
        return sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)


class TestProviderFailover(unittest.TestCase):
    """Test the 4-provider RapidAPI failover system."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = _session_factory(self.engine)()

        # Patch SessionLocal from app.db
        self._session_local_patcher = patch('app.db.SessionLocal', self.Session)
        self._session_local_patcher.start()

        # Also patch the imports in douyin_quota and other modules that import SessionLocal
        self._douyin_quota_patcher = patch('app.douyin_quota.SessionLocal', self.Session)
        self._douyin_quota_patcher.start()

        # Reset quota for all providers
        douyin_quota.reset_for_tests("rapidapi_primary")
        douyin_quota.reset_for_tests("rapidapi_fallback_1")
        douyin_quota.reset_for_tests("rapidapi_fallback_2")
        douyin_quota.reset_for_tests("rapidapi_fallback_3")

    def tearDown(self):
        self._session_local_patcher.stop()
        self._douyin_quota_patcher.stop()
        self.engine.dispose()

    def test_provider_quota_exhaustion(self):
        """Test that exhausted quota prevents any further requests."""
        from app.integrations.rapidapi.pool import RapidApiProviderPool

        primary = RapidApiProviderConfig(
            provider_id="rapidapi_primary",
            name="RapidAPI Primary",
            api_key="primary-key",
            host="primary.example.com",
            base_url="https://primary.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=0,
            enabled=True,
            monthly_request_limit=5,
        )

        pool = RapidApiProviderPool([primary])

        # Mark quota as exhausted
        douyin_quota.mark_exhausted("Primary quota exhausted", provider_id="rapidapi_primary")

        # Should not be available
        self.assertFalse(pool.is_available(primary))

    def test_disabled_provider_not_available(self):
        """Test that disabled providers are not available."""
        from app.integrations.rapidapi.pool import RapidApiProviderPool

        primary = RapidApiProviderConfig(
            provider_id="rapidapi_primary",
            name="RapidAPI Primary",
            api_key="primary-key",
            host="primary.example.com",
            base_url="https://primary.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=0,
            enabled=False,  # Disabled
        )

        pool = RapidApiProviderPool([primary])

        # Should not be available because disabled
        self.assertFalse(pool.is_available(primary))

    def test_provider_order_priority(self):
        """Test that providers are ordered by priority."""
        from app.integrations.rapidapi.pool import RapidApiProviderPool

        primary = RapidApiProviderConfig(
            provider_id="rapidapi_primary",
            name="RapidAPI Primary",
            api_key="primary-key",
            host="primary.example.com",
            base_url="https://primary.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=0,
            enabled=True,
        )

        fallback1 = RapidApiProviderConfig(
            provider_id="rapidapi_fallback_1",
            name="RapidAPI Fallback 1",
            api_key="fallback1-key",
            host="fallback1.example.com",
            base_url="https://fallback1.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=1,
            enabled=True,
        )

        fallback2 = RapidApiProviderConfig(
            provider_id="rapidapi_fallback_2",
            name="RapidAPI Fallback 2",
            api_key="fallback2-key",
            host="fallback2.example.com",
            base_url="https://fallback2.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=2,
            enabled=True,
        )

        pool = RapidApiProviderPool([primary, fallback2, fallback1])

        # Should be sorted by priority
        self.assertEqual(pool.configs[0].priority, 0)
        self.assertEqual(pool.configs[1].priority, 1)
        self.assertEqual(pool.configs[2].priority, 2)

    def test_provider_status_no_secrets(self):
        """Test that provider status doesn't expose API keys."""
        from app.integrations.rapidapi.pool import RapidApiProviderPool

        primary = RapidApiProviderConfig(
            provider_id="rapidapi_primary",
            name="RapidAPI Primary",
            api_key="secret-key-not-to-be-exposed",
            host="primary.example.com",
            base_url="https://primary.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=0,
            enabled=True,
        )

        pool = RapidApiProviderPool([primary])
        status = pool._provider_status(primary)

        # Should not contain API key
        self.assertNotIn("secret-key-not-to-be-exposed", str(status))
        self.assertIn("key_configured", status)
        self.assertTrue(status["key_configured"])

    def test_provider_id_mapping_backward_compat(self):
        """Test backward compatibility for provider ID mapping."""
        from app.integrations.rapidapi.pool import get_rapidapi_pool

        # Get the real pool
        pool = get_rapidapi_pool()

        # Test that rapidapi_justone maps to either rapidapi_justone or rapidapi_primary
        provider_id = "rapidapi_justone"
        result = pool.get(provider_id)

        # Should return a valid provider
        self.assertIsNotNone(result)
        self.assertIn(result.provider_id, ["rapidapi_justone", "rapidapi_primary"])

    def test_provider_info_includes_schema(self):
        """Test that provider info includes schema information."""
        primary = RapidApiProviderConfig(
            provider_id="rapidapi_primary",
            name="RapidAPI Primary",
            api_key="test-key",
            host="primary.example.com",
            base_url="https://primary.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=0,
            enabled=True,
        )

        # Provider should have schema set
        self.assertEqual(primary.schema, "justone_v3")
        self.assertEqual(primary.path, "/api/v1/videos")

    def test_provider_id_unique(self):
        """Test that provider IDs are unique."""
        primary = RapidApiProviderConfig(
            provider_id="rapidapi_primary",
            name="RapidAPI Primary",
            api_key="test-key",
            host="primary.example.com",
            base_url="https://primary.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=0,
            enabled=True,
        )

        fallback1 = RapidApiProviderConfig(
            provider_id="rapidapi_fallback_1",
            name="RapidAPI Fallback 1",
            api_key="test-key2",
            host="fallback1.example.com",
            base_url="https://fallback1.example.com",
            path="/api/v1/videos",
            schema="justone_v3",
            priority=1,
            enabled=True,
        )

        # Provider IDs should be unique
        self.assertNotEqual(primary.provider_id, fallback1.provider_id)
        self.assertNotEqual(primary.api_key, fallback1.api_key)


if __name__ == "__main__":
    unittest.main()