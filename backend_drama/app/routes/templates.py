"""Visual template presets (stored by URL/key, never binary)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import templates as templates_repo
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-templates"])


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    asset_url: str = Field(min_length=1, max_length=2000)
    canvas_width: int = 1280
    canvas_height: int = 720
    content_x: int = 0
    content_y: int = 0
    content_width: int = 1280
    content_height: int = 720


@router.get("/templates")
async def list_templates(_: None = Depends(require_admin)) -> dict:
    return {"items": templates_repo.list_templates()}


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreate, _: None = Depends(require_admin)
) -> dict:
    try:
        return templates_repo.create_template(
            name=body.name, asset_url=body.asset_url,
            canvas_width=body.canvas_width, canvas_height=body.canvas_height,
            content_x=body.content_x, content_y=body.content_y,
            content_width=body.content_width, content_height=body.content_height,
        )
    except ValueError as exc:
        raise _err(400, "INVALID_TEMPLATE", str(exc))


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str, _: None = Depends(require_admin)
) -> dict:
    if not templates_repo.delete_template(template_id):
        raise _err(404, "TEMPLATE_NOT_FOUND", "Template not found.")
    return {"ok": True, "id": template_id, "deleted": True}
