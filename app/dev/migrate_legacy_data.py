"""One-off upgrade of legacy persisted data formats (migrations M01-M08).

Owner runbook (docs/OPERATIONS.md, "Legacy data migration"):
  1. python app/dev/backup_db.py PROD.db backup.db ; cp backup.db copy.db
  2. python app/dev/migrate_legacy_data.py --db copy.db --census
  3. python app/dev/migrate_legacy_data.py --db copy.db --apply, then check the runs render
  4. Stop the API, back up again, run --census, --apply, --census on prod, restart.

Self-contained on purpose: the alias maps and shape converters below are frozen copies, so
deleting the app readers they mirror cannot change what this script does. The DB must exist
and have no live writers; the script never creates one.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEMO = "__demo__"
TIERS = frozenset({"express", "standard", "extended", "ultra"})
TIER_ALIASES = {"advanced": "ultra", "default": "standard"}
VERDICTS = ("support", "revise", "oppose")
REPORT_KEYS = (
    "meta_review",
    "research_overview",
    "knowledge_base",
    "agent_insights",
    "idea_buckets",
    "claim_evidence",
    "degraded_sections",
    "skills_used",
    "reviews",
    "citation_summary",
    "leaderboard",
)
IDS = ("M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08")
# Resumable-state branches: dead once the quiescence gate is clean.
GATED = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09")
ALWAYS_STAY = (
    "C10",
    "K01",
    "K02",
    "K03",
    "K04",
    "K05",
    "K06",
    "K07",
    "K08",
    "K09",
    "K10",
)


def tier_alias(tier: Any) -> Any:
    return TIER_ALIASES.get(tier, tier) if isinstance(tier, str) else tier


def span(item: Any) -> Any:
    if isinstance(item, str):
        return {"evidence_id": "", "quote": item, "url": ""}
    return item


def direction(item: Any) -> Any:
    if isinstance(item, dict):
        return item
    return {"focus_area": "", "recommendation": item, "justification": ""}


def passage_text(title: Any, abstract: Any) -> str:
    return " ".join(str(part or "") for part in (title, abstract)).strip()


def scientist_verdict(verdict: Any, summary: Any) -> str | None:
    """The verdict to store, or None when the stored one is already valid."""
    if str(verdict or "").strip().lower() in VERDICTS:
        return None
    text = str(summary or "").lower()
    return next((v for v in VERDICTS if v in text), "revise")


def _upgrade_spans(edge: Any) -> bool:
    changed = False
    if not isinstance(edge, dict):
        return False
    for key in ("supporting", "contradicting"):
        items = edge.get(key)
        if isinstance(items, list) and any(isinstance(i, str) for i in items):
            edge[key] = [span(i) for i in items]
            changed = True
    return changed


def upgrade_payload(payload: Any) -> set[str]:
    """Upgrade a report payload in place; returns the migration ids that changed it."""
    done: set[str] = set()
    if not isinstance(payload, dict):
        return done
    if payload.get("run_mode") in TIER_ALIASES:
        payload["run_mode"] = tier_alias(payload["run_mode"])
        done.add("M01")
    edges = payload.get("claim_evidence")
    if isinstance(edges, list) and sum(_upgrade_spans(e) for e in edges):
        done.add("M03")
    insights = payload.get("agent_insights")
    if isinstance(insights, dict):
        items = insights.get("recommended_directions")
        if isinstance(items, list) and any(not isinstance(i, dict) for i in items):
            insights["recommended_directions"] = [direction(i) for i in items]
            done.add("M04")
    return done


def upgrade_span_column(raw: Any) -> str | None:
    """New JSON for a claim_evidence span column, or None when nothing to rewrite."""
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(items, list) and any(isinstance(i, str) for i in items):
        return json.dumps([span(i) for i in items])
    return None


def _jx(column: str, path: str) -> str:
    return f"CASE WHEN json_valid({column}) THEN json_extract({column},'{path}') END"


def _scope(column: str, include_demo: bool) -> str:
    if include_demo:
        return "1"
    return f"{column} IN (SELECT id FROM runs WHERE client_id <> '{DEMO}')"


def _payload_rows(conn: sqlite3.Connection, include_demo: bool) -> list[tuple[str, Any, str, str]]:
    rows = []
    for table, where in (("reports", "1"), ("run_events", "type='report'")):
        sql = (
            f"SELECT id, run_id, payload_json FROM {table} "
            f"WHERE {where} AND {_scope('run_id', include_demo)}"
        )
        rows += [(table, r[0], r[1], r[2]) for r in conn.execute(sql)]
    return rows


class _Tally:
    def __init__(self) -> None:
        self.old = 0
        self.bad = 0
        self.runs: set[str] = set()

    def hit(self, run_id: str, n: int = 1) -> None:
        self.old += n
        self.runs.add(run_id)

    def out(self) -> dict[str, int]:
        return {
            "old_format_rows": self.old,
            "malformed_rows": self.bad,
            "runs_affected": len(self.runs),
        }


def _census_groups(conn: sqlite3.Connection, include_demo: bool) -> dict[str, _Tally]:
    t = {i: _Tally() for i in IDS}
    for run_id, profile, raw in conn.execute(
        f"SELECT id, profile, config_json FROM runs WHERE {_scope('id', include_demo)}"
    ):
        if profile in TIER_ALIASES:
            t["M01"].hit(run_id)
        try:
            config = json.loads(raw)
        except ValueError:
            t["M01"].bad += 1
            continue
        setup = config.get("setup") if isinstance(config, dict) else None
        for holder in (config, setup):
            if isinstance(holder, dict) and holder.get("tier") in TIER_ALIASES:
                t["M01"].hit(run_id)
    for (run_id,) in conn.execute(
        f"SELECT id FROM runs WHERE llm_backend IS NULL AND {_scope('id', include_demo)}"
    ):
        t["M02"].hit(run_id)
    _census_json_columns(conn, include_demo, t)
    _census_rows(conn, include_demo, t)
    return t


def _census_json_columns(
    conn: sqlite3.Connection, include_demo: bool, t: dict[str, _Tally]
) -> None:
    for run_id, sup, con in conn.execute(
        "SELECT run_id, supporting_json, contradicting_json FROM claim_evidence "
        f"WHERE {_scope('run_id', include_demo)}"
    ):
        for raw in (sup, con):
            try:
                json.loads(raw)
            except (TypeError, ValueError):
                t["M03"].bad += 1
        if upgrade_span_column(sup) is not None or upgrade_span_column(con) is not None:
            t["M03"].hit(run_id)
    for _table, _id, run_id, raw in _payload_rows(conn, include_demo):
        try:
            payload = json.loads(raw)
        except ValueError:
            for key in ("M01", "M03", "M04"):
                t[key].bad += 1
            continue
        for key in upgrade_payload(payload):
            t[key].hit(run_id)


def _census_rows(conn: sqlite3.Connection, include_demo: bool, t: dict[str, _Tally]) -> None:
    for key, column in (("M05", "retracted"), ("M06", "passage_text")):
        for (run_id,) in conn.execute(
            f"SELECT run_id FROM evidence WHERE {column} IS NULL "
            f"AND {_scope('run_id', include_demo)}"
        ):
            t[key].hit(run_id)
    for run_id, verdict, summary in conn.execute(
        "SELECT run_id, verdict, summary FROM reviews WHERE reviewer_agent='scientist' "
        f"AND {_scope('run_id', include_demo)}"
    ):
        if scientist_verdict(verdict, summary) is not None:
            t["M07"].hit(run_id)
    demo = "" if include_demo else f" AND client_id <> '{DEMO}'"
    for (raw,) in conn.execute(f"SELECT fields_json FROM interviews WHERE 1{demo}"):
        try:
            fields = json.loads(raw)
        except ValueError:
            t["M08"].bad += 1
            continue
        if isinstance(fields, dict) and "lab_constraints" not in fields:
            t["M08"].old += 1


def schema_drift(conn: sqlite3.Connection) -> dict[str, list[str]]:
    from app.store.schema import SCHEMA

    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    missing: dict[str, list[str]] = {}
    for (table,) in ref.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        want = {r[1] for r in ref.execute(f"PRAGMA table_info({table})")}
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if want - have:
            missing[table] = sorted(want - have)
    ref.close()
    return missing


def gate_status(conn: sqlite3.Connection) -> dict[str, Any]:
    runs = conn.execute(
        "SELECT id, status FROM runs WHERE status IN ('queued','running','synthesizing','paused')"
    ).fetchall()
    failed = conn.execute(
        "SELECT id FROM runs WHERE status='failed' AND id IN (SELECT run_id FROM checkpoints)"
    ).fetchall()
    tasks = conn.execute(
        "SELECT id, task_type, status FROM scientific_tasks "
        "WHERE status IN ('queued','leased','paused')"
    ).fetchall()
    return {
        "quiescent": not (runs or failed or tasks),
        "in_flight_runs": [list(r) for r in runs],
        "failed_runs_with_checkpoints": [r[0] for r in failed],
        "open_tasks": [list(r) for r in tasks],
    }


_NOT_ENGINE = (
    "CASE WHEN json_valid(state_json) THEN json_extract(state_json,'$.provider') IS NOT 'engine' "
    "ELSE 0 END"
)


def _foreign_checkpoints(conn: sqlite3.Connection, terminal_only: bool) -> int:
    where = (
        "AND run_id IN (SELECT id FROM runs WHERE status IN ('completed','blocked','cancelled'))"
    )
    row = conn.execute(
        f"SELECT COUNT(*) FROM checkpoints WHERE {_NOT_ENGINE} "
        f"{where if terminal_only else ''} AND {_scope('run_id', False)}"
    ).fetchone()
    return int(row[0])


def census(conn: sqlite3.Connection) -> dict[str, Any]:
    groups = _census_groups(conn, False)
    result: dict[str, Any] = {i: groups[i].out() for i in IDS}
    known = TIERS | set(TIER_ALIASES)
    unknown = sorted(
        {
            str(v)
            for (v,) in conn.execute(
                f"SELECT profile FROM runs UNION SELECT {_jx('config_json', '$.tier')} FROM runs"
            )
            if v is not None and v not in known
        }
    )
    result["M01"]["unknown_tier_values"] = unknown
    result["M02"]["by_provider"] = dict(
        conn.execute(
            "SELECT provider, COUNT(*) FROM runs WHERE llm_backend IS NULL "
            f"AND {_scope('id', False)} GROUP BY 1"
        )
    )
    missing_keys = dict.fromkeys(REPORT_KEYS, 0)
    for _table, _id, _run, raw in _payload_rows(conn, False):
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        if _table != "reports" or not isinstance(payload, dict):
            continue
        for k in REPORT_KEYS:
            missing_keys[k] += k not in payload
    result["K06_reports_missing_key"] = missing_keys
    result["K07_runs_without_owner"] = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE client_id=''"
    ).fetchone()[0]
    result["K08_events_without_activity"] = conn.execute(
        "SELECT COUNT(*) FROM run_events WHERE CASE WHEN json_valid(payload_json) "
        "THEN json_type(payload_json,'$.activity') IS NULL ELSE 0 END"
    ).fetchone()[0]
    result["C01_non_engine_checkpoints"] = {
        "terminal_runs": _foreign_checkpoints(conn, True),
        "all_runs": _foreign_checkpoints(conn, False),
    }
    result["provider_counts"] = dict(conn.execute("SELECT provider, COUNT(*) FROM runs GROUP BY 1"))
    demo = _census_groups(conn, True)
    result["demo_runs_old_format"] = {
        i: demo[i].old - groups[i].old for i in IDS if demo[i].old != groups[i].old
    }
    result["quiescence"] = gate_status(conn)
    return result


def verdict_lines(report: dict[str, Any]) -> tuple[list[str], list[str]]:
    residual = {i for i in IDS if report[i]["old_format_rows"]}
    residual |= set(report["demo_runs_old_format"])
    deletable = [i for i in IDS if i not in residual]
    stay = sorted(residual) + list(ALWAYS_STAY)
    quiet = (
        report["quiescence"]["quiescent"] and report["C01_non_engine_checkpoints"]["all_runs"] == 0
    )
    (deletable if quiet else stay).extend(GATED)
    return deletable, sorted(stay)


def _rewrite_reports(conn: sqlite3.Connection, changed: dict[str, int]) -> None:
    for table, row_id, _run, raw in _payload_rows(conn, False):
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        done = upgrade_payload(payload)
        if done:
            conn.execute(
                f"UPDATE {table} SET payload_json=? WHERE id=?", (json.dumps(payload), row_id)
            )
            for key in done:
                changed[key] += 1


def apply_all(conn: sqlite3.Connection) -> dict[str, int]:
    changed = dict.fromkeys((*IDS, "C01"), 0)
    nodemo = f"client_id <> '{DEMO}'"
    changed["M01"] += conn.execute(
        "UPDATE runs SET profile = CASE profile WHEN 'advanced' THEN 'ultra' ELSE 'standard' END "
        f"WHERE profile IN ('advanced','default') AND {nodemo}"
    ).rowcount
    for path in ("$.tier", "$.setup.tier"):
        changed["M01"] += conn.execute(
            f"UPDATE runs SET config_json = json_set(config_json,'{path}', CASE "
            f"json_extract(config_json,'{path}') WHEN 'advanced' THEN 'ultra' ELSE 'standard' END) "
            f"WHERE {_jx('config_json', path)} IN ('advanced','default') AND {nodemo}"
        ).rowcount
    changed["M02"] += conn.execute(
        "UPDATE runs SET llm_backend = CASE provider WHEN 'mock' THEN 'offline' ELSE 'real' END "
        f"WHERE llm_backend IS NULL AND {nodemo}"
    ).rowcount
    for row_id, sup, con in conn.execute(
        "SELECT id, supporting_json, contradicting_json FROM claim_evidence "
        f"WHERE {_scope('run_id', False)}"
    ).fetchall():
        new_sup, new_con = upgrade_span_column(sup), upgrade_span_column(con)
        if new_sup is not None or new_con is not None:
            conn.execute(
                "UPDATE claim_evidence SET supporting_json=?, contradicting_json=? WHERE id=?",
                (
                    new_sup if new_sup is not None else sup,
                    new_con if new_con is not None else con,
                    row_id,
                ),
            )
            changed["M03"] += 1
    _rewrite_reports(conn, changed)
    scope = _scope("run_id", False)
    changed["M05"] = conn.execute(
        f"UPDATE evidence SET retracted=0 WHERE retracted IS NULL AND {scope}"
    ).rowcount
    for row_id, title, abstract in conn.execute(
        f"SELECT id, title, abstract FROM evidence WHERE passage_text IS NULL AND {scope}"
    ).fetchall():
        conn.execute(
            "UPDATE evidence SET passage_text=? WHERE id=?", (passage_text(title, abstract), row_id)
        )
        changed["M06"] += 1
    for row_id, verdict, summary in conn.execute(
        f"SELECT id, verdict, summary FROM reviews WHERE reviewer_agent='scientist' AND {scope}"
    ).fetchall():
        new = scientist_verdict(verdict, summary)
        if new is not None:
            conn.execute("UPDATE reviews SET verdict=? WHERE id=?", (new, row_id))
            changed["M07"] += 1
    changed["M08"] = conn.execute(
        "UPDATE interviews SET fields_json = json_set(fields_json,'$.lab_constraints',json('[]')) "
        "WHERE CASE WHEN json_valid(fields_json) THEN json_type(fields_json) = 'object' "
        "AND json_type(fields_json,'$.lab_constraints') IS NULL ELSE 0 END "
        f"AND {nodemo}"
    ).rowcount
    changed["C01"] = conn.execute(
        f"DELETE FROM checkpoints WHERE {_NOT_ENGINE} AND run_id IN "
        "(SELECT id FROM runs WHERE status IN ('completed','blocked','cancelled') "
        f"AND {nodemo})"
    ).rowcount
    return changed


def _open(path: Path, mode: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode={mode}", uri=True, timeout=30)
    conn.isolation_level = None
    conn.execute("PRAGMA busy_timeout=30000")
    if mode == "rw":
        conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _emit(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))
    deletable, stay = verdict_lines(report)
    print(f"deletable: {deletable}")
    print(f"must_stay: {stay}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--census", action="store_true", help="read-only report")
    mode.add_argument("--apply", action="store_true", help="migrate in one transaction")
    parser.add_argument("--allow-in-flight", action="store_true")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"error: {args.db} does not exist", file=sys.stderr)
        return 1
    conn = _open(args.db, "ro" if args.census else "rw")
    try:
        drift = schema_drift(conn)
        if drift:
            print(json.dumps({"schema_drift": drift}, indent=2), file=sys.stderr)
            return 2
        before = census(conn)
        if args.census:
            _emit(before)
            return 0
        print(json.dumps(before, indent=2, sort_keys=True))
        conn.execute("BEGIN IMMEDIATE")
        try:
            gate = gate_status(conn)
            if not gate["quiescent"] and not args.allow_in_flight:
                print("error: in-flight work; use --allow-in-flight to override", file=sys.stderr)
                conn.execute("ROLLBACK")
                return 3
            changed = apply_all(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        print(json.dumps({"changed": changed}, indent=2, sort_keys=True))
        _emit(census(conn))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
