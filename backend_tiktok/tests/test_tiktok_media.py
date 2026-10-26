"""Tests for TikTok media hashing and manual resolve path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.tiktok_media import source_hash


def test_source_hash_deterministic():
    url = "https://www.tiktok.com/@user/video/12345"
    h1 = source_hash(url)
    h2 = source_hash(url)
    assert h1 == h2
    assert len(h1) == 32


def test_source_hash_different_urls():
    h1 = source_hash("https://www.tiktok.com/@user/video/123")
    h2 = source_hash("https://www.tiktok.com/@user/video/456")
    assert h1 != h2


def test_source_hash_ignores_query_params():
    url1 = "https://www.tiktok.com/@user/video/123?utm_source=share"
    url2 = "https://www.tiktok.com/@user/video/123"
    assert source_hash(url1) == source_hash(url2)


if __name__ == "__main__":
    test_source_hash_deterministic()
    test_source_hash_different_urls()
    test_source_hash_ignores_query_params()
    print("All media hash tests passed!")
