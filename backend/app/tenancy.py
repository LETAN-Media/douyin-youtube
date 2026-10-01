"""Backend-enforced tenant isolation.

Every HTTP route authenticates via :func:`authenticate_request`, which resolves
an :class:`AuthContext` from EITHER:

1. a user session (``X-Session-Token`` header, ``Authorization: Bearer``,
   or ``dy_api_session`` cookie) created by ``POST /api/auth/login``, or
2. the legacy ``X-Admin-Token`` (system admin, full access — preserved so the
   existing admin flow keeps working while user auth rolls out).

The context is ALSO published into a :mod:`contextvars` slot so shared
helpers (``_require_youtube_channel``, ...) enforce ownership without
signature changes on every caller. Code running OUTSIDE a request
(worker / scheduler / monitor loops) sees the SYSTEM context, which may
touch all workspaces but must always propagate ``workspace_id`` onto rows
it creates — never mix data between tenants.

Regular users see ONLY rows whose ``workspace_id`` is one of their member
workspaces. Unknown IDs return 404 (never 403) so existence is not leaked.
"""

from __future__ import annotations

import hmac
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth as auth_lib
from app.config import settings
from app.db import get_db
from app.models import (
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    PipelineSource,
    Publication,
    User,
    VideoJob,
    Workspace,
    WorkspaceMember,
    YouTubeComment,
)


@dataclass
class AuthContext:
    user_id: str | None = None
    email: str | None = None
    is_system_admin: bool = False
    workspace_ids: list[str] = field(default_factory=list)
    via: str = "system"  # session | admin_token | system


SYSTEM_CTX = AuthContext(
    user_id=None,
    email=None,
    is_system_admin=True,
    workspace_ids=[],
    via="system",
)

_current: ContextVar[AuthContext] = ContextVar("tenant_ctx", default=SYSTEM_CTX)


def tenant_ctx() -> AuthContext:
    """Context for the current request (or SYSTEM for background jobs)."""
    return _current.get()


def _extract_session_token(request: Request) -> str:
    header = (request.headers.get("X-Session-Token") or "").strip()
    if header:
        return header
    authz = (request.headers.get("Authorization") or "").strip()
    if authz.lower().startswith("bearer "):
        return authz[7:].strip()
    cookie = request.cookies.get("dy_api_session") or ""
    return cookie.strip()


def _admin_token_valid(provided: str) -> bool:
    expected = settings.admin_token or ""
    return bool(expected) and bool(provided) and hmac.compare_digest(
        provided, expected
    )


