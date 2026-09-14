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
    ) -> dict[str, Any] | None:
        path = Path(file_path)
        with SessionLocal() as db:
            video_id = upload_video(
                db=db,
                file_path=path,
                title=title,
                description=description,
                privacy_status="public",
                destination_id=self.destination.id,
            )

        return {
            "video_id": video_id,
            "url": (
                f"https://youtu.be/{video_id}"
            ),
        }
