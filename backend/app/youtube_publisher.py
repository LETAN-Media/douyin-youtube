import logging
from pathlib import Path
from typing import Any

from app.db import SessionLocal
from app.models import Destination
from app.publishers import PublisherAdapter
from app.youtube import (
    load_credentials,
    upload_video,
)

logger = logging.getLogger("douyin-youtube-youtube-publisher")


class YouTubePublisher(PublisherAdapter):
    def connect(self) -> bool:
        try:
            with SessionLocal() as db:
                load_credentials(
                    db,
                    destination_id=self.destination.id,
                )
            return True
        except Exception:
            return False

    def validate_credentials(self) -> bool:
        try:
            with SessionLocal() as db:
                load_credentials(
                    db,
                    destination_id=self.destination.id,
                )
            return True
        except Exception:
            return False

    def get_account_info(self) -> dict[str, Any] | None:
        return {
            "channel_id": (
                self.destination.external_account_id
            ),
            "channel_title": (
                self.destination.external_account_name
            ),
        }

    def publish_video(
        self,
        file_path: str,
        title: str,
        description: str,
        publish_at: Any = None,
        publish_mode: str | None = None,
        privacy_status: str | None = None,
    ) -> dict[str, Any] | None:
        path = Path(file_path)
        mode = (publish_mode or "").lower() or None
        if mode is None and publish_at is not None:
            mode = "scheduled"
        if mode is None:
            # Infer from explicit privacy or channel default.
            default_mode = (getattr(self.destination, "youtube_default_publish_mode", None) or "immediate").lower()
            if privacy_status:
                mode = {"public": "immediate", "private": "private", "unlisted": "unlisted"}.get(
                    privacy_status.lower(), default_mode
                )
            else:
                mode = default_mode if default_mode in ("immediate", "scheduled", "private", "unlisted") else "immediate"
        from app.youtube_scheduling import MODE_TO_PRIVACY

        privacy = privacy_status or MODE_TO_PRIVACY.get(mode or "immediate", "public")
        with SessionLocal() as db:
            video_id = upload_video(
                db=db,
                file_path=path,
                title=title,
                description=description,
                privacy_status=privacy,
                destination_id=self.destination.id,
                publish_at=publish_at,
                publish_mode=mode,
            )

        return {
            "video_id": video_id,
            "url": (
                f"https://youtu.be/{video_id}"
            ),
        }
