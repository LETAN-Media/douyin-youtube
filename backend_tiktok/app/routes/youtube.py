from fastapi import APIRouter, Depends

from ..dependencies import require_admin

router = APIRouter(prefix="/api/tiktok/youtube", tags=["youtube"])


@router.get("/destinations/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def list_destinations(pipeline_id: str):
    from ..db.repositories import destinations

    return await destinations.list_destinations(pipeline_id)


@router.post("/destinations", dependencies=[Depends(require_admin)])
async def create_destination(body: dict):
    import secrets as _secrets

    dest_id = body.get("id") or f"dest_{_secrets.token_hex(8)}"
    from ..db.repositories import destinations

    return await destinations.create_destination(
        destination_id=dest_id,
        pipeline_id=body["pipeline_id"],
        channel_id=body.get("channel_id"),
        channel_name=body.get("channel_name"),
        account_id=body.get("account_id"),
        visibility=body.get("visibility", "public"),
    )


@router.post("/oauth/authorize/{pipeline_id}/{destination_id}", dependencies=[Depends(require_admin)])
async def oauth_authorize(pipeline_id: str, destination_id: str, return_to: str | None = None):
    from ..services.youtube_oauth import build_auth_url

    auth_url, state = await build_auth_url(destination_id, pipeline_id, return_to=return_to)
    return {"auth_url": auth_url, "state": state}


@router.get("/oauth/callback", dependencies=[Depends(require_admin)])
async def oauth_callback(code: str, state: str):
    from ..services.youtube_oauth import handle_callback

    result = await handle_callback(code, state)
    return result


@router.get("/destinations/{destination_id}/credentials", dependencies=[Depends(require_admin)])
async def check_credentials(destination_id: str):
    from ..db.repositories import youtube_auth

    row = await youtube_auth.get_credentials(destination_id)
    return {"configured": row is not None, "destination_id": destination_id}


@router.delete("/destinations/{destination_id}/credentials", dependencies=[Depends(require_admin)])
async def delete_credentials(destination_id: str):
    from ..db.repositories import destinations, youtube_auth

    await youtube_auth.delete_credentials(destination_id)
    await destinations.update_destination_connected(destination_id, connected=False)
    return {"status": "deleted", "destination_id": destination_id}
