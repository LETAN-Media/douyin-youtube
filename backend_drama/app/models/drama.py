"""Normalized provider-agnostic drama models.

Raw RapidIX JSON never leaves the adapter: RapidixClient returns these,
the scanner persists them. Field aliases cover the response shapes such
provider APIs commonly use; anything else raises a typed error instead of
being silently mis-stored.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedSeries:
    provider: str
    external_series_id: str
    title: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    total_episodes: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedEpisode:
    provider: str
    external_episode_id: str | None
    episode_number: int
    title: str | None = None
    source_url: str | None = None
    thumbnail_url: str | None = None
    duration: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodePage:
    episodes: list[NormalizedEpisode]
    next_cursor: str | None = None
    has_more: bool = False


def _first(d: dict[str, Any], *names: str) -> Any:
    for name in names:
        if isinstance(d, dict) and d.get(name) is not None:
            return d[name]
    return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value))
    except (TypeError, ValueError):
        return None


def normalize_series(provider: str, payload: dict[str, Any]) -> NormalizedSeries:
    if not isinstance(payload, dict):
        raise ValueError("Series payload is not an object.")
    external_id = _first(payload, "id", "book_id", "bookId", "series_id", "seriesId", "external_id", "sid", "drama_id", "dramaId")
    if external_id is None or str(external_id).strip() == "":
        raise ValueError("Series payload has no stable id.")
    return NormalizedSeries(
        provider=provider,
        external_series_id=str(external_id),
        title=_first(payload, "title", "name", "book_title"),
        description=_first(payload, "description", "synopsis", "desc", "summary"),
        thumbnail_url=_first(
            payload, "thumbnail_url", "thumbnail", "cover", "cover_url", "coverUrl",
            "image", "poster", "poster_url", "posterUrl", "banner", "pic", "thumb",
        ),
        total_episodes=_as_int(
            _first(payload, "total_episodes", "episode_count", "total", "episodes_total", "episodes")
        ),
        raw=payload,
    )


def normalize_episode(
    provider: str, payload: dict[str, Any], *, fallback_number: int | None = None
) -> NormalizedEpisode:
    if not isinstance(payload, dict):
        raise ValueError("Episode payload is not an object.")
    external_id = _first(
        payload, "id", "episode_id", "episodeId", "external_id",
        "chapter_id", "chapterId", "eid",
    )
    number = _as_int(
        _first(payload, "episode_number", "episodeNumber", "episode_num", "number", "ep", "chapter_number", "chapterNumber", "serial_number", "serialNumber", "chapter_index", "order", "index")
    )
    if number is None:
        number = fallback_number
    if number is None:
        raise ValueError("Episode payload has no episode number.")
    return NormalizedEpisode(
        provider=provider,
        external_episode_id=str(external_id) if external_id is not None else None,
        episode_number=number,
        title=_first(payload, "title", "name", "chapter_title"),
        source_url=_first(payload, "source_url", "url", "link", "share_url"),
        thumbnail_url=_first(payload, "thumbnail_url", "thumbnail", "cover", "cover_url", "coverUrl", "image", "video_pic", "videoPic"),
        duration=_as_float(_first(payload, "duration", "duration_seconds", "length")),
        raw=payload,
    )
