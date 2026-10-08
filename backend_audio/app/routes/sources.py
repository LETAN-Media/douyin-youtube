from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import require_admin
from app.db.repositories import pipelines as pipe_repo
from app.db.repositories import sources as repo
from app.services import facebook_urls, scanner

router = APIRouter(prefix="/api/audio", tags=["audio-sources"])


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


class SourcesAdd(BaseModel):
    urls: str


@router.get("/pipelines/{pipeline_id}/sources")
async def list_sources(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    items = repo.list_sources(pipeline_id)
    out = []
    for source in items:
        status = scanner.scan_status(source["id"])
        out.append({**source, "scan": status})
    return {"items": out}


@router.post("/pipelines/{pipeline_id}/sources", status_code=201)
async def add_sources(pipeline_id: str, body: SourcesAdd,
                      _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    lines = [line.strip() for line in (body.urls or "").splitlines()
             if line.strip()]
    if not lines:
        return _err(400, "NO_URLS", "Paste ít nhất một link Facebook.")
    added, existing, invalid = [], [], []
    for line in lines:
        try:
            parsed = facebook_urls.parse_facebook_source_url(line)
        except facebook_urls.FacebookUrlError as exc:
            invalid.append({"url": line, "error": str(exc)})
            continue
        source, created = repo.add_source(pipeline_id,
                                          parsed["canonical_url"],
                                          parsed["username"])
        (added if created else existing).append(source)
    for source in added:
        await scanner.scan_source(source["id"])
    return {"added": added, "existing": existing, "invalid": invalid}


@router.post("/sources/{source_id}/scan")
async def scan_now(source_id: str, full: bool = False,
                   mode: str | None = None,
                   _: None = Depends(require_admin)):
    """Manual scan only. mode=new (default, new videos only) or mode=full."""
    if mode is not None and mode not in ("new", "full"):
        return _err(400, "BAD_MODE", "mode must be 'new' or 'full'.")
    try:
        state = await scanner.scan_source(
            source_id, full=(mode == "full" or full))
    except ValueError:
        return _err(404, "SOURCE_NOT_FOUND", "Source không tồn tại.")
    return state


@router.post("/sources/{source_id}/pause")
async def pause(source_id: str, _: None = Depends(require_admin)):
    scanner.pause_scan(source_id)
    return {"paused": True}


@router.get("/sources/{source_id}/scan-runs")
async def list_scan_runs(source_id: str, _: None = Depends(require_admin)):
    from app.db.repositories import scan_runs

    return {"items": scan_runs.list_runs_for_source(source_id)}


@router.put("/sources/{source_id}")
async def set_enabled(source_id: str, enabled: bool,
                      _: None = Depends(require_admin)):
    repo.set_source_enabled(source_id, enabled)
    return {"id": source_id, "enabled": enabled}


@router.delete("/sources/{source_id}")
async def delete(source_id: str, _: None = Depends(require_admin)):
    repo.delete_source(source_id)
    return {"deleted": True}
