import asyncio

from app.config import settings
from app.services import dashboard_cache


def _counter():
    calls = {"n": 0}

    async def compute() -> int:
        calls["n"] += 1
        return calls["n"]

    return calls, compute


def test_remote_db_uses_cached_value(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURSO_DATABASE_URL", "https://db.example")
    dashboard_cache.clear()
    calls, compute = _counter()

    async def _run() -> tuple[int, int]:
        first = await dashboard_cache.get_or_compute("k", 60, compute)
        second = await dashboard_cache.get_or_compute("k", 60, compute)
        return first, second

    assert asyncio.run(_run()) == (1, 1)
    assert calls["n"] == 1


def test_clear_invalidates_cached_value(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURSO_DATABASE_URL", "https://db.example")
    dashboard_cache.clear()
    calls, compute = _counter()

    async def _run() -> int:
        await dashboard_cache.get_or_compute("k", 60, compute)
        dashboard_cache.clear()
        return await dashboard_cache.get_or_compute("k", 60, compute)

    assert asyncio.run(_run()) == 2
    assert calls["n"] == 2


def test_file_db_and_zero_ttl_are_uncached(monkeypatch) -> None:
    dashboard_cache.clear()
    calls, compute = _counter()

    async def _run() -> None:
        monkeypatch.setattr(settings, "TURSO_DATABASE_URL", "file:/tmp/x.db")
        await dashboard_cache.get_or_compute("file", 60, compute)
        await dashboard_cache.get_or_compute("file", 60, compute)
        monkeypatch.setattr(settings, "TURSO_DATABASE_URL", "https://db.example")
        await dashboard_cache.get_or_compute("zero", 0, compute)

    asyncio.run(_run())
    assert calls["n"] == 3


def test_pipeline_keys_are_isolated(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURSO_DATABASE_URL", "https://db.example")
    dashboard_cache.clear()
    calls_a, compute_a = _counter()
    calls_b, compute_b = _counter()

    async def _run() -> tuple[int, int, int]:
        first = await dashboard_cache.get_or_compute("flow:pl_a", 60, compute_a)
        second = await dashboard_cache.get_or_compute("flow:pl_b", 60, compute_b)
        first_again = await dashboard_cache.get_or_compute("flow:pl_a", 60, compute_a)
        return first, second, first_again

    assert asyncio.run(_run()) == (1, 1, 1)
    assert calls_a["n"] == 1
    assert calls_b["n"] == 1
