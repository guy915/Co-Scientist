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
    if (
        now >= spend.cutoff
        or spend.amount < 0
        or spend.total <= 0
        or spent + spend.amount > spend.total
        or conn.execute("SELECT 1 FROM llm_spend_holds LIMIT 1").fetchone()
    ):
        raise ProviderAdmissionError(UNAVAILABLE)
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
) -> None:
    row = conn.execute("SELECT reserved_microeur FROM llm_spend WHERE id=?", (receipt,)).fetchone()
    if row is None:
        return
    if not 0 <= charged <= row[0]:
        raise ProviderAdmissionError(UNAVAILABLE)
    conn.execute(
        "UPDATE llm_spend SET charged_microeur=?,settled=1,prompt_tokens=?,output_tokens=?,"
        "cached_tokens=?,cache_write_tokens=? WHERE id=? AND settled=0",
        (charged, prompt, output, cached, written, receipt),
    )
