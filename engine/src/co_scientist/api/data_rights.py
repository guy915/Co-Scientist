from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from co_scientist.api.auth import require_client_scope
from co_scientist.core.async_bridge import off_loop
from co_scientist.domains.access.data_rights import delete_data, export_data

router = APIRouter(prefix="/api/data", tags=["data rights"])
_EXPORT_SLOTS = threading.BoundedSemaphore(2)


class BrowserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["light", "dark", "system"] | None = None
    provider: str | None = Field(default=None, max_length=32)
    worker_model: str | None = Field(default=None, max_length=1024)
    supervisor_model: str | None = Field(default=None, max_length=1024)
    custom_models: dict[
        Annotated[str, Field(max_length=256)], Annotated[str, Field(max_length=2048)]
    ] = Field(default_factory=dict, max_length=20)
    session_views: dict[
        Annotated[str, Field(max_length=128)], Annotated[str, Field(max_length=64)]
    ] = Field(default_factory=dict, max_length=1000)


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE"]


class PrivateExportResponse(FileResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await asyncio.wait_for(super().__call__(scope, receive, send), timeout=300)
        finally:
            try:
                Path(self.path).unlink(missing_ok=True)
            finally:
                _EXPORT_SLOTS.release()


@off_loop
def _create_export(request: Request, settings: BrowserSettings) -> Path:
    return export_data(require_client_scope(request), settings.model_dump())


@router.post("/export")
async def export_browser_data(request: Request, settings: BrowserSettings) -> FileResponse:
    if not _EXPORT_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="Two data exports are already active; try again shortly",
            headers={"Retry-After": "60"},
        )
    work = asyncio.create_task(_create_export(request, settings))
    try:
        data = await asyncio.shield(work)
    except asyncio.CancelledError:
        # Threads cannot be cancelled mid-write. Collect and unlink their
        # result even when the requesting client has disconnected.
        try:
            (await work).unlink(missing_ok=True)
        finally:
            _EXPORT_SLOTS.release()
        raise
    except BaseException:
        _EXPORT_SLOTS.release()
        raise
    return PrivateExportResponse(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="co-scientist-data.zip"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/delete")
@off_loop
def delete_browser_data(request: Request, body: DeleteRequest) -> dict[str, Any]:
    counts = delete_data(require_client_scope(request))
    return {"deleted": True, "counts": counts}
