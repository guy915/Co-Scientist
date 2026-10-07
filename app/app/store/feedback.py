"""Bounded owner-scoped feedback with durable admission budgets."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from co_scientist.platform import db

Category = Literal["Bug", "Security", "Results quality", "Feature request", "Other"]
MAX_ROWS = 200
MAX_BYTES = 10 * 1024 * 1024
RETENTION_SECONDS = 30 * 24 * 60 * 60
OWNER_PER_MINUTE = 5
HOST_PER_MINUTE = 20
GLOBAL_PER_MINUTE = 100


class RateExceededError(ValueError):
    pass


@dataclass(frozen=True)
class Submission:
    category: Category
    message: str
    diagnostics: str
    url: str
    run_id: str | None = None


def submit(owner: str, host_key: str, submission: Submission) -> str:
    now = db.current_time()
    identity = str(uuid.uuid4())
    size = (
        sum(
            len(text.encode("utf-8"))
            for text in (
                identity,
                owner,
                submission.category,
                submission.message,
                submission.diagnostics,
                submission.url,
                submission.run_id or "",
            )
        )
        + 128
    )
    if size > MAX_BYTES:
        raise ValueError("feedback exceeds the storage limit")
    with db.transaction() as conn:
        conn.execute("DELETE FROM feedback_admissions WHERE created_at<=?", (now - 60,))
        total, owned, hosted = conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(client_id=?),0),"
            "COALESCE(SUM(host_key=?),0) FROM feedback_admissions",
            (owner, host_key),
        ).fetchone()
        if total >= GLOBAL_PER_MINUTE or owned >= OWNER_PER_MINUTE or hosted >= HOST_PER_MINUTE:
            raise RateExceededError("Please wait a minute before sending more feedback.")
        conn.execute(
            "INSERT INTO feedback_admissions VALUES (?,?,?)",
            (owner, host_key, now),
        )
        conn.execute(
            "INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identity,
                owner,
                submission.category,
                submission.message,
                submission.diagnostics,
                submission.url,
                submission.run_id,
                now,
                size,
            ),
        )
        conn.execute(
            "DELETE FROM feedback WHERE created_at<?",
            (now - RETENTION_SECONDS,),
        )
        # Keep newest records within both budgets, including multibyte text.
        conn.execute(
            "DELETE FROM feedback WHERE id IN (SELECT id FROM ("
            "SELECT id,ROW_NUMBER() OVER "
            "(ORDER BY created_at DESC,rowid DESC) AS n,"
            "SUM(byte_size) OVER "
            "(ORDER BY created_at DESC,rowid DESC) AS bytes "
            "FROM feedback) WHERE n>? OR bytes>?)",
            (MAX_ROWS, MAX_BYTES),
        )
    return identity
