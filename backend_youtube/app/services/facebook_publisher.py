import json
import logging
import os
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger("backend-youtube.facebook")


class FacebookError(Exception):
    pass


async def get_page_info(client: httpx.AsyncClient, page_access_token: str, page_id: str) -> dict:
    resp = await client.get(
        f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}",
        params={"fields": "id,name,access_token", "access_token": page_access_token},
        timeout=httpx.Timeout(settings.FACEBOOK_API_TIMEOUT),
    )
    if resp.status_code != 200:
        raise FacebookError(f"Facebook page info error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _file_size(file_path: str) -> int:
    return os.path.getsize(file_path)


def _upload_resumable(
    client: httpx.AsyncClient,
    page_access_token: str,
    page_id: str,
    file_path: str,
    caption: str,
    description: str | None,
    is_reel: bool,
) -> str:
    import asyncio

    async def _start() -> str:
        resp = await client.post(
            f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
            params={
                "access_token": page_access_token,
                "upload_phase": "start",
                "video_file_size": str(_file_size(file_path)),
                "video_file_name": os.path.basename(file_path),
                "description": description or caption,
                "title": caption,
            },
            timeout=httpx.Timeout(settings.FACEBOOK_UPLOAD_TIMEOUT),
        )
        if resp.status_code != 200:
            raise FacebookError(f"Upload start failed {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if "error" in data:
            raise FacebookError(f"Upload start error: {json.dumps(data['error'])}")
        return data.get("id") or data.get("upload_session_id", "")

    async def _transfer(session_id: str, start: int, end: int, is_final: bool) -> None:
        params = {
            "access_token": page_access_token,
            "upload_phase": "transfer",
            "upload_session_id": session_id,
            "start_offset": str(start),
        }
        with open(file_path, "rb") as fh:
            fh.seek(start)
            chunk = fh.read(end - start)
        files = {"source": ("video.mp4", chunk, "video/mp4")}
        resp = await client.post(
            f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
            params=params,
            files=files,
            timeout=httpx.Timeout(settings.FACEBOOK_UPLOAD_TIMEOUT),
        )
        if resp.status_code != 200:
            raise FacebookError(f"Upload transfer failed {resp.status_code}: {resp.text[:500]}")

    async def _finish(session_id: str) -> dict:
        resp = await client.post(
            f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
            params={
                "access_token": page_access_token,
                "upload_phase": "finish",
                "upload_session_id": session_id,
                "description": description or caption,
                "title": caption,
            },
            timeout=httpx.Timeout(settings.FACEBOOK_API_TIMEOUT),
        )
        if resp.status_code != 200:
            raise FacebookError(f"Upload finish failed {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if "error" in data:
            raise FacebookError(f"Upload finish error: {json.dumps(data['error'])}")
        return data

    session_id = asyncio.get_event_loop().run_until_complete(_start())
    return _transfer_sync_wrapper(client, session_id, page_access_token, page_id, file_path, caption, description, is_reel, _start, _transfer, _finish)


def _transfer_sync_wrapper(
    client: httpx.AsyncClient,
    session_id: str,
    page_access_token: str,
    page_id: str,
    file_path: str,
    caption: str,
    description: str | None,
    is_reel: bool,
    _start,
    _transfer,
    _finish,
) -> str:
    raise NotImplementedError


async def upload_video(
    client: httpx.AsyncClient,
    page_access_token: str,
    page_id: str,
    file_path: str,
    caption: str,
    description: str | None = None,
    is_reel: bool = False,
) -> dict:
    """Upload a video file and return the Facebook video/container metadata.

    Uses the resumable upload API: start -> transfer chunks -> finish.
    Returns {"id": <video_id_or_container_id>, "is_reel": <bool>}.
    """
    file_size = _file_size(file_path)
    if not is_reel and file_size < 100 * 1024 * 1024:
        return await _upload_simple(client, page_access_token, page_id, file_path, caption, description)
    return await _upload_resumable_async(client, page_access_token, page_id, file_path, caption, description, file_size)


async def _upload_simple(
    client: httpx.AsyncClient,
    page_access_token: str,
    page_id: str,
    file_path: str,
    caption: str,
    description: str | None,
) -> dict:
    with open(file_path, "rb") as fh:
        resp = await client.post(
            f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
            params={
                "access_token": page_access_token,
                "caption": caption,
                "description": description or caption,
                "published": "false",
            },
            files={"source": (os.path.basename(file_path), fh, "video/mp4")},
            timeout=httpx.Timeout(settings.FACEBOOK_UPLOAD_TIMEOUT),
        )
    if resp.status_code != 200:
        raise FacebookError(f"Video upload error {resp.status_code}: {resp.text[:800]}")
    data = resp.json()
    if "error" in data:
        raise FacebookError(f"Video upload error: {json.dumps(data['error'])}")
    return {"id": data.get("id"), "is_reel": False}


async def _upload_resumable_async(
    client: httpx.AsyncClient,
    page_access_token: str,
    page_id: str,
    file_path: str,
    caption: str,
    description: str | None,
    file_size: int,
) -> dict:
    start = await client.post(
        f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
        params={
            "access_token": page_access_token,
            "upload_phase": "start",
            "video_file_size": str(file_size),
            "video_file_name": os.path.basename(file_path),
            "description": description or caption,
            "title": caption,
        },
        timeout=httpx.Timeout(settings.FACEBOOK_UPLOAD_TIMEOUT),
    )
    if start.status_code != 200:
        raise FacebookError(f"Upload start failed {start.status_code}: {start.text[:500]}")
    start_data = start.json()
    if "error" in start_data:
        raise FacebookError(f"Upload start error: {json.dumps(start_data['error'])}")
    session_id = start_data.get("id") or start_data.get("upload_session_id", "")
    chunk_size = 64 * 1024 * 1024
    offset = 0
    with open(file_path, "rb") as fh:
        while offset < file_size:
            end = min(offset + chunk_size, file_size)
            fh.seek(offset)
            chunk = fh.read(end - offset)
            is_final = end >= file_size
            resp = await client.post(
                f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
                params={
                    "access_token": page_access_token,
                    "upload_phase": "transfer",
                    "upload_session_id": session_id,
                    "start_offset": str(offset),
                },
                files={"source": ("video.mp4", chunk, "video/mp4")},
                timeout=httpx.Timeout(settings.FACEBOOK_UPLOAD_TIMEOUT),
            )
            if resp.status_code != 200:
                raise FacebookError(f"Upload transfer failed {resp.status_code}: {resp.text[:500]}")
            offset = end
            if is_final:
                finish = await client.post(
                    f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/videos",
                    params={
                        "access_token": page_access_token,
                        "upload_phase": "finish",
                        "upload_session_id": session_id,
                        "description": description or caption,
                        "title": caption,
                    },
                    timeout=httpx.Timeout(settings.FACEBOOK_API_TIMEOUT),
                )
                if finish.status_code != 200:
                    raise FacebookError(f"Upload finish failed {finish.status_code}: {finish.text[:500]}")
                finish_data = finish.json()
                if "error" in finish_data:
                    raise FacebookError(f"Upload finish error: {json.dumps(finish_data['error'])}")
    return {"id": session_id, "is_reel": False}


async def create_reel_container(
    client: httpx.AsyncClient,
    page_access_token: str,
    page_id: str,
    video_id: str,
    caption: str,
    hashtags: list[str] | None = None,
) -> dict:
    tags = " ".join(f"#{h}" for h in (hashtags or []))
    message = (caption + (f" {tags}" if tags else "")).strip()
    resp = await client.post(
        f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{page_id}/feed",
        params={"access_token": page_access_token},
        json={"message": message, "attached_media": [{"media_type": "VIDEO", "media_fbid": video_id}]},
        timeout=httpx.Timeout(settings.FACEBOOK_API_TIMEOUT),
    )
    if resp.status_code != 200:
        raise FacebookError(f"Reel creation error {resp.status_code}: {resp.text[:800]}")
    data = resp.json()
    if "error" in data:
        raise FacebookError(f"Reel creation error: {json.dumps(data['error'])}")
    return {"post_id": data.get("id"), "container_id": video_id, "is_reel": True}


async def wait_for_processing(client: httpx.AsyncClient, page_access_token: str, video_id: str, timeout: float = 300.0) -> str:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(
            f"{settings.FACEBOOK_GRAPH_BASE_URL}/{settings.FACEBOOK_GRAPH_API_VERSION}/{video_id}",
            params={"fields": "id,status,processing_status", "access_token": page_access_token},
            timeout=httpx.Timeout(settings.FACEBOOK_API_TIMEOUT),
        )
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status") or data.get("processing_status", {}).get("status")
            if status in ("succeeded", "true", "active"):
                return "succeeded"
            if status in ("failed", "error"):
                return "failed"
        await asyncio_sleep(5)
    return "timeout"


async def asyncio_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


async def validate_token(client: httpx.AsyncClient, page_access_token: str, page_id: str) -> bool:
    try:
        info = await get_page_info(client, page_access_token, page_id)
        return "error" not in info
    except FacebookError:
        return False


def parse_error(resp_text: str) -> tuple[str | None, str | None]:
    try:
        data = json.loads(resp_text)
    except Exception:
        return None, resp_text[:500]
    err = data.get("error", {})
    code = err.get("code") if isinstance(err, dict) else None
    message = err.get("message") if isinstance(err, dict) else None
    if not message:
        message = err.get("id") if isinstance(err, dict) else resp_text[:500]
    return (str(code) if code is not None else None), (message or resp_text[:500])


async def refresh_page_token(client: httpx.AsyncClient, fb_app_id: str, fb_app_secret: str, page_access_token: str) -> tuple[str | None, str | None]:
    resp = await client.get(
        f"{settings.FACEBOOK_GRAPH_BASE_URL}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": fb_app_id,
            "client_secret": fb_app_secret,
            "fb_exchange_token": page_access_token,
        },
        timeout=httpx.Timeout(settings.FACEBOOK_API_TIMEOUT),
    )
    try:
        data = resp.json()
    except Exception:
        return None, None
    return data.get("access_token"), data.get("expires_in")
