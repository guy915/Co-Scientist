from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from co_scientist.api.auth import client_id
from co_scientist.api.runs.models import CreateRunRequest
from co_scientist.core import byok_scope
from co_scientist.core.async_bridge import off_loop
from co_scientist.core.config import settings
from co_scientist.platform.llm.process_mode import offline_mode

FREE_TIER = "express"

_NUMERIC_KNOBS = (
    "initial_hypotheses_count",
    "max_iterations",
    "evolution_max_count",
    "k_factor",
)

router = APIRouter(tags=["free-usage"])


class FreeUsageExhaustedError(Exception):
    """The daily free-run allowance is exhausted."""


def applies(byok: byok_scope.ByokCredential | None, llm_backend: str) -> bool:
    return byok is None and llm_backend == "real"


def check_request(req: CreateRunRequest, tier: str) -> None:
    """Numeric overrides cannot enlarge a free express run beyond its funded
    envelope.
    """
    if tier != FREE_TIER or any(getattr(req, knob) is not None for knob in _NUMERIC_KNOBS):
        raise HTTPException(
            status_code=403,
            detail=(
                "Free usage is limited to Express runs. Add your own API "
                "key in Settings > Model to use other run types."
            ),
        )


def daily_limit() -> int | None:
    limit = settings.free_runs_per_day
    return limit if limit > 0 else None


def _day_bounds(now: float) -> tuple[float, float]:
    day = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc).date()
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    return start.timestamp(), (start + dt.timedelta(days=1)).timestamp()


def used_today(conn: sqlite3.Connection, owner: str, now: float) -> int:
    start, _ = _day_bounds(now)
    row = conn.execute(
        "SELECT COUNT(*) FROM free_run_usage WHERE client_id=? AND created_at>=?",
        (owner, start),
    ).fetchone()
    return int(row[0])


def claim_free_run(conn: sqlite3.Connection, owner: str, run_id: str) -> None:
    """Count and admission share the create transaction; deleting a run
    never refunds its independent usage-ledger slot.
    """
    from co_scientist.platform.db import current_time

    now = current_time()
    limit = daily_limit()
    if limit is not None and used_today(conn, owner, now) >= limit:
        raise FreeUsageExhaustedError
    conn.execute(
        "INSERT INTO free_run_usage (run_id, client_id, created_at) VALUES (?,?,?)",
        (run_id, owner, now),
    )


def exhausted_error() -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=(
            f"You have used your {daily_limit()} free runs for today. "
            "Add your own API key in Settings > Model, or try again "
            "tomorrow (UTC)."
        ),
    )


def usage_payload(owner: str) -> dict[str, Any]:
    """Offline deterministic execution spends no deployment free-model
    allowance.
    """
    from co_scientist.platform.db import connect, current_time

    now = current_time()
    with connect() as conn:
        used = used_today(conn, owner, now)
    limit = daily_limit()
    return {
        "enforced": not offline_mode(),
        "tier": FREE_TIER,
        "limit": limit,
        "used": used,
        "remaining": None if limit is None else max(limit - used, 0),
        "resets_at": _day_bounds(now)[1],
    }


@router.get("/api/free-usage")
@off_loop
def get_free_usage(request: Request) -> dict[str, Any]:
    """Return how many free runs the caller has left today."""
    return usage_payload(client_id(request))
