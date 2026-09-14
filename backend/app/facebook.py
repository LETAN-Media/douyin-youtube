import logging
from typing import Any

from app.models import Destination
from app.publishers import PublisherAdapter

logger = logging.getLogger("douyin-youtube-facebook")


class FacebookPublisher(PublisherAdapter):
    def connect(self) -> bool:
        logger.info(
            "Facebook connect placeholder for destination %s",
            self.destination.id,
        )
        return False

    def validate_credentials(self) -> bool:
        return False

    def get_account_info(self) -> dict[str, Any] | None:
        return None

    def publish_video(
        self,
        file_path: str,
        title: str,
        description: str,
        publish_at: Any = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "Facebook publisher chưa được triển khai"
        )
