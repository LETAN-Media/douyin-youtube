"""Manual Facebook -> YouTube publishing API.

Independent from inventory/scheduler/auto-publish. All endpoints require
admin (the dashboard proxies them behind login). Never returns credentials
or FastSaver download URLs to the browser.
"""

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import destinations, manual_publications as manual_repo
from ..db.repositories import youtube_auth
from ..services.facebook_manual_publisher import generate_manual_metadata
from ..services.facebook_media import FacebookMediaError, FacebookMediaResolver
from ..services.facebook_url import is_facebook_url
from ..services.facebook_youtube_publisher import (
    YouTubePublisherError,
    validate_publish_at,
    validate_visibility,
)
from ..services.facebook_ai_metadata import MetadataError

router = APIRouter(prefix="/api/facebook", tags=["facebook-manual"])

# Facebook URL shapes accepted for manual mode. Bare profile/page URLs
# (no video marker) are rejected — manual mode publishes videos only.
_VIDEO_MARKERS = ("/reel/", "/videos/", "/watch", "/share/")


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _check_manual_video_url(raw_url: str | None) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise _err(400, "MANUAL_INVALID_URL", "Dán một Facebook video URL.")
    if not is_facebook_url(url):
        raise _err(400, "MANUAL_INVALID_URL", "URL không phải Facebook video hợp lệ.")
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        path = (urllib.parse.urlparse(url).path or "").lower()
    except Exception:
        raise _err(400, "MANUAL_INVALID_URL", "URL không hợp lệ.")
    if host == "fb.watch":
        return url
    if not any(m in path for m in _VIDEO_MARKERS):
        raise _err(
            400, "MANUAL_INVALID_URL",
            "Chỉ nhận link video Facebook (reel / videos / watch / fb.watch), "
            "không nhận link profile/page.",
        )
    return url


def _normalize_hashtags(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for tag in raw or []:
        t = str(tag or "").strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t.lstrip("#")
        t = "#" + t[1:].replace(" ", "")
        if t != "#" and t.lower() not in {x.lower() for x in out}:
            out.append(t)
        if len(out) >= 15:
            break
    return out


# ---------- Schemas ----------


class ManualResolveBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class ManualGenerateBody(BaseModel):
    destination_id: str = Field(min_length=1, max_length=100)
    caption: str | None = Field(default=None, max_length=10000)
    source_url: str | None = Field(default=None, max_length=2000)


class ManualPublishBody(BaseModel):
    destination_id: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default="", max_length=10000)
    hashtags: list[str] | None = None
    visibility: str = Field(default="public", max_length=20)
    publish_at: str | None = Field(default=None, max_length=64)
    caption: str | None = Field(default=None, max_length=10000)
    thumbnail_url: str | None = Field(default=None, max_length=2000)
    duration: float | None = None
    force_duplicate: bool = False


# ---------- Connected channels ----------


@router.get("/youtube-destinations")
async def list_all_connected_destinations(_: None = Depends(require_admin)) -> list[dict]:
    return await destinations.list_connected_with_pipelines()


# ---------- Resolve / preview (metadata only, never the download URL) ----------


@router.post("/manual/resolve")
async def resolve_manual_video(body: ManualResolveBody, _: None = Depends(require_admin)) -> dict:
    url = _check_manual_video_url(body.url)
    try:
        resolver = FacebookMediaResolver.from_settings()
        media = await resolver.resolve(url)
    except FacebookMediaError as exc:
        raise _err(400, "MANUAL_RESOLVE_FAILED", str(exc) or "Không nhận diện được video.")
    return {
        "source_url": url,
        "caption": media.caption,
        "thumbnail_url": media.thumbnail_url,
        "duration": media.duration,
        "media_type": media.media_type,
    }


