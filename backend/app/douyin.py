import base64
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import settings


@dataclass
class DownloadResult:
    file_path: Path
    title: str


def ensure_temp_dir() -> Path:
    path = Path(settings.temp_dir)
    path.mkdir(
        parents=True,
        exist_ok=True,
    )
    return path


def create_cookie_file() -> Path | None:
    encoded = settings.douyin_cookies_b64.strip()

    if not encoded:
        return None

    temp_dir = ensure_temp_dir()
    cookie_path = temp_dir / "douyin-cookies.txt"

    try:
        data = base64.b64decode(encoded)
    except Exception as exc:
        raise RuntimeError(
            "DOUYIN_COOKIES_B64 không phải base64 hợp lệ"
        ) from exc

    cookie_path.write_bytes(data)

    return cookie_path


def find_downloaded_file(job_id: str) -> Path:
    temp_dir = ensure_temp_dir()

    candidates = [
        path
        for path in temp_dir.glob(f"{job_id}.*")
        if path.is_file()
        and not path.name.endswith(".part")
        and not path.name.endswith(".ytdl")
    ]

    if not candidates:
        raise RuntimeError(
            "yt-dlp hoàn tất nhưng không tìm thấy file video"
        )

    candidates.sort(
        key=lambda item: item.stat().st_size,
        reverse=True,
    )

    return candidates[0]


def download_video(
    url: str,
    job_id: str,
) -> DownloadResult:
    temp_dir = ensure_temp_dir()
    cookie_path = create_cookie_file()

    output_template = str(
        temp_dir / f"{job_id}.%(ext)s"
    )

    options: dict = {
        "format": "bv*+ba/b",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "continuedl": True,
        "overwrites": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        },
    }

    if cookie_path:
        options["cookiefile"] = str(cookie_path)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                url,
                download=True,
            )
    except Exception as exc:
        raise RuntimeError(
            f"Không tải được video Douyin: {exc}"
        ) from exc

    if not info:
        raise RuntimeError(
            "Douyin không trả về thông tin video"
        )

    file_path = find_downloaded_file(job_id)

    title = str(
        info.get("title")
        or info.get("description")
        or "Douyin video"
    ).strip()

    if not title:
        title = "Douyin video"

    return DownloadResult(
        file_path=file_path,
        title=title[:100],
    )


def cleanup_job_files(job_id: str) -> None:
    temp_dir = ensure_temp_dir()

    for path in temp_dir.glob(f"{job_id}.*"):
        if not path.is_file():
            continue

        try:
            path.unlink()
        except OSError:
            pass
