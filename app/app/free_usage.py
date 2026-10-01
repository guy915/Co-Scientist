"""Free usage: limits on runs that bring no API key.

A run without a bring-your-own-key credential runs on the deployment's
own free models, so it is limited in two ways:

- Tier: only the express tier, with no numeric knob overrides (a knob
  such as ``max_iterations`` would otherwise grow an "express" run past
  the express envelope).
- Count: ``settings.free_runs_per_day`` runs per client identity per UTC
  day. The identity is the caller's scope (``auth.client_id``): the
  browser's ``X-Client-ID``, or the researcher subject of a session.

Each free run takes one row in ``free_run_usage``. The row is written in
the same transaction that creates the run (``claim_free_run``), and the
count is checked again inside it, so two concurrent requests cannot both
take the last slot. The ledger has no foreign key to ``runs``: deleting
a run does not return its slot.

Offline runs (no provider key on the deployment, or forced offline) and
campaign runs are not free usage: neither spends the free models.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app import credentials, engine_adapter
from app.auth import client_id
from app.config import settings
from app.execution_policy import CAMPAIGN
from app.runs.models import CreateRunRequest

FREE_TIER = "express"

_NUMERIC_KNOBS = (
    "initial_hypotheses_count",
    "max_iterations",
    "evolution_max_count",
    "k_factor",
)

router = APIRouter(tags=["free-usage"])


class FreeUsageExhaustedError(Exception):
    """The caller has no free runs left today. Maps to 429."""


def applies(
    byok: credentials.ByokCredential | None,
    execution_policy: str,
    llm_backend: str,
) -> bool:
    """Return whether a new run counts as free usage.

    Args:
        byok: The run's validated credential, when one was sent.
        execution_policy: The run's trusted execution policy.
        llm_backend: ``"real"`` or ``"offline"`` for the new run.

    Returns:
        True for a real-backed, non-campaign run with no key.
    """
    return (
        byok is None and execution_policy != CAMPAIGN and llm_backend == "real"
    )


def check_request(req: CreateRunRequest, tier: str) -> None:
    """Refuse a free run outside the express envelope.

    Args:
        req: The create-run request.
        tier: The run's normalized tier.

    Raises:
        HTTPException: 403 for a non-express tier or a numeric override.
    """
    if tier != FREE_TIER or any(
        getattr(req, knob) is not None for knob in _NUMERIC_KNOBS
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Free usage is limited to Express runs. Add your own API "
                "key in Settings > Model to use other run types."
            ),
        )


def daily_limit() -> int | None:
    """Return the free runs allowed per day, or None when uncapped."""
    limit = settings.free_runs_per_day
    return limit if limit > 0 else None


def _day_bounds(now: float) -> tuple[float, float]:
    """Return the (start, end) epoch seconds of ``now``'s UTC day."""
    day = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc).date()
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    return start.timestamp(), (start + dt.timedelta(days=1)).timestamp()


def used_today(conn: sqlite3.Connection, owner: str, now: float) -> int:
    """Count the free runs ``owner`` started in ``now``'s UTC day."""
    start, _ = _day_bounds(now)
    row = conn.execute(
        "SELECT COUNT(*) FROM free_run_usage "
        "WHERE client_id=? AND created_at>=?",
        (owner, start),
    ).fetchone()
    return int(row[0])


def claim_free_run(conn: sqlite3.Connection, owner: str, run_id: str) -> None:
    """Take one free-run slot for ``run_id`` inside the create transaction.

    Args:
        conn: The open run-creation transaction.
        owner: The caller's scope.
        run_id: The run being created.

    Raises:
        FreeUsageExhaustedError: The daily limit is already reached; the
            caller's transaction then rolls the new run back.
    """
    from app.store.db import _now

    now = _now()
    limit = daily_limit()
    if limit is not None and used_today(conn, owner, now) >= limit:
        raise FreeUsageExhaustedError
    conn.execute(
        "INSERT INTO free_run_usage (run_id, client_id, created_at) "
        "VALUES (?,?,?)",
        (run_id, owner, now),
    )


def exhausted_error() -> HTTPException:
    """Return the 429 a caller sees once today's free runs are spent."""
    return HTTPException(
        status_code=429,
        detail=(
            f"You have used your {daily_limit()} free runs for today. "
            "Add your own API key in Settings > Model, or try again "
            "tomorrow (UTC)."
        ),
    )


def usage_payload(owner: str) -> dict[str, Any]:
    """Return the caller's free-usage state for the Settings UI.

    ``enforced`` is False on an offline deployment, where a keyless run
    uses the deterministic offline backend rather than the free models.
    """
    from app.store.db import _now, connect

    now = _now()
    with connect() as conn:
        used = used_today(conn, owner, now)
    limit = daily_limit()
    return {
        "enforced": not engine_adapter.offline_mode(),
        "tier": FREE_TIER,
        "limit": limit,
        "used": used,
        "remaining": None if limit is None else max(limit - used, 0),
        "resets_at": _day_bounds(now)[1],
    }


@router.get("/api/free-usage")
async def get_free_usage(request: Request) -> dict[str, Any]:
    """Return how many free runs the caller has left today."""
    return usage_payload(client_id(request))
