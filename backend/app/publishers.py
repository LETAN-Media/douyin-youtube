import logging
from abc import (
    ABC,
    abstractmethod,
)
from typing import Any

from app.models import Destination

logger = logging.getLogger("douyin-youtube-publishers")


class PublisherAdapter(ABC):
    def __init__(self, destination: Destination):
        self.destination = destination

    @abstractmethod
    def connect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate_credentials(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def publish_video(
        self,
        file_path: str,
        title: str,
        description: str,
        publish_at: Any = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError


def get_publisher(destination: Destination) -> PublisherAdapter | None:
    platform = (destination.platform or "").lower()

    if platform == "youtube":
        from app.youtube_publisher import YouTubePublisher
        return YouTubePublisher(destination)

    if platform == "facebook":
        from app.facebook import FacebookPublisher
        return FacebookPublisher(destination)

    logger.warning("Unsupported platform: %s", platform)
    return None
