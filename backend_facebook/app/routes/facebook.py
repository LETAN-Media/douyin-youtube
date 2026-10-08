import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import destinations, pipelines, publications, reels, sources
from ..services.facebook_url import (
    SOURCE_TYPE,
    InvalidFacebookUrlError,
    PageIdRequiredError,
    parse_facebook_reels_url,
)

router = APIRouter(prefix="/api/facebook", tags=["facebook"])


# ---------- Schemas ----------


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    auto_publish: bool = True


class PipelineUpdate(BaseModel):
    enabled: bool | None = None
    auto_publish: bool | None = None
    name: str | None = Field(default=None, max_length=200)


class SourceCreate(BaseModel):
    url: str = Field(min_length=1)
    page_name: str | None = None
    enabled: bool = True


# ---------- Helpers ----------


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or f"pipeline-{uuid.uuid4().hex[:8]}"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _source_response(row: dict) -> dict:
    return {
        "id": row["id"],
        "pipeline_id": row["pipeline_id"],
        "page_id": row["page_id"],
        "page_name": row.get("page_name"),
        "reels_url": row.get("reels_url"),
        "source_url": row.get("source_url"),
        "source_type": SOURCE_TYPE,
        "enabled": row.get("enabled", True),
        "initial_scan_completed": row.get("initial_scan_completed", False),
        "crawl_complete": row.get("crawl_complete", False),
        "discovered_total": row.get("discovered_total", 0),
        "last_scan_at": row.get("last_scan_at"),
        "last_scan_status": row.get("last_scan_status"),
        "last_scan_error": row.get("last_scan_error"),
    }


# ---------- Pipelines ----------


@router.post("/pipelines", status_code=status.HTTP_201_CREATED)
async def create_pipeline(body: PipelineCreate, _: None = Depends(require_admin)) -> dict:
    slug = (body.slug or "").strip() or _slugify(body.name)
    existing = await pipelines.get_pipeline_by_slug(slug)
    if existing is not None:
        raise _err(409, "PIPELINE_ALREADY_EXISTS", "Pipeline slug already exists")
    pipeline_id = _new_id("pl")
    try:
        created = await pipelines.create_pipeline(
            pipeline_id=pipeline_id,
            name=body.name.strip(),
            slug=slug,
            enabled=body.enabled,
            auto_publish=body.auto_publish,
        )
    except Exception:
        raise _err(500, "PIPELINE_CREATE_FAILED", "Failed to create pipeline")
    return created


@router.get("/pipelines")
async def list_all_pipelines() -> list[dict]:
    return await pipelines.list_pipelines()


@router.get("/pipelines/{pipeline_id}")
async def get_one_pipeline(pipeline_id: str) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return pipeline


@router.patch("/pipelines/{pipeline_id}")
async def update_one_pipeline(pipeline_id: str, body: PipelineUpdate, _: None = Depends(require_admin)) -> dict:
    if body.enabled is None and body.auto_publish is None and body.name is None:
        raise _err(400, "NOTHING_TO_UPDATE", "Provide at least one of: enabled, auto_publish, name")
    if body.name is not None and not body.name.strip():
        raise _err(400, "INVALID_NAME", "Pipeline name must not be empty")
    try:
        updated = await pipelines.update_pipeline(
            pipeline_id,
            enabled=body.enabled,
            auto_publish=body.auto_publish,
            name=body.name,
        )
    except ValueError as exc:
        raise _err(400, "INVALID_NAME", str(exc) or "Invalid pipeline name")
    except Exception:
        raise _err(500, "PIPELINE_UPDATE_FAILED", "Failed to update pipeline")
    if updated is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return updated


# ---------- Sources ----------


