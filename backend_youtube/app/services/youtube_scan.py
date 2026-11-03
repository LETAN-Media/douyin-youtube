import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger("backend-youtube.youtube_scan")


class YouTubeScanError(Exception):
    pass


async def _get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(settings.YOUTUBE_API_TIMEOUT), base_url="https://www.googleapis.com/youtube/v3")


async def get_channel_id_by_handle(client: httpx.AsyncClient, channel_id_or_handle: str) -> str | None:
    if channel_id_or_handle.startswith("UC") and len(channel_id_or_handle) >= 24:
        return channel_id_or_handle
    handle = channel_id_or_handle.lstrip("@")
    key = settings.YOUTUBE_DATA_API_KEY or ""
    try:
        resp = await client.get(
            "/channels",
            params={"part": "id", "forHandle": handle, "key": key},
        )
    except httpx.HTTPError as exc:
        raise YouTubeScanError(f"Channel lookup failed for handle {handle}: {exc}") from exc
    if resp.status_code != 200:
        raise YouTubeScanError(f"YouTube API error {resp.status_code}: {resp.text}")
    data = resp.json()
    items = data.get("items") or []
    if not items:
        return None
    return items[0].get("id")


async def list_channel_videos(client: httpx.AsyncClient, channel_id: str, since_iso: str | None = None, max_results: int | None = None, on_page=None) -> list[dict]:
    videos: list[dict] = []
    key = settings.YOUTUBE_DATA_API_KEY or ""
    max_results = max_results or settings.YOUTUBE_SCAN_MAX_RESULTS
    pages = 0
    next_page_token: str | None = None
    total_pages = settings.YOUTUBE_SCAN_MAX_PAGES
    while pages < total_pages:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails,statistics",
            "id": channel_id,
            "key": key,
            "maxResults": 1,
        }
        resp = await client.get("/channels", params=params)
        if resp.status_code != 200:
            raise YouTubeScanError(f"YouTube channel API error {resp.status_code}: {resp.text}")
        channel_data = resp.json()
        if not channel_data.get("items"):
            raise YouTubeScanError(f"Channel {channel_id} not found")
        uploads_playlist_id = channel_data["items"][0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads_playlist_id:
            raise YouTubeScanError(f"No uploads playlist for channel {channel_id}")
        playlist_resp = await client.get(
            "/playlistItems",
            params={
                "part": "snippet,contentDetails,status",
                "playlistId": uploads_playlist_id,
                "maxResults": max_results,
                "pageToken": next_page_token,
                "key": key,
            },
        )
        if playlist_resp.status_code != 200:
            raise YouTubeScanError(f"YouTube playlist API error {playlist_resp.status_code}: {playlist_resp.text}")
        page = playlist_resp.json()
        for item in page.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet", {}) or {}
            existing = next((v for v in videos if v["video_id"] == video_id), None)
            if existing:
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "channel_id": snippet.get("channelId"),
                    "title": snippet.get("title"),
                    "description": snippet.get("description"),
                    "publish_time": snippet.get("publishedAt"),
                    "thumbnails": snippet.get("thumbnails", {}),
                    "view_count": None,
                    "like_count": None,
                    "tags": snippet.get("tags"),
                    "raw": item,
                }
            )
            if on_page is not None:
                await on_page(videos[-1])
        next_page_token = page.get("nextPageToken")
        pages += 1
        if not next_page_token:
            break
    return videos


async def enrich_video_stats(client: httpx.AsyncClient, video_ids: list[str]) -> dict:
    if not video_ids:
        return {}
    key = settings.YOUTUBE_DATA_API_KEY or ""
    resp = await client.get(
        "/videos",
        params={"part": "contentDetails,statistics", "id": ",".join(video_ids), "key": key},
    )
    if resp.status_code != 200:
        logger.warning("Failed to enrich video stats: %s", resp.text)
        return {}
    data = resp.json()
    stats: dict[str, dict] = {}
    for item in data.get("items", []):
        vid = item.get("id")
        if not vid:
            continue
        cd = item.get("contentDetails", {})
        stats_obj = item.get("statistics", {}) or {}
        duration_iso = cd.get("duration")
        seconds = None
        if duration_iso:
            from isodate import parse_duration  # type: ignore
            seconds = int(parse_duration(duration_iso).total_seconds())
        stats[vid] = {
            "duration_seconds": seconds,
            "view_count": int(stats_obj.get("viewCount", 0) or 0),
            "like_count": int(stats_obj.get("likeCount", 0) or 0),
        }
    return stats
