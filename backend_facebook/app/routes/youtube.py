"""YouTube destination OAuth routes (Task 7A). No uploads here."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import destinations, pipelines
from ..services import facebook_youtube_oauth as yt_oauth

router = APIRouter(prefix="/api/facebook", tags=["facebook-youtube"])


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


async def _require_pipeline(pipeline_id: str) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return pipeline


class DestinationCreate(BaseModel):
    visibility: str = Field(default="public", max_length=20)
    enabled: bool = True


@router.post("/pipelines/{pipeline_id}/youtube-destinations", status_code=201)
async def create_youtube_destination(
    pipeline_id: str, body: DestinationCreate, _: None = Depends(require_admin)
) -> dict:
    await _require_pipeline(pipeline_id)
    row = await destinations.create_destination(
        destination_id=f"ytd_{uuid.uuid4().hex[:12]}",
        pipeline_id=pipeline_id,
        channel_id=None,
        channel_name=None,
        visibility=body.visibility,
        enabled=body.enabled,
    )
    return destinations.to_safe_dict(row)


@router.get("/pipelines/{pipeline_id}/youtube-destinations")
async def list_youtube_destinations(pipeline_id: str) -> list[dict]:
    await _require_pipeline(pipeline_id)
    rows = await destinations.list_destinations(pipeline_id)
    return [destinations.to_safe_dict(r) for r in rows]


@router.post("/youtube-destinations/{destination_id}/oauth/start")
async def oauth_start(destination_id: str, _: None = Depends(require_admin)) -> dict:
    destination = await destinations.get_destination(destination_id)
    if destination is None:
        raise _err(404, "DESTINATION_NOT_FOUND", "Destination not found")
    try:
        url = await yt_oauth.create_authorization_url(
            destination_id, destination["pipeline_id"]
        )
    except RuntimeError as exc:
        raise _err(400, "OAUTH_START_FAILED", str(exc) or "OAuth start failed")
    return {"authorization_url": url}


@router.get("/youtube/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(request: Request, state: str = "", code: str = "") -> str:
    if not state or not code:
        raise _err(400, "OAUTH_INVALID_STATE", "Missing state or code")
    try:
        info = await yt_oauth.complete_oauth(state, str(request.url))
    except RuntimeError as exc:
        message = str(exc) or "OAuth failed"
        code_name = "OAUTH_STATE_EXPIRED" if "expired" in message.lower() else (
            "OAUTH_INVALID_STATE" if "not exist" in message.lower() or "match" in message.lower()
            else "OAUTH_FAILED"
        )
        raise _err(400, code_name, message)
    channel = (info["channel_name"] or "").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
        "<h2>YouTube connected</h2>"
        f"<p>Channel <b>{channel}</b> linked successfully. You can close this tab.</p>"
        "</body></html>"
    )
