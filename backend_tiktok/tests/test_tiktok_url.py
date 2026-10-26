"""Tests for TikTok URL parsing and validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.tiktok_url import (
    extract_username,
    extract_video_id,
    is_tiktok_url,
    normalize_url,
)


def test_is_tiktok_url_valid():
    assert is_tiktok_url("https://www.tiktok.com/@username/video/1234567890")
    assert is_tiktok_url("https://vm.tiktok.com/abc123")
    assert is_tiktok_url("https://vt.tiktok.com/abc123")


def test_is_tiktok_url_invalid():
    assert not is_tiktok_url("https://facebook.com/reel/123")
    assert not is_tiktok_url("not a url")
    assert not is_tiktok_url("ftp://tiktok.com")
    assert is_tiktok_url("") is False


def test_extract_username():
    assert extract_username("https://www.tiktok.com/@myuser/video/123") == "myuser"
    assert extract_username("https://tiktok.com/@another") == "another"
    assert extract_username("https://vm.tiktok.com/abc") is None


def test_extract_video_id():
    assert extract_video_id("https://www.tiktok.com/@user/video/7312345678901234567") == "7312345678901234567"
    assert extract_video_id("https://www.tiktok.com/v/1234567890") == "1234567890"


def test_normalize_url():
    normalized = normalize_url("https://www.tiktok.com/@user/video/123?utm_source=share")
    assert "?" not in normalized
    assert "utm_source" not in normalized
    assert normalized == "https://www.tiktok.com/@user/video/123"


def test_extract_username_not_tiktok():
    assert extract_username("https://facebook.com/reel/123") is None


if __name__ == "__main__":
    test_is_tiktok_url_valid()
    test_is_tiktok_url_invalid()
    test_extract_username()
    test_extract_video_id()
    test_normalize_url()
    test_extract_username_not_tiktok()
    print("All tiktok_url tests passed!")