def _member_workspace_ids(db: Session, user_id: str) -> list[str]:
    rows = (
        db.execute(
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [str(r) for r in rows]


async def authenticate_request(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthContext:
    """FastAPI dependency replacing ``require_admin`` on tenant routes.

    Accepts a user session OR the legacy admin token. Publishes the resolved
    context into the request-local ContextVar and returns it.
    """
    token = _extract_session_token(request)
    if token:
        found = auth_lib.lookup_session(db, token)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn",
            )
        _session_row, user = found
        ctx = AuthContext(
            user_id=user.id,
            email=user.email,
            is_system_admin=bool(user.is_system_admin),
            workspace_ids=(
                [] if user.is_system_admin else _member_workspace_ids(db, user.id)
            ),
            via="session",
        )
        _current.set(ctx)
        return ctx

    if _admin_token_valid(request.headers.get("X-Admin-Token") or ""):
        ctx = AuthContext(
            user_id=None,
            email=None,
            is_system_admin=True,
            workspace_ids=[],
            via="admin_token",
        )
        _current.set(ctx)
        return ctx

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thiếu xác thực (session hoặc X-Admin-Token)",
    )


def require_system_admin(ctx: AuthContext | None = None) -> AuthContext:
    """Dependency/ guard for admin-only routes (users, platform accounts)."""
    active = ctx if ctx is not None else tenant_ctx()
    if not active.is_system_admin:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    return active


# --------------------------------------------------------------------------
# Visibility primitives
# --------------------------------------------------------------------------

def _workspace_allows(ctx: AuthContext, workspace_id: str | None) -> bool:
    if ctx.is_system_admin:
        return True
    if not workspace_id:
        return False
    return str(workspace_id) in (ctx.workspace_ids or [])


def _pipeline_workspace_id(db: Session, pipeline_id: str | None) -> str | None:
    if not pipeline_id:
        return None
    ws = db.execute(
        select(Pipeline.workspace_id).where(Pipeline.id == pipeline_id)
    ).scalar_one_or_none()
    return str(ws) if ws else None


def _destination_workspace_id(
    db: Session, destination_id: str | None
) -> str | None:
    if not destination_id:
        return None
    row = db.execute(
        select(Destination.workspace_id, Destination.pipeline_id).where(
            Destination.id == destination_id
        )
    ).first()
    if row is None:
        return None
    ws, pipeline_id = row[0], row[1]
    if ws:
        return str(ws)
    return _pipeline_workspace_id(db, pipeline_id)


def pipeline_visible(db: Session, ctx: AuthContext, pipeline_id: str) -> bool:
    if ctx.is_system_admin:
        return True
    return _workspace_allows(ctx, _pipeline_workspace_id(db, pipeline_id))


def destination_visible(db: Session, ctx: AuthContext, destination_id: str) -> bool:
    if ctx.is_system_admin:
        return True
    return _workspace_allows(ctx, _destination_workspace_id(db, destination_id))


def visible_pipeline_ids(db: Session, ctx: AuthContext) -> set[str] | None:
    """None = unrestricted (system admin). Otherwise the allowed set."""
    if ctx.is_system_admin:
        return None
    if not ctx.workspace_ids:
        return set()
    rows = (
        db.execute(
            select(Pipeline.id).where(Pipeline.workspace_id.in_(ctx.workspace_ids))
        )
        .scalars()
        .all()
    )
    return {str(r) for r in rows}


def visible_destination_ids(db: Session, ctx: AuthContext) -> set[str] | None:
    if ctx.is_system_admin:
        return None
    if not ctx.workspace_ids:
        return set()
    rows = (
        db.execute(
            select(Destination.id).where(
                Destination.workspace_id.in_(ctx.workspace_ids)
            )
        )
        .scalars()
        .all()
    )
    return {str(r) for r in rows}


# --------------------------------------------------------------------------
# require_* fetchers: 404 when missing OR out of scope (no existence leak)
# --------------------------------------------------------------------------

def require_pipeline(db: Session, pipeline_id: str) -> Pipeline:
    ctx = tenant_ctx()
    pipe = db.get(Pipeline, pipeline_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy pipeline")
    if not ctx.is_system_admin and not _workspace_allows(ctx, pipe.workspace_id):
        # Legacy rows without workspace_id fall back to: admin-only.
        raise HTTPException(status_code=404, detail="Không tìm thấy pipeline")
    return pipe


def require_destination(
    db: Session, destination_id: str, youtube_only: bool = False
) -> Destination:
    ctx = tenant_ctx()
    dest = db.get(Destination, destination_id)
    if dest is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy channel")
    if youtube_only and (dest.platform or "").lower() != "youtube":
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")
    if ctx.is_system_admin:
        return dest
    ws = dest.workspace_id or _pipeline_workspace_id(db, dest.pipeline_id)
    if not _workspace_allows(ctx, ws):
        raise HTTPException(status_code=404, detail="Không tìm thấy channel")
    return dest


def require_source(db: Session, source_id: str) -> DouyinSource:
    ctx = tenant_ctx()
    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if ctx.is_system_admin:
        return source
    ws = source.workspace_id or _pipeline_workspace_id(db, source.pipeline_id)
    if not _workspace_allows(ctx, ws):
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    return source


def require_pipeline_source(db: Session, source_id: str) -> PipelineSource:
    ctx = tenant_ctx()
    source = db.get(PipelineSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if ctx.is_system_admin:
        return source
    ws = source.workspace_id or _pipeline_workspace_id(db, source.pipeline_id)
    if not _workspace_allows(ctx, ws):
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    return source


def _row_workspace_via_parents(db: Session, row) -> str | None:
    """Best-effort workspace for rows that may predate the backfill."""
    ws = getattr(row, "workspace_id", None)
    if ws:
        return str(ws)
    pipeline_id = getattr(row, "pipeline_id", None)
    if pipeline_id:
        return _pipeline_workspace_id(db, pipeline_id)
    destination_id = getattr(row, "destination_id", None)
    if destination_id:
        return _destination_workspace_id(db, destination_id)
    return None


def require_publication(db: Session, publication_id: str) -> Publication:
    ctx = tenant_ctx()
    pub = db.get(Publication, publication_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")
    if not ctx.is_system_admin and not _workspace_allows(
        ctx, _row_workspace_via_parents(db, pub)
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")
    return pub


def require_job(db: Session, job_id: str) -> VideoJob:
    ctx = tenant_ctx()
    job = db.get(VideoJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    if not ctx.is_system_admin and not _workspace_allows(
        ctx, _row_workspace_via_parents(db, job)
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    return job


def require_video(db: Session, pipeline_id: str, video_id: str) -> DouyinVideo:
    """Inventory video addressed as (pipeline, video). Both must be visible."""
    ctx = tenant_ctx()
    pipe = db.get(Pipeline, pipeline_id)
    if pipe is None or (
        not ctx.is_system_admin and not _workspace_allows(ctx, pipe.workspace_id)
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy pipeline")
    video = (
        db.execute(
            select(DouyinVideo)
            .where(DouyinVideo.pipeline_id == pipeline_id)
            .where(DouyinVideo.video_id == video_id)
            .limit(1)
        ).scalar_one_or_none()
    )
    if video is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    return video


def require_comment(
    db: Session, destination_id: str, comment_id: str
) -> YouTubeComment:
    from app.models import YouTubeComment as _YC

    dest = require_destination(db, destination_id, youtube_only=True)
    comment = db.get(_YC, comment_id)
    if comment is None:
        comment = (
            db.execute(
                select(_YC)
                .where(_YC.destination_id == dest.id)
                .where(_YC.youtube_comment_id == comment_id)
                .limit(1)
            ).scalar_one_or_none()
        )
    if comment is None or comment.destination_id != dest.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy bình luận")
    return comment


# --------------------------------------------------------------------------
# Workspace assignment for newly created rows
# --------------------------------------------------------------------------

ADMIN_WORKSPACE_NAME = "Admin Workspace"


def default_workspace_id(db: Session, ctx: AuthContext | None = None) -> str:
    """Workspace that owns rows created without an explicit parent.

    - Regular user: their oldest membership workspace (must exist).
    - System admin / legacy token: the "Admin Workspace" (backfill target),
      else the oldest workspace, else a freshly created Admin Workspace.
    """
    active = ctx if ctx is not None else tenant_ctx()
    if not active.is_system_admin:
        if not active.workspace_ids:
            raise HTTPException(
                status_code=404, detail="Tài khoản chưa thuộc workspace nào"
            )
        row = (
            db.execute(
                select(WorkspaceMember.workspace_id)
                .where(WorkspaceMember.user_id == active.user_id)
                .order_by(WorkspaceMember.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail="Tài khoản chưa thuộc workspace nào"
            )
        return str(row)

    admin_ws = (
        db.execute(
            select(Workspace).where(Workspace.name == ADMIN_WORKSPACE_NAME).limit(1)
        ).scalar_one_or_none()
    )
    if admin_ws is not None:
        return str(admin_ws.id)
    oldest = (
        db.execute(select(Workspace).order_by(Workspace.created_at.asc()).limit(1))
        .scalars()
        .first()
    )
    if oldest is not None:
        return str(oldest.id)
    ws = Workspace(name=ADMIN_WORKSPACE_NAME, owner_user_id=active.user_id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return str(ws.id)


def user_public_info(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "is_system_admin": bool(user.is_system_admin),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
