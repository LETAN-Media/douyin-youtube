import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger("douyin-youtube-url")


class DouyinProfileUrl:
    def __init__(self, original: str, sec_uid: str, canonical: str):
        self.original = original
        self.sec_uid = sec_uid
        self.canonical = canonical


def parse_douyin_profile_url(raw_url: str) -> DouyinProfileUrl | None:
    value = raw_url.strip()
    if not value:
        return None

    if not value.startswith("http://") and not value.startswith("https://"):
        value = "https://" + value

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    hostname = (parsed.hostname or "").lower()
    path = parsed.path or ""

    is_douyin_host = (
        hostname == "douyin.com"
        or hostname.endswith(".douyin.com")
        or hostname == "m.douyin.com"
    )

    if not is_douyin_host:
        return None

    sec_uid = None

    share_match = re.search(r'/share/user/([A-Za-z0-9_-]+)', path)
    if share_match:
        sec_uid = share_match.group(1)
    else:
        user_match = re.search(r'/user/([A-Za-z0-9_-]+)', path)
        if user_match:
            sec_uid = user_match.group(1)

    if not sec_uid:
        return None

    canonical = f"https://www.douyin.com/user/{sec_uid}"

    return DouyinProfileUrl(
        original=raw_url.strip(),
        sec_uid=sec_uid,
        canonical=canonical,
    )
