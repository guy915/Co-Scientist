from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db import connect, current_time, transaction

UNAVAILABLE = "No model is available right now"


@dataclass(frozen=True)
class SpendReservation:
    model: str
    role: str
    amount: int
    total: int
    cutoff: float
    input_bound: int
    output_bound: int
    rates: str
    run_id: str | None = None


@dataclass(frozen=True)
class SpendRecord:
    input_bound: int
    output_bound: int
    rates: str
    settled: bool


def spend_record(receipt: str, path: str) -> SpendRecord | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM llm_spend WHERE id=?", (receipt,)).fetchone()
    return (
        SpendRecord(row["input_bound"], row["output_bound"], row["rates"], bool(row["settled"]))
        if row
        else None
    )


def hold_spending(receipt: str, path: str) -> None:
    with transaction(path, durable=True) as conn:
        conn.execute("INSERT OR IGNORE INTO llm_spend_holds VALUES (?)", (receipt,))


def reserve_spend(conn: sqlite3.Connection, receipt: str, spend: SpendReservation) -> None:
    now = current_time()
    spent = conn.execute("SELECT COALESCE(SUM(charged_microeur),0) FROM llm_spend").fetchone()[0]
    forecasts = conn.execute(
        "SELECT COALESCE(SUM(forecast_microeur),0) FROM llm_routes"
    ).fetchone()[0]
    converted = 0
    if spend.run_id is not None:
        route = conn.execute("SELECT * FROM llm_routes WHERE run_id=?", (spend.run_id,)).fetchone()
        if route is None or not route["azure_allowed"]:
            raise ProviderAdmissionError(UNAVAILABLE)
        converted = min(spend.amount, route["forecast_microeur"])
    if (
        now >= spend.cutoff
        or spend.amount < 0
        or spend.total <= 0
        or spent + forecasts + spend.amount - converted > spend.total
        or conn.execute("SELECT 1 FROM llm_spend_holds LIMIT 1").fetchone()
    ):
        raise ProviderAdmissionError(UNAVAILABLE)
    if converted:
        conn.execute(
            "UPDATE llm_routes SET forecast_microeur=forecast_microeur-? WHERE run_id=?",
            (converted, spend.run_id),
        )
        conn.execute(
            "INSERT INTO llm_forecast_allocations VALUES (?,?,?)",
            (receipt, spend.run_id, converted),
        )
    conn.execute(
        "INSERT INTO llm_spend "
        "(id,created_at,model,role,reserved_microeur,charged_microeur,"
        "input_bound,output_bound,rates) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            receipt,
            now,
            spend.model,
            spend.role,
            spend.amount,
            spend.amount,
            spend.input_bound,
            spend.output_bound,
            spend.rates,
        ),
    )


def settle_spend(
    conn: sqlite3.Connection,
    receipt: str,
    charged: int,
    prompt: int,
    output: int,
    cached: int | None,
    written: int | None,
    refused: bool | None = None,
) -> None:
    row = conn.execute("SELECT reserved_microeur FROM llm_spend WHERE id=?", (receipt,)).fetchone()
    if row is None:
        return
    if not 0 <= charged <= row[0]:
        raise ProviderAdmissionError(UNAVAILABLE)
    changed = conn.execute(
        "UPDATE llm_spend SET charged_microeur=?,settled=1,prompt_tokens=?,output_tokens=?,"
        "cached_tokens=?,cache_write_tokens=?,refused=? WHERE id=? AND settled=0",
        (charged, prompt, output, cached, written, refused, receipt),
    ).rowcount
    if changed:
        allocation = conn.execute(
            "SELECT run_id,converted_microeur FROM llm_forecast_allocations WHERE receipt_id=?",
            (receipt,),
        ).fetchone()
        if allocation:
            refund = min(allocation["converted_microeur"], row[0] - charged)
            conn.execute(
                "UPDATE llm_routes SET forecast_microeur=forecast_microeur+? WHERE run_id=?",
                (refund, allocation["run_id"]),
            )
            conn.execute("DELETE FROM llm_forecast_allocations WHERE receipt_id=?", (receipt,))
