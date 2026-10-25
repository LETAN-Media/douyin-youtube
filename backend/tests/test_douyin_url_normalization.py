"""Tests for Douyin profile URL normalization (15 key cases)."""

import sys
import unittest
from unittest.mock import patch

from app.douyin_url import parse_douyin_profile_url, parse_profile_url, DouyinUrlError
from app.models import DouyinSource
from app.db import Base, SessionLocal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class TestDouyinUrlNormalization(unittest.TestCase):
    """Test all 15 key cases for Douyin URL normalization."""

    def setUp(self):
        # Use in-memory SQLite database for tests
        self.engine = create_engine("sqlite:///:memory:")
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(self.engine)

        # Patch SessionLocal to use our test session
        self.original_session_local = SessionLocal
        self.patcher = patch("app.db.SessionLocal", self.Session)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_01_standard_douyin_com_user(self):
        """Standard www.douyin.com/user/{sec_uid} - the primary case."""
        result = parse_douyin_profile_url("https://www.douyin.com/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_02_mobile_douyin_com_user(self):
        """Mobile version m.douyin.com/user/{sec_uid}."""
        result = parse_douyin_profile_url("https://m.douyin.com/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_03_iesdouyin_com_share_user(self):
        """iesdouyin.com/share/user/{sec_uid} with query params."""
        result = parse_douyin_profile_url("https://iesdouyin.com/share/user/MS4wLjABAAAA_test?foo=bar&source=share")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_04_apex_douyin_com_user(self):
        """Apex douyin.com/user/{sec_uid} (without www)."""
        result = parse_douyin_profile_url("https://douyin.com/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_05_http_scheme(self):
        """HTTP scheme (should work with redirect normalization)."""
        result = parse_douyin_profile_url("http://www.douyin.com/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_06_missing_scheme(self):
        """URL without scheme should be normalized."""
        result = parse_douyin_profile_url("www.douyin.com/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_07_sec_uid_alphanumeric_underscore_hyphen(self):
        """SecUid with alphanumeric, underscore, and hyphen characters."""
        result = parse_douyin_profile_url("https://www.douyin.com/user/MS4wLjAB_123-ABC")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjAB_123-ABC")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjAB_123-ABC")

    def test_08_whitespace_trim(self):
        """URL with surrounding whitespace should be trimmed."""
        result = parse_douyin_profile_url("  https://www.douyin.com/user/MS4wLjABAAAA_test  ")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_09_empty_string(self):
        """Empty string should return None."""
        result = parse_douyin_profile_url("")
        self.assertIsNone(result)

    def test_10_whitespace_only(self):
        """Whitespace-only string should return None."""
        result = parse_douyin_profile_url("   ")
        self.assertIsNone(result)

    def test_11_parse_profile_url_dict_wrapper(self):
        """parse_profile_url dict-style wrapper should work."""
        result = parse_profile_url("https://www.douyin.com/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("sec_uid"), "MS4wLjABAAAA_test")
        self.assertEqual(result.get("clean_url"), "https://www.douyin.com/user/MS4wLjABAAAA_test")
        self.assertEqual(result.get("canonical"), "https://www.douyin.com/user/MS4wLjABAAAA_test")

    def test_12_video_url_rejection_standard(self):
        """Standard video URL should raise DouyinUrlError."""
        with self.assertRaises(DouyinUrlError):
            parse_douyin_profile_url("https://www.douyin.com/video/123456")

    def test_13_video_url_rejection_short(self):
        """Short video URL should raise DouyinUrlError."""
        with self.assertRaises(DouyinUrlError):
            parse_douyin_profile_url("https://www.douyin.com/v/abc123")

    def test_14_invalid_host(self):
        """Invalid host (not Douyin-related) should return None."""
        result = parse_douyin_profile_url("https://facebook.com/user/test")
        self.assertIsNone(result)

    def test_15_mixed_case_host(self):
        """Mixed case hostname should be normalized to lowercase."""
        result = parse_douyin_profile_url("HTTPS://WWW.DOUYIN.COM/user/MS4wLjABAAAA_test")
        self.assertIsNotNone(result)
        self.assertEqual(result.sec_uid, "MS4wLjABAAAA_test")
        self.assertEqual(result.canonical, "https://www.douyin.com/user/MS4wLjABAAAA_test")


if __name__ == "__main__":
    unittest.main()