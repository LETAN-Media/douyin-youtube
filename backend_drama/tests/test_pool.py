"""Failover pool: ordering, policy, breaker, capabilities, redaction.

All provider HTTP is mocked. No secrets anywhere (asserted on logs).
"""

import asyncio
import logging

import httpx
import pytest

from app.services.providers import pool as pool_mod
from app.services.providers.base import ProviderError


def run(coro):
    return asyncio.run(coro)


def _ep(name, host="h1.example.com", providers=()):
    priority = 0 if name == "primary" else int(name.rsplit("_", 1)[-1])
    return pool_mod.ProviderEndpoint(
        name=name, host=host, base_url=f"https://{host}",
        api_key="k_" + name, priority=priority,
        enabled=True, providers=tuple(providers),
    )


def _ok_handler(payload):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


def test_pool_load_skips_unconfigured_and_legacy_primary(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DRAMA_API_PRIMARY_HOST", "")
    monkeypatch.setattr(settings, "DRAMA_API_PRIMARY_KEY", "")
    monkeypatch.setattr(settings, "DRAMA_API_FALLBACK_1_HOST", "")
    monkeypatch.setattr(settings, "DRAMA_API_FALLBACK_1_KEY", "")
    monkeypatch.setattr(settings, "DRAMA_API_FALLBACK_2_HOST", "fb2.example.com")
    monkeypatch.setattr(settings, "DRAMA_API_FALLBACK_2_KEY", "k2")
    monkeypatch.setattr(settings, "DRAMA_API_HOST", "legacy.example.com")
    monkeypatch.setattr(settings, "DRAMA_API_BASE_URL", "https://legacy.example.com")
    monkeypatch.setattr(settings, "DRAMA_API_KEY", "legacy_key")
    eps = pool_mod.load_pool_from_settings()
    assert [e.name for e in eps] == ["primary", "fallback_2"]
    assert eps[0].host == "legacy.example.com"  # legacy maps to primary
    assert eps[1].base_url == "https://fb2.example.com"  # base defaults to host


def test_capability_routing():
    eps = [
        _ep("primary", providers=("starshort",)),
        _ep("fallback_1", providers=()),
    ]
    assert eps[0].serves("starshort") and not eps[0].serves("dramabox")
    assert eps[1].serves("dramabox") and eps[1].serves("anything")


def _fake_adapter_factory(calls, behaviors):
    """behaviors: {endpoint_name: ('ok', value) | ('raise', code)}"""

    class FakeAdapter:
        def __init__(self, transport=None, endpoint=None):
            self._endpoint = endpoint

        async def _dispatch(self, *args, **kwargs):
            calls.append(self._endpoint.name)
            action = behaviors.get(self._endpoint.name, ("ok", []))
            if action[0] == "ok":
                return action[1]
            raise ProviderError(action[1], f"boom {action[1]}")

        search_series = _dispatch
        get_series = _dispatch
        list_episodes = _dispatch
        get_episode = _dispatch
        resolve_episode_media = _dispatch

    return FakeAdapter


def test_primary_success_no_failover(monkeypatch):
    import app.services.providers.base as base_mod

    calls: list = []
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, {"primary": ("ok", ["s1"])})
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary"), _ep("fallback_1", host="h2.example.com")],
    )
    try:
        result, ep = run(pool_mod.execute("starshort", "search_series", query="love"))
        assert result == ["s1"] and ep == "primary"
        assert calls == ["primary"]
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_timeout_fails_over_to_fallback(monkeypatch):
    import app.services.providers.base as base_mod

    calls: list = []
    behaviors = {"primary": ("raise", "TIMEOUT"), "fallback_1": ("ok", ["s2"])}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, behaviors)
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary"), _ep("fallback_1", host="h2.example.com")],
    )
    try:
        result, ep = run(pool_mod.execute("starshort", "search_series", query="love"))
        assert result == ["s2"] and ep == "fallback_1"
        assert calls == ["primary", "fallback_1"]
        assert pool_mod.pool_health()["primary"] == "healthy"  # 1 failure < threshold
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_503_fails_over(monkeypatch):
    import app.services.providers.base as base_mod

    calls: list = []
    behaviors = {"primary": ("raise", "TEMPORARY"), "fallback_1": ("ok", ["s3"])}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, behaviors)
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary"), _ep("fallback_1", host="h2.example.com")],
    )
    try:
        result, ep = run(pool_mod.execute("starshort", "search_series", query="love"))
        assert result == ["s3"] and ep == "fallback_1"
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_401_is_config_error_no_retry(monkeypatch):
    import app.services.providers.base as base_mod

    calls: list = []
    behaviors = {"primary": ("raise", "AUTH_FAILED")}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, behaviors)
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary"), _ep("fallback_1", host="h2.example.com")],
    )
    try:
        with pytest.raises(pool_mod.PoolExhausted) as exc:
            run(pool_mod.execute("starshort", "search_series", query="love"))
        assert exc.value.code == "CONFIG_ERROR"
        assert calls == ["primary"]  # never touched fallback
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_404_returns_not_found_without_fallback(monkeypatch):
    import app.services.providers.base as base_mod

    calls: list = []
    behaviors = {"primary": ("raise", "NOT_FOUND")}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, behaviors)
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary"), _ep("fallback_1", host="h2.example.com")],
    )
    try:
        with pytest.raises(pool_mod.PoolExhausted) as exc:
            run(pool_mod.execute("starshort", "get_series", series_id="x"))
        assert exc.value.code == "NOT_FOUND"
        assert calls == ["primary"]
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_all_fail_gives_all_providers_failed(monkeypatch):
    import app.services.providers.base as base_mod

    behaviors = {"primary": ("raise", "TIMEOUT"), "fallback_1": ("raise", "TEMPORARY")}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory([], behaviors)
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary"), _ep("fallback_1", host="h2.example.com")],
    )
    try:
        with pytest.raises(pool_mod.PoolExhausted) as exc:
            run(pool_mod.execute("starshort", "search_series", query="love"))
        assert exc.value.code == "ALL_PROVIDERS_FAILED"
        assert [a["endpoint"] for a in exc.value.attempts] == ["primary", "fallback_1"]
        for a in exc.value.attempts:
            assert "k_primary" not in str(a) and "k_fallback" not in str(a)
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_circuit_breaker_cooldown_and_recovery(monkeypatch):
    import app.services.providers.base as base_mod

    calls: list = []
    behaviors = {"primary": ("raise", "TIMEOUT")}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, behaviors)
    pool_mod.reset_pool_state()
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings", lambda: [_ep("primary")]
    )
    try:
        for _ in range(3):
            with pytest.raises(pool_mod.PoolExhausted):
                run(pool_mod.execute("starshort", "search_series", query="love"))
        assert calls == ["primary"] * 3
        assert pool_mod.pool_health()["primary"] == "cooldown"
        # 4th call skips the endpoint entirely (no new attempt).
        with pytest.raises(pool_mod.PoolExhausted):
            run(pool_mod.execute("starshort", "search_series", query="love"))
        assert calls == ["primary"] * 3
        # After cooldown the endpoint is probed again.
        pool_mod._states["primary"].unhealthy_until = 0.0
        with pytest.raises(pool_mod.PoolExhausted):
            run(pool_mod.execute("starshort", "search_series", query="love"))
        assert calls == ["primary"] * 4
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)


