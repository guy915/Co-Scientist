"""Short, caller-owned admission transactions; no network work or poll writes."""

import hashlib
import ipaddress
import sqlite3

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db import connect, current_time, transaction

UNKNOWN_HOST = "unknown"


def connecting_host(host: str | None) -> str:
    """Use the connecting peer, never client-supplied forwarding headers.

    IPv6 addresses share a /64 allowance. Persist only a digest, not an IP.
    Missing peers share a bounded bucket rather than bypassing admission.
    """
    if not host:
        return UNKNOWN_HOST
    try:
        address = ipaddress.ip_address(host)
        host = (
            str(ipaddress.ip_network(f"{address}/64", strict=False))
            if address.version == 6
            else str(address)
        )
    except ValueError:
        pass
    return hashlib.sha256(host.encode()).hexdigest()


def claim_session(conn: sqlite3.Connection, owner: str, host: str, day: int) -> None:
    from co_scientist.core.config import settings

    if conn.execute(
        "SELECT 1 FROM anonymous_admissions WHERE day=? AND host=? AND client_id=?",
        (day, host, owner),
    ).fetchone():
        return
    global_count, host_count = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(host=?),0) FROM anonymous_admissions WHERE day=?",
        (host, day),
    ).fetchone()
    if (
        global_count >= settings.anonymous_sessions_per_day
        or host_count >= settings.anonymous_sessions_per_host_per_day
    ):
        raise ProviderAdmissionError("daily anonymous session admission exhausted")
    conn.execute("DELETE FROM anonymous_admissions WHERE day<?", (day,))
    conn.execute("INSERT INTO anonymous_admissions VALUES (?,?,?)", (day, host, owner))


def claim_run(conn: sqlite3.Connection, run_id: str, owner: str, host: str, *, free: bool) -> None:
    from co_scientist.core.config import settings

    day = int(current_time() // 86400)
    claim_session(conn, owner, host, day)
    total, same_host, free_total, free_host = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(host=?),0),COALESCE(SUM(free),0),"
        "COALESCE(SUM(free AND host=?),0) FROM run_admissions WHERE day=?",
        (host, host, day),
    ).fetchone()
    if (
        total >= settings.runs_per_day
        or same_host >= settings.runs_per_host_per_day
        or (
            free
            and (
                free_total >= settings.free_runs_globally_per_day
                or free_host >= settings.free_runs_per_host_per_day
            )
        )
    ):
        raise ProviderAdmissionError("daily run admission exhausted; try again tomorrow (UTC)")
    conn.execute(
        "INSERT INTO run_admissions VALUES (?,?,?,?,?)", (run_id, owner, host, day, int(free))
    )


def run_host(run_id: str, *, db_path: str | None = None) -> str:
    with connect(db_path) as conn:
        row = conn.execute("SELECT host FROM run_admissions WHERE run_id=?", (run_id,)).fetchone()
    return str(row[0]) if row else UNKNOWN_HOST


def capacity_available(conn: sqlite3.Connection, run_id: str, limit: int) -> bool:
    from co_scientist.core.config import settings

    # The status transition and all three counts occur under the same writer.
    host = conn.execute("SELECT host FROM run_admissions WHERE run_id=?", (run_id,)).fetchone()
    host = str(host[0]) if host else UNKNOWN_HOST
    total, same_host = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(COALESCE(a.host,?)=?),0) FROM runs r "
        "LEFT JOIN run_admissions a ON a.run_id=r.id "
        "WHERE r.status IN ('queued','running','synthesizing') AND r.id!=?",
        (UNKNOWN_HOST, host, run_id),
    ).fetchone()
    return bool(total < limit and same_host < settings.concurrent_runs_per_host)


