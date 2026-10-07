from __future__ import annotations

from fastapi import APIRouter

from co_scientist.core.async_bridge import off_loop
from co_scientist.domains.access.byok_models import model_catalog

router = APIRouter(tags=["byok-models"])


@router.get("/api/byok-models")
@off_loop
def get_byok_models() -> dict[str, dict[str, list[str]]]:
    """Return the models each BYOK provider offers, default first."""
    return {"providers": model_catalog()}
