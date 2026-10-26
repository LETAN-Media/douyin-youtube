from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    from ..db.client import get_client

    try:
        client = get_client()
        await client.execute("SELECT 1")
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "service": settings.service_name,
        "version": settings.version,
        "database": db_status,
    }


@router.get("/health/providers")
async def provider_health():
    from ..services.tiktok_provider_factory import get_scan_provider, available_providers

    provider = get_scan_provider()
    healthy = False
    try:
        healthy = await provider.health_check()
    except Exception:
        healthy = False
    return {
        "provider": provider.name,
        "healthy": healthy,
        "available": available_providers(),
    }