def _reserve_app(conn: sqlite3.Connection, owner: str, day: int, tokens: int) -> None:
    from co_scientist.core.config import settings

    row = conn.execute(
        "SELECT calls,tokens FROM app_llm_usage WHERE day=? AND client_id=?", (day, owner)
    ).fetchone()
    calls, used = (row["calls"], row["tokens"]) if row else (0, 0)
    if (
        calls + 1 > settings.app_llm_client_calls_per_day
        or used + tokens > settings.app_llm_client_tokens_per_day
    ):
        raise ProviderAdmissionError("daily completion budget exceeded")
    conn.execute("DELETE FROM app_llm_usage WHERE day<?", (day,))
    conn.execute(
        "INSERT INTO app_llm_usage VALUES (?,?,1,?) ON CONFLICT(day,client_id) "
        "DO UPDATE SET calls=calls+1,tokens=tokens+excluded.tokens",
        (day, owner, tokens),
    )


def reserve_provider(owner: str, host: str, tokens: int, *, app: bool, db_path: str | None) -> None:
    from co_scientist.core.config import settings

    # A future EUR reservation belongs before this commit, alongside these
    # ceilings. The provider dispatch must remain outside the transaction.
    day = int(current_time() // 86400)
    ceilings = (
        (
            "global",
            "",
            settings.app_llm_global_calls_per_day,
            settings.app_llm_global_tokens_per_day,
        ),
        (
            "client",
            owner,
            settings.provider_client_calls_per_day,
            settings.provider_client_tokens_per_day,
        ),
        ("host", host, settings.provider_host_calls_per_day, settings.provider_host_tokens_per_day),
    )
    with transaction(db_path) as conn:
        claim_session(conn, owner, host, day)
        for scope, subject, call_limit, token_limit in ceilings:
            row = conn.execute(
                "SELECT calls,tokens FROM provider_admissions "
                "WHERE day=? AND scope=? AND subject=?",
                (day, scope, subject),
            ).fetchone()
            calls, used = (row["calls"], row["tokens"]) if row else (0, 0)
            if calls + 1 > call_limit or used + tokens > token_limit:
                raise ProviderAdmissionError("daily provider admission exhausted")
        if app:
            _reserve_app(conn, owner, day, tokens)
        conn.execute("DELETE FROM provider_admissions WHERE day<?", (day,))
        for scope, subject, _, _ in ceilings:
            conn.execute(
                "INSERT INTO provider_admissions VALUES (?,?,?,1,?) "
                "ON CONFLICT(day,scope,subject) DO UPDATE "
                "SET calls=calls+1,tokens=tokens+excluded.tokens",
                (day, scope, subject, tokens),
            )


def claim_continuation(
    conn: sqlite3.Connection, run_id: str, input_id: int, owner: str, *, free: bool
) -> None:
    from co_scientist.core.config import settings

    day = int(current_time() // 86400)
    row = conn.execute("SELECT host FROM run_admissions WHERE run_id=?", (run_id,)).fetchone()
    host = str(row[0]) if row else UNKNOWN_HOST
    prefix = f"continuation:{run_id}:"
    counts = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(client_id=?),0),COALESCE(SUM(host=?),0),"
        "COALESCE(SUM(substr(run_id,1,?)=?),0) FROM run_admissions "
        "WHERE day=? AND run_id LIKE 'continuation:%'",
        (owner, host, len(prefix), prefix, day),
    ).fetchone()
    limits = (
        settings.continuations_per_day,
        settings.continuations_per_client_per_day,
        settings.continuations_per_host_per_day,
        settings.continuations_per_run_per_day,
    )
    if any(count >= limit for count, limit in zip(counts, limits, strict=True)):
        raise ProviderAdmissionError("daily continuation admission exhausted")
    key = f"{prefix}{input_id}"
    if free:
        used = conn.execute(
            "SELECT COUNT(*) FROM free_run_usage WHERE client_id=? AND created_at>=?",
            (owner, day * 86400),
        ).fetchone()[0]
        if settings.free_runs_per_day > 0 and used >= settings.free_runs_per_day:
            raise ProviderAdmissionError("daily free run admission exhausted")
    # A continuation consumes the shared run envelope, even if its original run is old.
    claim_run(conn, key, owner, host, free=free)
    if free:
        conn.execute("INSERT INTO free_run_usage VALUES (?,?,?)", (key, owner, current_time()))
