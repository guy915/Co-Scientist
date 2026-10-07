from co_scientist.platform.db import current_time, transaction


class DecisionQuotaExceededError(RuntimeError):
    pass


_TABLE = """
CREATE TABLE IF NOT EXISTS decision_usage (
    day INTEGER PRIMARY KEY,
    calls INTEGER NOT NULL,
    tokens INTEGER NOT NULL,
    blocked_until REAL NOT NULL DEFAULT 0
)
"""


def reserve_decision(tokens: int, call_limit: int, token_limit: int, db_path: str | None) -> None:
    now = current_time()
    day = int(now // 86400)
    with transaction(db_path) as conn:
        conn.execute(_TABLE)
        row = conn.execute("SELECT * FROM decision_usage WHERE day=?", (day,)).fetchone()
        calls, used = (row["calls"], row["tokens"]) if row else (0, 0)
        blocked = conn.execute(
            "SELECT COALESCE(MAX(blocked_until),0) FROM decision_usage"
        ).fetchone()[0]
        if calls + 1 > call_limit or used + tokens > token_limit or now < blocked:
            raise DecisionQuotaExceededError("decision allowance unavailable")
        conn.execute("DELETE FROM decision_usage WHERE day<?", (day - 7,))
        conn.execute(
            "INSERT INTO decision_usage(day,calls,tokens) VALUES (?,1,?) "
            "ON CONFLICT(day) DO UPDATE SET calls=calls+1,tokens=tokens+excluded.tokens",
            (day, tokens),
        )


def block_decisions(seconds: float, db_path: str | None) -> None:
    now = current_time()
    with transaction(db_path) as conn:
        conn.execute(_TABLE)
        conn.execute(
            "INSERT INTO decision_usage(day,calls,tokens,blocked_until) VALUES (?,0,0,?) "
            "ON CONFLICT(day) DO UPDATE SET "
            "blocked_until=MAX(blocked_until,excluded.blocked_until)",
            (int(now // 86400), now + seconds),
        )
