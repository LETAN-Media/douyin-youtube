"""Durable project pause after provider quota errors, plus optional upload budget."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, or_
from app.config import settings
from app.models import AppSetting, VideoJob

PAUSE_KEY = 'youtube_upload_quota_pause_until'


def quota_block_reason(db, now=None, include_pending=True, exclude_job_id=None, destination_id=None):
    now = now or datetime.now(timezone.utc)
    for key in [PAUSE_KEY] + ([f"{PAUSE_KEY}:{destination_id}"] if destination_id else []):
        row = db.get(AppSetting, key)
        if row:
            try:
                until = datetime.fromisoformat(row.value)
                if until > now:
                    return f'YOUTUBE_QUOTA_EXHAUSTED until {until.isoformat()}'
            except (ValueError, TypeError):
                pass
    budget = settings.youtube_project_daily_upload_budget
    if budget:
        local = now.astimezone(ZoneInfo('America/Los_Angeles'))
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        statuses = ['published', 'downloading', 'uploading'] + (['pending', 'scheduled'] if include_pending else [])
        query = select(func.count(VideoJob.id)).where(VideoJob.updated_at >= start, or_(VideoJob.status.in_(statuses), VideoJob.youtube_video_id.is_not(None)))
        if exclude_job_id:
            query = query.where(VideoJob.id != exclude_job_id)
        used = db.scalar(query) or 0
        if used >= budget:
            return f'YOUTUBE_PROJECT_UPLOAD_BUDGET_REACHED {used}/{budget}'
    return None


def is_quota_error(error):
    text = str(error).lower().replace('_', '')
    return any(x in text for x in ('quotaexceeded', 'dailylimitexceeded', 'uploadlimitexceeded', 'quota exhausted'))


def pause_after_quota_error(db, now=None, destination_id=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('America/Los_Angeles'))
    until = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    key = f"{PAUSE_KEY}:{destination_id}" if destination_id else PAUSE_KEY
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=until.isoformat())
        db.add(row)
    else:
        row.value = until.isoformat()
    return until
