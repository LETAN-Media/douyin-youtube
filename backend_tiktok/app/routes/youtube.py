from __future__ import annotations

import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..config import settings
from ..dependencies import require_admin
from ..db.repositories import destinations, pipelines, youtube_auth
from ..services import youtube_oauth

router = APIRouter(prefix="/api/tiktok/youtube", tags=["youtube"])


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


@router.get("/destinations/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def list_destinations(pipeline_id: str):
    return await destinations.list_destinations(pipeline_id)


@router.post("/destinations", dependencies=[Depends(require_admin)])
async def create_destination(body: dict):
    pipeline_id = body.get("pipeline_id")
    if not pipeline_id:
        raise HTTPException(status_code=400, detail="pipeline_id is required")

    pipeline = await pipelines.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    dest_id = body.get("id") or f"dest_{secrets.token_hex(8)}"
    return await destinations.create_destination(
        destination_id=dest_id,
        pipeline_id=pipeline_id,
        channel_id=body.get("channel_id"),
        channel_name=body.get("channel_name"),
        channel_avatar_url=body.get("channel_avatar_url"),
        account_id=body.get("account_id"),
        visibility=body.get("visibility", "public"),
        enabled=bool(body.get("enabled", True)),
        is_default=bool(body.get("is_default", False)),
    )


@router.post("/oauth/start", dependencies=[Depends(require_admin)])
async def oauth_start(body: dict):
    pipeline_id = body.get("pipeline_id")
    if not pipeline_id:
        raise HTTPException(status_code=400, detail="pipeline_id is required")

    pipeline = await pipelines.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    dest_id = body.get("destination_id")
    if not dest_id:
        all_dests = await destinations.list_destinations(pipeline_id)
        unconnected = [d for d in all_dests if not d.get("connected")]
        if unconnected:
            dest_id = unconnected[0]["id"]
        else:
            dest_id = f"dest_{secrets.token_hex(8)}"
            await destinations.create_destination(
                destination_id=dest_id,
                pipeline_id=pipeline_id,
                visibility="public",
                enabled=True,
            )

    return_to = body.get("return_to")
    try:
        auth_url, state = await youtube_oauth.build_auth_url(dest_id, pipeline_id, return_to=return_to)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"authorization_url": auth_url, "destination_id": dest_id, "state": state}


@router.post("/oauth/authorize/{pipeline_id}/{destination_id}", dependencies=[Depends(require_admin)])
async def oauth_authorize(pipeline_id: str, destination_id: str, return_to: str | None = None):
    auth_url, state = await youtube_oauth.build_auth_url(destination_id, pipeline_id, return_to=return_to)
    return {"auth_url": auth_url, "authorization_url": auth_url, "state": state}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
):
    """Google OAuth callback. No require_admin dependency since Google redirects user browser."""
    base = (settings.dashboard_base_url or "").rstrip("/")

    # If Google redirected with an error (e.g. error=access_denied)
    if error:
        return_to = None
        if state:
            state_row = await youtube_auth.get_oauth_state(state)
            if state_row:
                return_to = youtube_oauth.sanitize_return_to(state_row.get("return_to"))
                await youtube_auth.delete_oauth_state(state)
        if return_to:
            sep = "&" if "?" in return_to else "?"
            return RedirectResponse(
                f"{base}{return_to}{sep}youtube_error={quote(error)}", status_code=303
            )
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
            f"<h2 style='color:#e11d48'>YouTube Authorization Error</h2>"
            f"<p>Google OAuth returned: {error}</p>"
            f"</body></html>",
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
            "<h2 style='color:#e11d48'>Invalid OAuth Request</h2>"
            "<p>Missing code or state.</p>"
            "</body></html>",
            status_code=400,
        )

    state_row = await youtube_auth.get_oauth_state(state)
    return_to = youtube_oauth.sanitize_return_to(state_row.get("return_to")) if state_row else None

    try:
        result = await youtube_oauth.handle_callback(code, state)
    except Exception as exc:
        err_msg = str(exc)
        if return_to:
            sep = "&" if "?" in return_to else "?"
            return RedirectResponse(
                f"{base}{return_to}{sep}youtube_error={quote(err_msg)}", status_code=303
            )
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
            f"<h2 style='color:#e11d48'>OAuth Failed</h2>"
            f"<p>{err_msg}</p>"
            f"</body></html>",
            status_code=400,
        )

    final_return = result.get("return_to") or return_to
    if final_return:
        sep = "&" if "?" in final_return else "?"
        return RedirectResponse(
            f"{base}{final_return}{sep}youtube_connected=1", status_code=303
        )

    channel_name = (result.get("channel_name") or "YouTube Channel").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        f"<html><body style='font-family:sans-serif;text-align:center;padding:48px'>"
        f"<h2 style='color:#16a34a'>Đã liên kết YouTube thành công!</h2>"
        f"<p>Kênh <b>{channel_name}</b> đã được kết nối với TikTok Pipeline.</p>"
        f"<p><a href='{base}/tiktok'>Quay lại Dashboard TikTok</a></p>"
        f"</body></html>"
    )


@router.patch("/destinations/{destination_id}/enable", dependencies=[Depends(require_admin)])
async def toggle_destination_enabled(destination_id: str, body: dict):
    enabled = bool(body.get("enabled", True))
    updated = await destinations.toggle_destination_enabled(destination_id, enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="Destination not found")
    return updated


@router.patch("/destinations/{destination_id}/default", dependencies=[Depends(require_admin)])
async def set_default_destination(destination_id: str, body: dict):
    pipeline_id = body.get("pipeline_id")
    if not pipeline_id:
        dest = await destinations.get_destination(destination_id)
        if not dest:
            raise HTTPException(status_code=404, detail="Destination not found")
        pipeline_id = dest["pipeline_id"]

    updated = await destinations.set_default_destination(pipeline_id, destination_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Destination not found")
    return updated


@router.delete("/destinations/{destination_id}", dependencies=[Depends(require_admin)])
async def disconnect_destination(destination_id: str):
    dest = await destinations.get_destination(destination_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    await youtube_auth.delete_credentials(destination_id)
    await youtube_auth.delete_oauth_states_for_destination(destination_id)
    await destinations.disconnect_destination(destination_id)
    return {"ok": True, "destination_id": destination_id, "connected": False}


@router.delete("/destinations/{destination_id}/permanent", dependencies=[Depends(require_admin)])
async def delete_destination_permanently(destination_id: str):
    dest = await destinations.get_destination(destination_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    await youtube_auth.delete_credentials(destination_id)
    await youtube_auth.delete_oauth_states_for_destination(destination_id)
    await destinations.delete_destination(destination_id)
    return {"ok": True, "destination_id": destination_id, "deleted": True}


@router.get("/destinations/{destination_id}/credentials", dependencies=[Depends(require_admin)])
async def check_credentials(destination_id: str):
    row = await youtube_auth.get_credentials(destination_id)
    return {"configured": row is not None, "destination_id": destination_id}


@router.delete("/destinations/{destination_id}/credentials", dependencies=[Depends(require_admin)])
async def delete_credentials(destination_id: str):
    await youtube_auth.delete_credentials(destination_id)
    await destinations.update_destination_connected(destination_id, connected=False)
    return {"status": "deleted", "destination_id": destination_id}
