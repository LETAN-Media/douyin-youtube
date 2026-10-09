"""Cloudflare R2 media library (S3-compatible, boto3). Metadata in Turso, bytes in R2."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-audio.r2")


class R2Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _client():
    try:
        import boto3
    except ImportError:
        raise R2Error("R2_SDK_MISSING", "boto3 is not installed.")
    from app.config import settings

    if not settings.r2_configured():
        raise R2Error("R2_NOT_CONFIGURED", "R2_* env is not configured.")
    endpoint = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _bucket() -> str:
    from app.config import settings

    bucket = (settings.R2_BUCKET or "").strip()
    if not bucket:
        raise R2Error("R2_NOT_CONFIGURED", "R2_BUCKET is not configured.")
    return bucket


def pipeline_prefix(pipeline_id: str, kind: str = "backgrounds") -> str:
    return f"audio/pipelines/{pipeline_id}/{kind}/"


def upload_file(local_path: Path, object_key: str,
                content_type: str | None = None) -> dict[str, Any]:
    client = _client()
    bucket = _bucket()
    extra = {"ContentType": content_type} if content_type else {}
    try:
        client.upload_file(str(local_path), bucket, object_key, ExtraArgs=extra)
    except Exception as exc:
        raise R2Error("R2_UPLOAD_FAILED", f"{type(exc).__name__}: {exc}"[:300])
    logger.info("r2 upload ok: %s (%d bytes)", object_key, local_path.stat().st_size)
    return {"object_key": object_key, "bytes": local_path.stat().st_size}


def object_exists(object_key: str) -> bool:
    from app.config import settings

    if not settings.r2_configured():
        return bool(object_key)
    try:
        _client().head_object(Bucket=_bucket(), Key=object_key)
        return True
    except Exception:
        return False


def get_object_metadata(object_key: str) -> dict[str, Any] | None:
    try:
        res = _client().head_object(Bucket=_bucket(), Key=object_key)
        return {
            "content_length": res.get("ContentLength", 0),
            "content_type": res.get("ContentType", ""),
        }
    except Exception:
        return None


def download_file(object_key: str, dest: Path) -> Path:
    client = _client()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(_bucket(), object_key, str(dest))
    except Exception as exc:
        raise R2Error("R2_DOWNLOAD_FAILED", f"{type(exc).__name__}: {exc}"[:300])
    return dest


def delete_object(object_key: str) -> None:
    try:
        _client().delete_object(Bucket=_bucket(), Key=object_key)
    except Exception as exc:
        raise R2Error("R2_DELETE_FAILED", f"{type(exc).__name__}: {exc}"[:300])


def presigned_url(object_key: str, expires: int = 3600) -> str:
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": object_key},
            ExpiresIn=expires)
    except Exception as exc:
        raise R2Error("R2_URL_FAILED", f"{type(exc).__name__}: {exc}"[:300])


def public_url(object_key: str) -> str | None:
    from app.config import settings

    base = (settings.R2_PUBLIC_BASE_URL or "").strip().rstrip("/")
    return f"{base}/{object_key}" if base else None
