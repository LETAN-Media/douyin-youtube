"""Fail-closed upload evidence. Never retry an external upload on a DB error.

The remote intent survives container replacement. The fsynced receipt bridges a
DB outage after YouTube returns an ID; mount upload_journal_dir persistently for
automatic receipt recovery across container replacement. Without the receipt,
the remote intent still requires manual reconciliation, never a second upload.
"""
import json
import os
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.models import AppSetting

PREFIX = "youtube_upload_attempt:"


class UploadReconciliationRequired(RuntimeError):
    pass


def read_attempt(db, job_id):
    row = db.get(AppSetting, PREFIX + job_id)
    return json.loads(row.value) if row else None


def write_attempt(db, job_id, evidence):
    row = db.get(AppSetting, PREFIX + job_id)
    if row is None:
        row = AppSetting(key=PREFIX + job_id, value="{}")
        db.add(row)
    row.value = json.dumps(evidence)
    publication_id = evidence.get("publication_id")
    if publication_id:
        key = "youtube_upload_publication:" + publication_id
        owner = db.get(AppSetting, key)
        if owner is not None and owner.value != job_id:
            previous = read_attempt(db, owner.value)
            if previous and previous.get("phase") == "rejected":
                owner.value = job_id
            else:
                raise UploadReconciliationRequired("Another job already owns this publication upload")
        if owner is None:
            db.add(AppSetting(key=key, value=job_id))


def receipt_path(job_id):
    # Job IDs are UUIDs; never allow a request value to escape the journal.
    return Path(settings.upload_journal_dir) / (str(UUID(job_id)) + ".json")


def save_receipt(job_id, evidence):
    path = receipt_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        os.chmod(temporary, 0o600)
        json.dump(evidence, file)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_receipt(job_id):
    path = receipt_path(job_id)
    return json.loads(path.read_text()) if path.exists() else None


def guard_retry(db, publication):
    from sqlalchemy import select
    from app.models import VideoJob
    owner = db.get(AppSetting, "youtube_upload_publication:" + publication.id)
    if owner:
        attempt = read_attempt(db, owner.value)
        if not attempt or attempt.get("phase") != "rejected":
            raise UploadReconciliationRequired("UPLOAD_RECONCILIATION_REQUIRED: publication upload intent exists")
    for job in db.scalars(select(VideoJob).where(VideoJob.publication_id == publication.id)):
        attempt = read_attempt(db, job.id)
        if (attempt and attempt.get("phase") != "rejected") or read_receipt(job.id):
            raise UploadReconciliationRequired(
                "UPLOAD_RECONCILIATION_REQUIRED: prior upload intent/receipt exists; verify YouTube before retry"
            )
        # Historical failures have no receipt. A missing ID alone proves nothing.
        if job.status in {"uploading", "upload_unknown"} or (
            job.error and not job.error.startswith("BEFORE_UPLOAD:")
            and ("Hrana" in job.error or "AFTER_UPLOAD" in job.error)
        ):
            raise UploadReconciliationRequired(
                "UPLOAD_RECONCILIATION_REQUIRED: previous upload outcome is uncertain"
            )
