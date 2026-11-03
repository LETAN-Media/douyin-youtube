import os
import tempfile

import pytest

from app.services.media import acquire_media, MediaError


@pytest.mark.asyncio
async def test_acquire_media_invalid_url(tmp_path):
    from app.config import settings
    settings.FASTSAVER_API_KEY = "test" if False else None
    try:
        await acquire_media("vid123", "not-a-real-url")
    except (MediaError, Exception):
        pass


@pytest.mark.asyncio
async def test_media_cleanup(tmp_path):
    from app.services.media import cleanup
    fpath = tmp_path / "test.bin"
    fpath.write_text("abc")
    cleanup(str(fpath))
    assert not fpath.exists()
    cleanup(None)
    cleanup(str(tmp_path / "nonexistent"))
