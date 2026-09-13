import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import yt_dlp

from app.config import settings


logger = logging.getLogger("douyin-downloader")

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Mobile/15E148 Safari/604.1"
)


@dataclass
class DownloadResult:
    file_path: Path
    title: str
    source_context: str = ""
    parser_name: str = ""


def ensure_temp_dir() -> Path:
    path = Path(settings.temp_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_http_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError(f"URL không hợp lệ: {value}")

    if not parsed.hostname:
        raise RuntimeError(f"URL thiếu hostname: {value}")

    return value


def extract_first_string(data, keys: tuple[str, ...]) -> str | None:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in data.values():
            found = extract_first_string(value, keys)

            if found:
                return found

    if isinstance(data, list):
        for value in data:
            found = extract_first_string(value, keys)

            if found:
                return found

    return None


def call_rcuts_parser(
    api_url: str,
    source_url: str,
    share_text: str | None,
) -> dict:
    clipboard = share_text.strip() if share_text and share_text.strip() else source_url

    payload = urlencode(
        {
            "url": source_url,
            "token": settings.rcuts_token,
            "clipboard": clipboard,
        }
    ).encode("utf-8")

    request = Request(
        api_url,
        data=payload,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Rcuts API HTTP {exc.code}: {body[:500]}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Không kết nối được Rcuts API: {exc}"
        ) from exc

    try:
        text = raw.decode("utf-8")
        data = json.loads(text)
    except Exception as exc:
        raise RuntimeError(
            f"Rcuts API không trả JSON hợp lệ: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Rcuts API trả response không đúng định dạng"
        )

    return data


def extract_video_url(data: dict) -> str:
    video_url = extract_first_string(
        data,
        (
            "video_url",
            "videoUrl",
            "play_url",
            "playUrl",
        ),
    )

    if not video_url:
        raise RuntimeError(
            f"Rcuts parser không trả video_url. "
            f"Keys={list(data.keys())}"
        )

    return validate_http_url(video_url)


def extract_title(data: dict) -> str:
    title = extract_first_string(
        data,
        (
            "title",
            "desc",
            "description",
            "video_title",
            "videoTitle",
            "video_name",
        ),
    )

    if not title:
        return ""

    return title[:100]


def build_source_context(data: dict) -> str:
    """Build rich source context for AI from Rcuts metadata."""
    interesting_keys = {
        "title",
        "desc",
        "description",
        "caption",
        "content",
        "text",
        "author",
        "nickname",
        "hashtags",
        "hashtag",
        "tags",
        "tag_list",
        "text_extra",
        "challenge",
        "challenges",
        "video_name",
        "cover",
        "sound",
    }

    lines: list[str] = []
    seen: set[str] = set()

    def walk(value, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(
                    child_value,
                    str(child_key),
                )
            return

        if isinstance(value, list):
            for item in value:
                walk(item, key)
            return

        if not isinstance(
            value,
            (str, int, float),
        ):
            return

        text = str(value).strip()

        if not text:
            return

        key_lower = key.lower()

        useful = (
            key_lower in interesting_keys
            or "title" in key_lower
            or "desc" in key_lower
            or "tag" in key_lower
            or "author" in key_lower
            or "caption" in key_lower
        )

        if not useful:
            return

        fingerprint = (
            key_lower
            + ":"
            + text
        )

        if fingerprint in seen:
            return

        seen.add(fingerprint)

        lines.append(
            f"{key}: {text}"
        )

    walk(data)

    if not lines:
        try:
            return json.dumps(
                data,
                ensure_ascii=False,
            )[:6000]
        except Exception:
            return ""

    return "\n".join(lines)[:6000]


def download_http_video(
    video_url: str,
    job_id: str,
) -> Path:
    temp_dir = ensure_temp_dir()

    output = temp_dir / f"{job_id}.mp4"

    request = Request(
        video_url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": "https://www.douyin.com/",
        },
    )

    try:
        with urlopen(
            request,
            timeout=60,
        ) as response:
            content_type = (
                response.headers
                .get("Content-Type", "")
                .lower()
            )

            if (
                "video" not in content_type
                and "octet-stream" not in content_type
            ):
                logger.warning(
                    "Unexpected Content-Type from video URL: %s",
                    content_type,
                )

            with output.open("wb") as file:
                while True:
                    chunk = response.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    file.write(chunk)

    except Exception:
        output.unlink(
            missing_ok=True
        )
        raise

    if not output.exists():
        raise RuntimeError(
            "Không tạo được file video"
        )

    if output.stat().st_size < 1024:
        output.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            "Video tải về quá nhỏ"
        )

    return output


