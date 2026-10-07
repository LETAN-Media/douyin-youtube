"""Upstream vendor health (failover pool state). No secrets exposed."""

from fastapi import APIRouter, Depends

from ..auth import require_admin
from ..config import settings
from ..services.providers import pool as pool_mod

router = APIRouter(prefix="/api/drama", tags=["drama-providers"])


@router.get("/providers/health")
async def providers_health(_: None = Depends(require_admin)) -> dict:
    """Per-upstream and per-provider status snapshot without secrets."""
    upstreams = pool_mod.pool_health()

    endpoints = pool_mod.load_pool_from_settings()
    if settings.rapidix_configured() and not any(ep.name == "rapidix" for ep in endpoints):
        endpoints.append(
            pool_mod.ProviderEndpoint(
                name="rapidix",
                host=settings.RAPIDAPI_HOST or "",
                base_url=settings.RAPIDAPI_BASE_URL or f"https://{settings.RAPIDAPI_HOST}",
                api_key=settings.rapidix_key(),
                priority=99,
                enabled=True,
                providers=("rapidix",),
            )
        )

    target_providers = (
        "shortmax",
        "netshort",
        "rapidix",
        "starshort",
        "dramabox",
        "flickshort",
        "reelshort_sdp",
    )
    provider_reports = []
    for p in target_providers:
        eligible = [ep for ep in endpoints if ep.serves(p)]
        if eligible:
            ep = eligible[0]
            state = pool_mod._state_for(ep.name)
            provider_reports.append({
                "provider": p,
                "upstream": ep.name,
                "vendor_group": ep.vendor_group,
                "status": pool_mod.endpoint_status(ep.name),
                "last_http": state.last_http,
                "last_error_code": state.last_code,
            })
        else:
            provider_reports.append({
                "provider": p,
                "upstream": None,
                "vendor_group": None,
                "status": "not_configured",
                "last_http": None,
                "last_error_code": "NOT_CONFIGURED",
            })

    return {
        "upstreams": upstreams,
        "providers": provider_reports,
    }