def test_429_only_independent_hosts(monkeypatch, caplog):
    import app.services.providers.base as base_mod

    calls: list = []
    behaviors = {"primary": ("raise", "RATE_LIMITED"), "fallback_1": ("ok", ["s9"])}
    orig = base_mod.PROVIDERS.copy()
    base_mod.PROVIDERS["starshort"] = _fake_adapter_factory(calls, behaviors)
    pool_mod.reset_pool_state()
    # Same host twice: second must be skipped (shared quota pool).
    monkeypatch.setattr(
        pool_mod, "load_pool_from_settings",
        lambda: [_ep("primary", host="same.example.com"),
                 _ep("fallback_1", host="same.example.com")],
    )
    try:
        with caplog.at_level("WARNING"):
            with pytest.raises(pool_mod.PoolExhausted) as exc:
                run(pool_mod.execute("starshort", "search_series", query="love"))
        assert exc.value.code == "ALL_PROVIDERS_FAILED"
        assert calls == ["primary"]  # fallback_1 skipped: same limited host
        assert "k_primary" not in caplog.text and "k_fallback" not in caplog.text
        # Different host: failover proceeds.
        pool_mod.reset_pool_state()
        calls.clear()
        monkeypatch.setattr(
            pool_mod, "load_pool_from_settings",
            lambda: [_ep("primary", host="h1.example.com"),
                     _ep("fallback_1", host="h2.example.com")],
        )
        result, ep = run(pool_mod.execute("starshort", "search_series", query="love"))
        assert result == ["s9"] and ep == "fallback_1"
    finally:
        base_mod.PROVIDERS.clear()
        base_mod.PROVIDERS.update(orig)
