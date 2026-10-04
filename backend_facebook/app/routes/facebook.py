import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import pipelines, sources
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
        "source_type": SOURCE_TYPE,
        "enabled": row.get("enabled", True),
        "initial_scan_completed": row.get("initial_scan_completed", False),
        "crawl_complete": row.get("crawl_complete", False),
        "discovered_total": row.get("discovered_total", 0),
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
    except PageIdRequiredError as exc:
        raise _err(400, "PAGE_ID_REQUIRED", str(exc))
    except InvalidFacebookUrlError as exc:
        raise _err(400, "INVALID_FACEBOOK_URL", str(exc) or "Invalid Facebook URL")

    try:
        created = await sources.create_source(
            source_id=_new_id("src"),
            pipeline_id=pipeline_id,
            page_id=parsed["page_id"],
            page_name=body.page_name,
            reels_url=parsed["normalized_url"],
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