@router.post("/manual/generate")
async def generate_manual_metadata_route(
    body: ManualGenerateBody, _: None = Depends(require_admin)
) -> dict:
    destination = await destinations.get_destination(body.destination_id)
    if destination is None:
        raise _err(404, "DESTINATION_NOT_FOUND", "Không tìm thấy kênh.")
    try:
        out = await generate_manual_metadata(
            pipeline_id=destination.get("pipeline_id"),
            caption=body.caption,
            source_url=body.source_url,
        )
    except MetadataError as exc:
        raise _err(400, exc.code or "MANUAL_AI_FAILED", str(exc) or "AI không tạo được metadata.")
    return out


# ---------- Publish (validate + enqueue, never uploads inline) ----------


@router.post("/manual/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_manual_video(body: ManualPublishBody, _: None = Depends(require_admin)) -> dict:
    url = _check_manual_video_url(body.source_url)
    destination = await destinations.get_destination(body.destination_id)
    if destination is None:
        raise _err(404, "DESTINATION_NOT_FOUND", "Không tìm thấy kênh.")
    if not destination.get("connected") or not destination.get("channel_id"):
        raise _err(400, "DESTINATION_NOT_CONNECTED", "Kênh YouTube chưa được kết nối.")
    if not destination.get("enabled", True):
        raise _err(400, "DESTINATION_DISABLED", "Kênh đích đang tắt.")
    if await youtube_auth.get_credentials(body.destination_id) is None:
        raise _err(400, "YOUTUBE_AUTH_FAILED", "Kênh chưa có credentials. Kết nối lại YouTube.")

    title = (body.title or "").strip()
    if not title:
        raise _err(400, "MANUAL_METADATA_INVALID", "Tiêu đề không được để trống.")
    try:
        visibility = validate_visibility(body.visibility or "public")
    except YouTubePublisherError as exc:
        raise _err(400, "INVALID_VISIBILITY", str(exc))

    publish_at: str | None = None
    if body.publish_at:
        try:
            publish_at = validate_publish_at(body.publish_at)
        except YouTubePublisherError as exc:
            raise _err(400, "INVALID_PUBLISH_AT", str(exc))
        # YouTube scheduling requires a private upload + publishAt.
        visibility = "private"

    if not body.force_duplicate:
        existing = await manual_repo.find_duplicate(body.destination_id, url)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "DUPLICATE_VIDEO",
                    "message": "Video này đã được đăng lên kênh này.",
                    "existing_id": existing["id"],
                    "existing_status": existing["status"],
                },
            )

    hashtags = _normalize_hashtags(body.hashtags)
    created = await manual_repo.create_manual_publication(
        destination_id=body.destination_id,
        pipeline_id=destination.get("pipeline_id") or "",
        source_url=url,
        caption=body.caption,
        thumbnail_url=body.thumbnail_url,
        duration=body.duration,
        title=title[:100],
        description=(body.description or "")[:5000],
        hashtags=hashtags,
        visibility=visibility,
        publish_at=publish_at,
    )
    return {"id": created["id"], "status": created["status"], **manual_repo.to_safe_dict(created)}


# ---------- Status / history / retry ----------


@router.get("/manual/publications")
async def list_manual_publication_history(
    destination_id: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_admin),
) -> dict:
    items, total = await manual_repo.list_manual_publications(
        destination_id=destination_id, limit=limit, offset=offset
    )
    return {"items": items, "total": total}


@router.get("/manual/publications/{manual_id}")
async def get_manual_publication_status(
    manual_id: str, _: None = Depends(require_admin)
) -> dict:
    row = await manual_repo.get_manual_publication(manual_id)
    if row is None:
        raise _err(404, "MANUAL_NOT_FOUND", "Không tìm thấy bản đăng.")
    return manual_repo.to_safe_dict(row)


@router.post("/manual/publications/{manual_id}/retry")
async def retry_manual_publication(
    manual_id: str, _: None = Depends(require_admin)
) -> dict:
    row = await manual_repo.retry_manual(manual_id)
    if row is None:
        raise _err(404, "MANUAL_NOT_FOUND", "Không tìm thấy bản đăng hoặc trạng thái không retry được.")
    return manual_repo.to_safe_dict(row)
