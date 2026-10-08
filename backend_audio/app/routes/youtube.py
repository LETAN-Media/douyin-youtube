"""YouTube OAuth routes: dedicated /api/audio/* callback (never drama's)."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth import require_admin
from app.db.repositories import audio as repo
from app.db.repositories import pipelines as pipe_repo

router = APIRouter(prefix="/api/audio", tags=["audio-youtube"])


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


@router.get("/pipelines/{pipeline_id}/youtube-destinations")
async def list_destinations(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return repo.list_destinations(pipeline_id)


@router.post("/pipelines/{pipeline_id}/youtube-destinations", status_code=201)
async def create_destination(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return repo.create_destination(pipeline_id)


@router.post("/youtube/oauth/start")
async def oauth_start(pipeline_id: str, destination_id: str | None = None,
                      _: None = Depends(require_admin)):
    from app.services import youtube_oauth as oauth

    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    if destination_id:
        dest = repo.get_destination(destination_id)
        if dest is None or dest.get("pipeline_id") != pipeline_id:
            return _err(404, "DESTINATION_NOT_FOUND", "Destination không tồn tại.")
    else:
        dest = repo.create_destination(pipeline_id)
        destination_id = dest["id"]
    try:
        from app.config import settings

        result = oauth.start_oauth(
            pipeline_id, destination_id,
            return_to=f"{settings.AUDIO_DASHBOARD_URL}/audio/{pipeline_id}?tab=youtube")
    except oauth.OAuthError as exc:
        return _err(503, exc.code, str(exc))
    return result


@router.get("/youtube/oauth/callback")
async def oauth_callback(code: str | None = None, state: str | None = None,
                         error: str | None = None):
    from app.config import settings
    from app.services import youtube_oauth as oauth

    dashboard = settings.AUDIO_DASHBOARD_URL.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{dashboard}/audio?oauth=error", status_code=302)
    try:
        consumed = oauth.consume_state(state)
        tokens = await oauth.exchange_code(code)
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise oauth.OAuthError("NO_REFRESH_TOKEN",
                                   "Google did not return a refresh token.")
        channel_id = await _resolve_channel_id(tokens.get("access_token"))
        oauth.save_credentials(consumed["destination_id"], channel_id, refresh)
        dest = repo.get_destination(consumed["destination_id"])
        if dest and not dest.get("channel_title") and channel_id:
            repo.update_destination(dest["id"], channel_title=channel_id)
        return_to = consumed.get("return_to") or f"{dashboard}/audio"
        sep = "&" if "?" in return_to else "?"
        return RedirectResponse(f"{return_to}{sep}oauth=connected", status_code=302)
    except oauth.OAuthError:
        return RedirectResponse(f"{dashboard}/audio?oauth=error", status_code=302)


async def _resolve_channel_id(access_token: str | None) -> str | None:
    if not access_token:
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code != 200:
            return None
        items = resp.json().get("items") or []
        if not items:
            return None
        snippet = items[0].get("snippet") or {}
        return snippet.get("title") or items[0].get("id")
    except Exception:
        return None


@router.post("/youtube-destinations/{destination_id}/disconnect")
async def disconnect(destination_id: str, _: None = Depends(require_admin)):
    from app.services import youtube_oauth as oauth

    oauth.disconnect(destination_id)
    return {"disconnected": True}


@router.delete("/youtube-destinations/{destination_id}")
async def delete(destination_id: str, _: None = Depends(require_admin)):
    repo.delete_destination(destination_id)
    return {"deleted": True}
