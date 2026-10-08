from __future__ import annotations

import os
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from co_scientist.api.operator_access import is_operator
from co_scientist.core.async_bridge import off_loop
from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db import connect, current_time
from co_scientist.platform.db.spend_view import spend_snapshot
from co_scientist.platform.llm.admission.anthropic import cycle_bounds, require_credit_available
from co_scientist.platform.llm.admission.spend import paid_dispatch_config
from co_scientist.platform.llm.routing import available_slots

router = APIRouter(tags=["operations"])


def _configured_money(name: str, default: str = "") -> int | None:
    try:
        value = Decimal(os.getenv(name, default))
        if not value.is_finite() or value <= 0:
            return None
        amount = int((value * 1_000_000).to_integral_value(rounding=ROUND_FLOOR))
        return amount if 0 < amount < 2**63 else None
    except InvalidOperation:
        return None


@router.get("/api/spend")
@off_loop
def get_spend(request: Request, response: Response) -> dict[str, Any]:
    if not is_operator(request):
        raise HTTPException(404, "not found")
    response.headers["Cache-Control"] = "no-store"
    now = current_time()
    start: float | None
    end: float | None
    try:
        start, end = cycle_bounds(now, int(os.getenv("ANTHROPIC_BILLING_RESET_DAY", "7")))
    except (ValueError, ProviderAdmissionError):
        start, end = None, None
    with connect() as conn:
        conn.execute("BEGIN")
        snapshot = spend_snapshot(
            conn,
            now=now,
            total_microeur=_configured_money("LLM_TOTAL_BUDGET_EUR"),
            credit_microusd=_configured_money("ANTHROPIC_MONTHLY_CREDIT_USD", "100")
            if start is not None
            else None,
            cycle_start=start,
            cycle_end=end,
        )
        path = str(conn.execute("PRAGMA database_list").fetchone()[2])
        azure_held = conn.execute("SELECT 1 FROM llm_spend_holds LIMIT 1").fetchone() is not None
    try:
        slots = available_slots(path).slots
    except ProviderAdmissionError:
        slots = ()
    for key, available in (
        ("azure", paid_dispatch_config),
        ("anthropic", require_credit_available),
    ):
        try:
            available(path)
            snapshot[key]["available"] = bool(
                key in slots
                and (
                    key != "azure" or (not azure_held and (snapshot[key]["remaining_eur"] or 0) > 0)
                )
            )
        except ProviderAdmissionError:
            snapshot[key]["available"] = False
    return snapshot