def try_rcuts_download(
    api_url: str,
    parser_name: str,
    source_url: str,
    job_id: str,
    share_text: str | None,
) -> DownloadResult | None:
    logger.info(
        "Trying Rcuts %s parser for job=%s url=%s",
        parser_name,
        job_id,
        api_url,
    )

    data = call_rcuts_parser(
        api_url=api_url,
        source_url=source_url,
        share_text=share_text,
    )

    video_url = extract_video_url(data)

    title = extract_title(data)

    file_path = download_http_video(
        video_url,
        job_id,
    )

    logger.info(
        "Rcuts %s OK job=%s size=%s",
        parser_name,
        job_id,
        file_path.stat().st_size,
    )

    source_context = build_source_context(data)

    return DownloadResult(
        file_path=file_path,
        title=title,
        source_context=source_context,
        parser_name=parser_name,
    )


def find_downloaded_file(
    job_id: str,
) -> Path:
    temp_dir = ensure_temp_dir()

    candidates = [
        path
        for path in temp_dir.glob(
            f"{job_id}.*"
        )
        if path.is_file()
        and not path.name.endswith(".part")
        and not path.name.endswith(".ytdl")
    ]

    if not candidates:
        raise RuntimeError(
            "yt-dlp hoàn tất nhưng không tìm thấy file"
        )

    candidates.sort(
        key=lambda item: item.stat().st_size,
        reverse=True,
    )

    return candidates[0]


def download_with_ytdlp(
    source_url: str,
    job_id: str,
) -> DownloadResult:
    temp_dir = ensure_temp_dir()

    output_template = str(
        temp_dir / f"{job_id}.%(ext)s"
    )

    options = {
        "format": "bv*+ba/b",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "continuedl": True,
        "overwrites": True,
        "http_headers": {
            "User-Agent": USER_AGENT,
        },
    }

    try:
        with yt_dlp.YoutubeDL(
            options
        ) as ydl:
            info = ydl.extract_info(
                source_url,
                download=True,
            )
    except Exception as exc:
        raise RuntimeError(
            f"yt-dlp fallback thất bại: {exc}"
        ) from exc

    file_path = find_downloaded_file(
        job_id
    )

    title = str(
        (info or {}).get("title")
        or (info or {}).get("description")
        or ""
    ).strip()

    tags = (
        (info or {}).get("tags")
        or []
    )

    description = str(
        (info or {}).get("description")
        or ""
    ).strip()

    context_parts = [
        f"title: {title}",
    ]

    if description:
        context_parts.append(
            f"description: {description}"
        )

    if tags:
        context_parts.append(
            "hashtags/tags: "
            + " ".join(
                str(tag)
                for tag in tags
            )
        )

    return DownloadResult(
        file_path=file_path,
        title=title[:100],
        source_context="\n".join(
            context_parts
        )[:6000],
        parser_name="yt_dlp",
    )


def download_video(
    url: str,
    job_id: str,
    share_text: str | None = None,
) -> DownloadResult:
    source_url = validate_http_url(
        url
    )

    primary_api = settings.rcuts_primary_api_url or settings.rcuts_api_url
    fallback_api = settings.rcuts_fallback_api_url or settings.rcuts_api_url

    if primary_api and primary_api != fallback_api:
        try:
            result = try_rcuts_download(
                api_url=primary_api,
                parser_name="rcuts_primary",
                source_url=source_url,
                job_id=job_id,
                share_text=share_text,
            )
            if result:
                return result
        except Exception as exc:
            logger.warning(
                "Rcuts primary failed for job=%s: %s",
                job_id,
                exc,
            )

    if fallback_api:
        try:
            result = try_rcuts_download(
                api_url=fallback_api,
                parser_name="rcuts_fallback",
                source_url=source_url,
                job_id=job_id,
                share_text=share_text,
            )
            if result:
                return result
        except Exception as exc:
            logger.warning(
                "Rcuts fallback failed for job=%s: %s",
                job_id,
                exc,
            )

    logger.info(
        "Trying yt-dlp fallback for job=%s",
        job_id,
    )

    return download_with_ytdlp(
        source_url,
        job_id,
    )


def cleanup_job_files(
    job_id: str,
) -> None:
    temp_dir = ensure_temp_dir()

    for path in temp_dir.glob(
        f"{job_id}.*"
    ):
        if not path.is_file():
            continue

        try:
            path.unlink()
        except OSError:
            logger.warning(
                "Không xóa được temp file %s",
                path,
            )
