"""High-level publish orchestration wrapping facebook_publisher."""
import logging
from datetime import datetime, timezone

import httpx

from ..config import settings
from ..db.models import Pipeline
from . import facebook_publisher as facebook_pub

logger = logging.getLogger("backend-youtube.publish")


async def publish(
    session,
    client: httpx.AsyncClient,
    page_access_token: str,
    pipeline: Pipeline,
    queue_item,
    media,
    caption: str | None,
    hashtags: list[str] | None,
    title: str | None,
    description: str | None,
    publish_mode: str,
) -> dict:
    """Publish a video to a Facebook page (Reels or Video). Returns metadata dict."""
    page_id = pipeline.default_facebook_page_id or queue_item.facebook_page_id
    if not page_id:
        raise facebook_pub.FacebookError("No Facebook page id available for publish")
    from ..db.repositories import facebook_pages as fb_repo
    page_row = await fb_repo.get_facebook_page(session, queue_item.facebook_page_id)
    if page_row is None:
        raise facebook_pub.FacebookError("Facebook page row not found")
    fb_page_id = page_row.page_id
    if not media or not media.local_path:
        raise facebook_pub.FacebookError("No local media file available for publish")
    is_reel = publish_mode in ("reels", "reeels_or_video", "reels_or_video")
    upload = await facebook_pub.upload_video(
        client,
        page_access_token,
        fb_page_id,
        media.local_path,
        caption or title or "",
        description=description,
        is_reel=is_reel,
    )
    video_id = upload.get("id")
    if not video_id:
        raise facebook_pub.FacebookError("Facebook video upload did not return an id")
    published_id: str | None = None
    reel_id: str | None = None
    if is_reel:
        container = await facebook_pub.create_reel_container(client, page_access_token, fb_page_id, video_id, caption or "", hashtags)
        published_id = container.get("post_id") or video_id
        reel_id = video_id
    else:
        published_id = video_id
    return {
        "id": published_id or video_id,
        "facebook_video_id": video_id,
        "facebook_reel_id": reel_id,
        "is_reel": is_reel,
        "publish_mode": publish_mode,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
