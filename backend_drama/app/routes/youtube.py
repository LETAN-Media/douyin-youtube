"""YouTube OAuth + destinations (drama). Tokens never leave the backend."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import require_admin
from ..db.repositories import drama as drama_repo
from ..db.repositories import youtube as yt_repo
from ..services import drama_youtube_oauth as yt_oauth
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-youtube"])


@router.get("/youtube/oauth/start")
async def oauth_start(
    pipeline_id: str = "",
    visibility: str = "public",
    return_to: str | None = None,
    _: None = Depends(require_admin),
) -> dict:
    if not pipeline_id:
        raise _err(400, "PIPELINE_REQUIRED", "pipeline_id is required.")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    try:
        url, destination_id = await yt_oauth.create_authorization_url(
            pipeline_id, visibility=visibility, return_to=return_to
        )
    except RuntimeError as exc:
        raise _err(400, "OAUTH_START_FAILED", str(exc) or "OAuth start failed.")
    return {"authorization_url": url, "destination_id": destination_id}


@router.get("/youtube/oauth/callback")
async def oauth_callback(state: str = "", code: str = ""):
    if not state or not code:
        raise _err(400, "OAUTH_INVALID_STATE", "Missing state or code.")
    try:
        info = await yt_oauth.complete_oauth(state, code)
    except RuntimeError as exc:
        message = str(exc) or "OAuth failed."
        lowered = message.lower()
        if "expired" in lowered:
            raise _err(400, "OAUTH_STATE_EXPIRED", message)
        if "not exist" in lowered or "already used" in lowered:
            raise _err(400, "OAUTH_INVALID_STATE", message)
        raise _err(400, "OAUTH_FAILED", message)
    return_to = yt_oauth.sanitize_return_to(info.get("return_to"))
    if return_to:
        from ..config import settings as app_settings

        base = (app_settings.DRAMA_DASHBOARD_URL or "https://douyin.toolnet.tech").rstrip("/")
        sep = "&" if "?" in return_to else "?"
        return RedirectResponse(
            f"{base}{return_to}{sep}youtube_connected=1", status_code=303
        )
    title = (info.get("channel_title") or "").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
        "<h2>YouTube connected</h2>"
        f"<p>Channel <b>{title}</b> linked successfully. You can close this tab.</p>"
        "</body></html>"
    )


@router.get("/youtube/destinations")
async def list_connected_destinations(_: None = Depends(require_admin)) -> list[dict]:
    """Every connected channel (for the picker), safe fields only."""
    return [
        {
            "id": d["id"],
            "pipeline_id": d["pipeline_id"],
            "channel_id": d["channel_id"],
            "channel_title": d["channel_title"],
            "channel_thumbnail": d.get("channel_thumbnail"),
            "visibility": d.get("visibility", "public"),
            "connected": True,
        }
        for d in yt_repo.list_destinations(None)
    ]


@router.get("/pipelines/{pipeline_id}/youtube-destinations")
async def list_pipeline_destinations(
    pipeline_id: str, _: None = Depends(require_admin)
) -> list[dict]:
    if drama_repo.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    return [
        {
            "id": d["id"],
            "pipeline_id": d["pipeline_id"],
            "channel_id": d["channel_id"],
            "channel_title": d["channel_title"],
            "channel_thumbnail": d.get("channel_thumbnail"),
            "visibility": d.get("visibility", "public"),
            "enabled": d.get("enabled", True),
            "connected": d.get("connected", False),
            "credentials_present": yt_repo.credentials_present(d["id"]),
        }
        for d in yt_repo.list_destinations(pipeline_id)
    ]


@router.delete("/youtube-destinations/{destination_id}")
async def disconnect_destination(
    destination_id: str, _: None = Depends(require_admin)
) -> dict:
    """Safe disconnect: row kept for history, credentials wiped."""
    from ..db.repositories import processing as proc_repo

    updated = yt_repo.disconnect_destination(destination_id)
    if updated is None:
        raise _err(404, "DESTINATION_NOT_FOUND", "Destination not found.")
    # A pipeline pointing at this destination falls back to unset.
    try:
        from ..db.client import get_client

        conn = get_client()
        conn.execute(
            "UPDATE drama_pipeline_settings SET youtube_destination_id = NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
            "WHERE youtube_destination_id = ?",
            (destination_id,),
        )
        conn.commit()
    except Exception:
        pass
    return {"ok": True, "destination_id": destination_id, "connected": False}
