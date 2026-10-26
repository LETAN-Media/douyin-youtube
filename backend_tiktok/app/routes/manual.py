from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import json as jsonlib
import secrets as _secrets

from ..dependencies import require_admin
from ..db.repositories import destinations, pipelines, reels
from ..db.repositories import publications as publications_repo
from ..db.repositories import manual_publications
from ..services.tiktok_media import resolve_manual_media, download_media, ManualMediaError, source_hash
from ..services.tiktok_source_api import TikTokSourceAPIProvider
from ..services.youtube_publisher import publish_video_to_youtube

router = APIRouter(prefix="/api/tiktok/manual", tags=["manual-publish"])


@router.post("/resolve", dependencies=[Depends(require_admin)])
async def resolve_video_info(body: dict):
    """Resolve a TikTok video URL via Source API /video/info for the Manual tab.

    Returns metadata (video_id, title, caption, thumbnail, duration) before
    the user commits to publishing.  Does NOT download the MP4.
    """
    source_url = body.get("source_url") or body.get("url")
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url required")

    provider = TikTokSourceAPIProvider()
    try:
        media = await provider.resolve_media(source_url)
    except Exception as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=f"Video not found: {source_url}")
        raise HTTPException(status_code=502, detail=f"Source API resolution failed: {exc}")

    from ..services.tiktok_url import extract_video_id

    video_id = extract_video_id(source_url)

    return {
        "source_url": source_url,
        "video_id": video_id,
        "caption": media.caption,
        "thumbnail": media.thumbnail_url,
        "duration": media.duration,
        "play_count": media.play_count,
        "provider": provider.name,
    }


@router.post("/{pipeline_id}/{destination_id}", dependencies=[Depends(require_admin)])
async def create_manual_publication(
    pipeline_id: str, destination_id: str, body: dict, background: BackgroundTasks
):
    source_url = body.get("source_url")
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url required")

    dest = await destinations.get_destination(destination_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")

    s_hash = source_hash(source_url)
    existing = await manual_publications.find_manual_pub_by_hash(destination_id, s_hash)
    if existing and existing.get("status") in ("queued", "processing"):
        return {"publication_id": existing["id"], "status": existing["status"], "duplicate": True}

    pub_id = f"mpub_{_secrets.token_hex(8)}"
    pub = await manual_publications.create_manual_publication(
        pub_id=pub_id,
        destination_id=destination_id,
        pipeline_id=pipeline_id,
        source_url=source_url,
        source_hash=s_hash,
        caption=body.get("caption"),
        youtube_title=body.get("youtube_title"),
        youtube_description=body.get("youtube_description"),
        youtube_hashtags_json=jsonlib.dumps(body.get("hashtags", [])) if body.get("hashtags") else None,
        visibility=body.get("visibility", "public"),
        publish_at=body.get("publish_at"),
    )
    background.add_task(_do_manual_publish, pub_id)
    return {"publication_id": pub_id, "status": "queued"}


@router.get("/{pipeline_id}/{destination_id}", dependencies=[Depends(require_admin)])
async def list_manual_publications(pipeline_id: str, destination_id: str):
    return await manual_publications.list_manual_publications(destination_id)


@router.get("/item/{pub_id}", dependencies=[Depends(require_admin)])
async def get_manual_publication(pub_id: str):
    row = await manual_publications.get_manual_publication(pub_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


async def _do_manual_publish(pub_id: str):
    """Background task that resolves metadata via Source API, downloads MP4
    via PHIMTAT, then uploads to YouTube.
    """
    try:
        pub = await manual_publications.get_manual_publication(pub_id)
        if pub is None:
            return

        await manual_publications.set_manual_pub_started(pub_id)
        await manual_publications.set_manual_pub_status(pub_id, "processing", stage="resolving_metadata")

        # --- Step 1: Resolve metadata via Source API /video/info ---
        source_provider = TikTokSourceAPIProvider()
        metadata = await source_provider.resolve_media(pub["source_url"])
        await manual_publications.set_manual_pub_status(pub_id, "processing", stage="resolving_media")

        # --- Step 2: Resolve download URL via PHIMTAT shortcut ---
        media = await resolve_manual_media(pub["source_url"])
        video_path = await download_media(
            _to_manual_resolved(media), job_id=f"mpub_{pub_id}"
        )

        await manual_publications.set_manual_pub_status(pub_id, "processing", stage="publishing")
        await manual_publications.set_manual_pub_media(
            pub_id,
            thumbnail_url=metadata.thumbnail_url or media.thumbnail_url,
            duration=metadata.duration or media.duration,
            youtube_title=metadata.caption or pub.get("youtube_title"),
            youtube_description=pub.get("youtube_description"),
            youtube_hashtags_json=pub.get("youtube_hashtags_json"),
            caption=pub.get("caption"),
        )

        # Read back for final metadata
        updated = await manual_publications.get_manual_publication(pub_id)

        video_id = await publish_video_to_youtube(
            destination_id=pub["destination_id"],
            video_path=video_path,
            title=updated.get("youtube_title") or metadata.caption or media.caption or "TikTok video",
            description=updated.get("youtube_description") or "",
            hashtags_json=updated.get("youtube_hashtags_json") or "[]",
            thumbnail_url=updated.get("thumbnail_url"),
        )

        await manual_publications.set_manual_pub_yt_video(pub_id, video_id)
        await manual_publications.set_manual_pub_status(pub_id, "done", stage="completed")
    except ManualMediaError as exc:
        await manual_publications.mark_manual_pub_error(pub_id, f"{exc.code}: {exc}", retry_increment=False)
        await manual_publications.set_manual_pub_status(pub_id, "failed", stage="error")
    except Exception as exc:
        import logging

        logging.getLogger("backend-tiktok").exception("manual publish %s failed: %s", pub_id, exc)
        await manual_publications.mark_manual_pub_error(pub_id, str(exc))
        await manual_publications.set_manual_pub_status(pub_id, "failed", stage="error")


def _to_manual_resolved(media):
    from ..services.tiktok_media import ManualResolvedMedia

    # Already the right type
    if isinstance(media, ManualResolvedMedia):
        return media
    return ManualResolvedMedia(
        source_url=media.get("source_url", ""),
        download_url=media.get("download_url", ""),
        content_type=media.get("content_type", "video/mp4"),
        caption=media.get("caption"),
        thumbnail_url=media.get("thumbnail_url"),
        duration=media.get("duration"),
    )
