"""Series/episode repositories: upsert, dedupe, strict ordering."""

from app.db.repositories import drama as repo


def _pipe(name="P"):
    return repo.create_pipeline(name=name)


def test_pipeline_slug_unique_and_auto(db):
    p1 = repo.create_pipeline(name="My Drama!")
    assert p1["slug"] == "my-drama"
    p2 = repo.create_pipeline(name="My Drama!")
    assert p2["slug"] == "my-drama-2"
    try:
        repo.create_pipeline(name="X", slug=p1["slug"])
        raise AssertionError("expected duplicate slug to fail")
    except ValueError:
        pass


def test_series_upsert_by_provider_external_id(db):
    p = _pipe()
    src = repo.create_source(pipeline_id=p["id"], external_series_id="b1")
    row, created = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="b1",
        title="T1", total_episodes=80,
    )
    assert created is True
    assert row["total_episodes"] == 80
    row2, created2 = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="b1",
        title="T1 updated", total_episodes=81,
    )
    assert created2 is False
    assert row2["id"] == row["id"]
    assert row2["title"] == "T1 updated"


def test_episode_dedupe_by_provider_id(db):
    p = _pipe()
    src = repo.create_source(pipeline_id=p["id"], external_series_id="b1")
    series, _ = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="b1"
    )
    r1, o1 = repo.upsert_episode(
        series_id=series["id"], provider="rapidix", external_episode_id="e1",
        episode_number=1, title="Ep 1",
    )
    assert o1 == "inserted"
    r2, o2 = repo.upsert_episode(
        series_id=series["id"], provider="rapidix", external_episode_id="e1",
        episode_number=1, title="Ep 1",
    )
    assert o2 == "existing" and r2["id"] == r1["id"]
    r3, o3 = repo.upsert_episode(
        series_id=series["id"], provider="rapidix", external_episode_id="e1",
        episode_number=1, title="Ep 1 new title",
    )
    assert o3 == "updated" and r3["title"] == "Ep 1 new title"


def test_episode_dedupe_fallback_series_number(db):
    p = _pipe()
    src = repo.create_source(pipeline_id=p["id"], external_series_id="b1")
    series, _ = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="b1"
    )
    _, o1 = repo.upsert_episode(
        series_id=series["id"], provider="rapidix", external_episode_id=None,
        episode_number=5, title="Five",
    )
    assert o1 == "inserted"
    _, o2 = repo.upsert_episode(
        series_id=series["id"], provider="rapidix", external_episode_id=None,
        episode_number=5, title="Five",
    )
    assert o2 == "existing"


def test_inventory_ordering_strict_asc(db):
    p = _pipe()
    src = repo.create_source(pipeline_id=p["id"], external_series_id="b1")
    series, _ = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="b1"
    )
    for n in (3, 1, 2):
        repo.upsert_episode(
            series_id=series["id"], provider="rapidix",
            external_episode_id=f"e{n}", episode_number=n,
        )
    items, total = repo.list_episodes(series["id"])
    assert total == 3
    assert [e["episode_number"] for e in items] == [1, 2, 3]
