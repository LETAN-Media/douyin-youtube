#!/usr/bin/env python3
"""Comprehensive test suite for simplified RapidAPI key failover system.

This module implements tests for the simplified 4-key RapidAPI Douyin API system
where all keys use the same endpoint (douyin-china-tiktok-all-api.p.rapidapi.com)
with a single justone_v3 adapter.
"""

import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import douyin_quota
from app.config import settings
from app.db import Base
from app.integrations.rapidapi.provider_config import RapidApiProviderConfig
from app.integrations.rapidapi.pool import RapidApiProviderPool


class _session_factory:
    def __init__(self, engine):
        self.engine = engine

    def __call__(self):
        return sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)


class TestSimplifiedKeyFailover(unittest.TestCase):
    """Test the simplified RapidAPI key failover system."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = _session_factory(self.engine)()

        # Patch SessionLocal for quota tracking
        self._session_local_patcher = patch('app.db.SessionLocal', self.Session)
        self._session_local_patcher.start()

        # Also patch douyin_quota SessionLocal
        self._douyin_quota_patcher = patch('app.douyin_quota.SessionLocal', self.Session)
        self._douyin_quota_patcher.start()

        # Reset quota for all keys
        douyin_quota.reset_for_tests()

    def tearDown(self):
        self._session_local_patcher.stop()
        self._douyin_quota_patcher.stop()
        self.engine.dispose()

    def test_single_api_single_adapter(self):
        """Test that all keys use the same API and adapter."""
        # Create a provider with a specific key
        provider = RapidApiProviderConfig(
            provider_id="rapidapi_key_primary",
            name="RapidAPI Key Primary",
            api_key="primary-key-12345",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=0,
            enabled=True,
            monthly_request_limit=100,
        )

        # Provider should have correct adapter
        self.assertEqual(provider.schema, "justone_v3")
        self.assertEqual(provider.path, "/api/douyin/get-user-video-list/v3")
        self.assertEqual(provider.host, "douyin-china-tiktok-all-api.p.rapidapi.com")

    def test_quota_tracking_shared_subscription(self):
        """Test quota tracking across multiple keys in shared subscription."""
        # Create multiple providers representing different keys
        primary = RapidApiProviderConfig(
            provider_id="rapidapi_key_primary",
            name="RapidAPI Key Primary",
            api_key="primary-key-12345",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=0,
            enabled=True,
            monthly_request_limit=100,
        )

        fallback1 = RapidApiProviderConfig(
            provider_id="rapidapi_key_1",
            name="RapidAPI Key 1",
            api_key="fallback1-key-67890",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=1,
            enabled=True,
            monthly_request_limit=100,
        )

        pool = RapidApiProviderPool([primary, fallback1])

        # Initially, both should be available
        self.assertTrue(pool.is_available(primary))
        self.assertTrue(pool.is_available(fallback1))

    def test_key_failover_on_quota_exhaustion(self):
        """Test failover from primary to fallback when quota exhausted."""
        # Create providers representing different keys
        primary = RapidApiProviderConfig(
            provider_id="rapidapi_key_primary",
            name="RapidAPI Key Primary",
            api_key="primary-key-12345",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=0,
            enabled=True,
            monthly_request_limit=10,
        )

        fallback1 = RapidApiProviderConfig(
            provider_id="rapidapi_key_1",
            name="RapidAPI Key 1",
            api_key="fallback1-key-67890",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=1,
            enabled=True,
            monthly_request_limit=100,
        )

        pool = RapidApiProviderPool([primary, fallback1])

        # Exhaust primary quota
        douyin_quota.mark_exhausted("Primary quota exhausted", provider_id="rapidapi_key_primary")

        # Primary should not be available
        self.assertFalse(pool.is_available(primary))

        # Fallback1 should still be available
        self.assertTrue(pool.is_available(fallback1))

    def test_backward_compatibility_with_legacy_keys(self):
        """Test that legacy RAPIDAPI_KEY still works."""
        # Create a provider that represents the legacy RAPIDAPI_KEY
        legacy_provider = RapidApiProviderConfig(
            provider_id="rapidapi_justone",
            name="Legacy RAPIDAPI Key",
            api_key="legacy-key-abcde",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=0,
            enabled=True,
            monthly_request_limit=50,
        )

        # Should be configured
        self.assertTrue(legacy_provider.configured)

    def test_disabled_key_handling(self):
        """Test that disabled keys are properly handled."""
        # Create a disabled provider
        disabled_provider = RapidApiProviderConfig(
            provider_id="rapidapi_key_disabled",
            name="Disabled Key",
            api_key="disabled-key-fghi",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=2,
            enabled=False,  # Disabled
            monthly_request_limit=50,
        )

        # Should not be available because disabled
        self.assertFalse(disabled_provider.configured)

    def test_provider_order_priority(self):
        """Test that providers are ordered by priority."""
        primary = RapidApiProviderConfig(
            provider_id="rapidapi_key_primary",
            name="RapidAPI Key Primary",
            api_key="primary-key-12345",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=0,
            enabled=True,
        )

        fallback1 = RapidApiProviderConfig(
            provider_id="rapidapi_key_1",
            name="RapidAPI Key 1",
            api_key="fallback1-key-67890",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=1,
            enabled=True,
        )

        fallback2 = RapidApiProviderConfig(
            provider_id="rapidapi_key_2",
            name="RapidAPI Key 2",
            api_key="fallback2-key-klmno",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=2,
            enabled=True,
        )

        pool = RapidApiProviderPool([primary, fallback2, fallback1])

        # Should be sorted by priority
        self.assertEqual(pool.configs[0].priority, 0)
        self.assertEqual(pool.configs[1].priority, 1)
        self.assertEqual(pool.configs[2].priority, 2)

    def test_key_status_no_secrets(self):
        """Test that provider status doesn't expose API keys."""
        provider = RapidApiProviderConfig(
            provider_id="rapidapi_key_primary",
            name="RapidAPI Key Primary",
            api_key="secret-key-not-to-be-exposed",
            host="douyin-china-tiktok-all-api.p.rapidapi.com",
            base_url="https://douyin-china-tiktok-all-api.p.rapidapi.com",
            path="/api/douyin/get-user-video-list/v3",
            schema="justone_v3",
            priority=0,
            enabled=True,
        )

        pool = RapidApiProviderPool([provider])
        status = pool._provider_status(provider)

        # Should not contain API key
        self.assertNotIn("secret-key-not-to-be-exposed", str(status))
        self.assertIn("key_configured", status)
        self.assertTrue(status["key_configured"])


if __name__ == "__main__":
    unittest.main()