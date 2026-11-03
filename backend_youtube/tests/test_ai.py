import pytest

from app.services.ai import enrich_metadata, AIError, _toolnet_params
from app.services.ai_rate_limiter import AIRateLimiter


@pytest.mark.asyncio
async def test_toolnet_params_error_when_disabled(monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "TOOLNET_AI_ENABLED", False)
    try:
        _toolnet_params()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    monkeypatch.setattr(cfg.settings, "TOOLNET_AI_ENABLED", True)


@pytest.mark.asyncio
async def test_rate_limiter_allows_initial_request():
    limiter = AIRateLimiter(max_requests=2, max_tokens=1000)
    assert await limiter.acquire(100) is True
    assert await limiter.acquire(100) is True
