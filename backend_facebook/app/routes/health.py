from fastapi import APIRouter
from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str


router = APIRouter()


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, service="backend-facebook", version="1.0.0")