@router.post("/pipelines/{pipeline_id}/sources", status_code=status.HTTP_201_CREATED)
async def create_source(
    pipeline_id: str, body: SourceCreate, _: None = Depends(require_admin)
) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")

    raw_url = (body.url or "").strip()
    if not raw_url:
        raise _err(400, "INVALID_FACEBOOK_URL", "URL is empty")

    try:
        parsed = parse_facebook_reels_url(raw_url)
        source_url = raw_url
    except PageIdRequiredError:
        # Username/profile/share URL: resolve to the authoritative Page ID.
        from ..services.facebook_url import (
            PageResolutionError,
            resolve_page_id_from_url,
        )

        try:
            resolved = await resolve_page_id_from_url(raw_url)
        except PageResolutionError as exc:
            raise _err(400, "PAGE_UNRESOLVABLE", str(exc))
        parsed = resolved
        source_url = raw_url
    except InvalidFacebookUrlError as exc:
        raise _err(400, "INVALID_FACEBOOK_URL", str(exc) or "Invalid Facebook URL")

    try:
        created = await sources.create_source(
            source_id=_new_id("src"),
            pipeline_id=pipeline_id,
            page_id=parsed["page_id"],
            page_name=body.page_name,
            reels_url=parsed["normalized_url"],
            source_url=source_url,
            enabled=body.enabled,
        )
    except sources.DuplicateSourceError as exc:
        raise _err(409, "SOURCE_ALREADY_EXISTS", "Facebook source already exists in this pipeline") from exc
    except Exception:
        raise _err(500, "SOURCE_CREATE_FAILED", "Failed to create source")
    return _source_response(created)


@router.get("/pipelines/{pipeline_id}/sources")
async def list_pipeline_sources(pipeline_id: str) -> list[dict]:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    rows = await sources.list_sources(pipeline_id)
    return [_source_response(r) for r in rows]


@router.get("/sources/{source_id}")
async def get_one_source(source_id: str) -> dict:
    source = await sources.get_source(source_id)
    if source is None:
        raise _err(404, "SOURCE_NOT_FOUND", "Source not found")
    return _source_response(source)


class SourceUpdate(BaseModel):
    enabled: bool


@router.patch("/sources/{source_id}")
async def update_one_source(
    source_id: str, body: SourceUpdate, _: None = Depends(require_admin)
) -> dict:
    updated = await sources.update_source_enabled(source_id, body.enabled)
    if updated is None:
        raise _err(404, "SOURCE_NOT_FOUND", "Source not found")
    return _source_response(updated)


@router.delete("/sources/{source_id}")
async def delete_one_source(
    source_id: str, _: None = Depends(require_admin)
) -> dict:
    """Delete a source with no inventory. Sources that already produced
    videos are protected (disable them instead) so AI stats, scheduler and
    inventory joins keep working."""
    outcome = await sources.delete_source(source_id)
    if outcome == "not_found":
        raise _err(404, "SOURCE_NOT_FOUND", "Source not found")
    if outcome == "has_reels":
        count = await sources.count_reels_for_source(source_id)
        raise _err(
            409, "SOURCE_HAS_VIDEOS",
            f"Nguồn còn {count} video trong Inventory. Hãy tắt nguồn thay vì xoá.",
        )
    return {"ok": True, "id": source_id, "deleted": True}


# ---------- Aggregates ----------


@router.get("/pipelines/{pipeline_id}/summary")
async def get_pipeline_summary(pipeline_id: str) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    fb_sources = await sources.list_sources(pipeline_id)
    stats = await reels.inventory_stats(pipeline_id)
    yt_destinations = await destinations.list_destinations(pipeline_id)
    return {
        "pipeline": {
            "id": pipeline["id"],
            "name": pipeline["name"],
            "slug": pipeline["slug"],
            "enabled": bool(pipeline.get("enabled", True)),
            "auto_publish": bool(pipeline.get("auto_publish", True)),
        },
        "sources": len(fb_sources),
        "inventory": stats["total"],
        "destinations": len(yt_destinations),
        "published": stats["published"],
        "failed": stats["failed"],
        "queued": stats["queued"],
        "processing": stats["processing"],
    }


@router.get("/pipelines/{pipeline_id}/publications")
async def list_pipeline_publications(
    pipeline_id: str, limit: int = 100, offset: int = 0
) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    items, total = await publications.list_publications_for_pipeline(
        pipeline_id, limit=limit, offset=offset
    )
    return {"items": items, "total": total}
