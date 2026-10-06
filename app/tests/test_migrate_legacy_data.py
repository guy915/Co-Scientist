from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import db as store_db
from app.store import events as store_events
from app.store import hypotheses, interviews, records, reports, runs
from app.store.hypotheses import NewHypothesis
from app.store.models import RunStatus
from app.store.records import NewClaimEvidence, NewEvidence, NewMatch, NewReview, NewSafetyDecision
from dev import migrate_legacy_data as mig
from dev.backup_db import backup_database
from tests._store_helpers import seed_checkpoint, seed_run

OLD_OWNER = "owner-old"
NEW_OWNER = "owner-new"
SPAN = {"evidence_id": "e1", "quote": "a passage", "url": "", "start": 0, "end": 9}


def _payload(run_id: str, hypothesis_id: str, mode: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "research_goal": "Goal",
        "run_mode": mode,
        "provider": "engine",
        "hypothesis_count": 1,
        "idea_count": 1,
        "verified_count": 0,
        "evidence_count": 2,
        "match_count": 1,
        "citation_summary": {"verified": 1.0},
        "leaderboard": [],
        "meta_review": {},
        "research_overview": {},
        "knowledge_base": [],
        "agent_insights": {
            "recommended_directions": [
                {"focus_area": "f", "recommendation": "r", "justification": "j"}
            ],
        },
        "idea_buckets": {"high_potential": [], "non_viable": []},
        "claim_evidence": [
            {
                "id": 1,
                "hypothesis_id": hypothesis_id,
                "claim": "claim",
                "label": "supports",
                "supporting": [SPAN],
                "contradicting": [],
                "assessor": "det",
            }
        ],
        "degraded_sections": [],
        "skills_used": [],
        "reviews": [],
    }
    return payload


def _modern_run(db: str, goal: str, client: str, status: RunStatus) -> tuple[str, str]:
    run = seed_run(goal, profile="ultra", client_id=client, llm_backend="real", db_path=db)
    hyp = hypotheses.add_hypothesis(
        NewHypothesis(run_id=run.id, title="H", statement="S"), db_path=db
    )
    other = hypotheses.add_hypothesis(
        NewHypothesis(run_id=run.id, title="H2", statement="S2"), db_path=db
    )
    ev = records.add_evidence(NewEvidence(run_id=run.id, title="T", abstract="A"), db_path=db)
    records.add_evidence(NewEvidence(run_id=run.id, title="T2", abstract=""), db_path=db)
    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp,
            claim="claim",
            label="supports",
            supporting=[{**SPAN, "evidence_id": ev}],
            contradicting=[],
            assessor="det",
        ),
        db_path=db,
    )
    records.add_review(
        NewReview(
            run_id=run.id,
            hypothesis_id=hyp,
            reviewer_agent="scientist",
            summary="I would revise this",
            critique="c",
            author="sci",
            verdict="revise",
        ),
        db_path=db,
    )
    records.add_match(
        NewMatch(run.id, 1, hyp, other, 1200, 1216, 1200, 1184, "rationale"), db_path=db
    )
    records.add_safety_decision(
        NewSafetyDecision(run_id=run.id, stage="intake", decision="allow", reason="ok", matches=[]),
        db_path=db,
    )
    report = _payload(run.id, hyp, "ultra")
    saved = reports.save_report(run.id, report, "# Goal Report\n", db_path=db)
    store_events.append_event(run.id, "report", {**report, "report_id": saved["id"]}, db_path=db)
    seed_checkpoint(run.id, {"provider": "engine"}, stage="final", db_path=db)
    runs.update_run_status(run.id, status, db_path=db)
    return run.id, hyp


def _age(db: str, run_id: str, *, tier: str, provider: str, alias_config: bool = True) -> None:
    """Rewrite one modern run into every format M01-M08 replaces. The run detail
    contract rejects an aliased config tier, so only some runs carry one.
    """
    with sqlite3.connect(db) as conn:
        config_tier = tier if alias_config else mig.TIER_ALIASES[tier]
        setup: dict[str, Any] = {
            "goal": "G",
            "requirements": [],
            "attributes": [],
            "criteria": [],
            "focus": "balance",
            "tier": config_tier,
        }
        config = json.dumps({"tier": config_tier, "setup": setup})
        conn.execute(
            "UPDATE runs SET profile=?, provider=?, llm_backend=NULL, config_json=? WHERE id=?",
            (tier, provider, config, run_id),
        )
        conn.execute(
            "UPDATE claim_evidence SET supporting_json=?, contradicting_json=? WHERE run_id=?",
            (json.dumps(["a bare quote"]), json.dumps(["x", SPAN]), run_id),
        )
        conn.execute(
            "UPDATE evidence SET retracted=NULL, passage_text=NULL WHERE run_id=?", (run_id,)
        )
        conn.execute(
            "UPDATE reviews SET verdict=NULL, summary='the idea is oppose-worthy' WHERE run_id=?",
            (run_id,),
        )
        for table, where in (("reports", "1"), ("run_events", "type='report'")):
            for row_id, raw in conn.execute(
                f"SELECT id, payload_json FROM {table} WHERE run_id=? AND {where}", (run_id,)
            ).fetchall():
                payload = json.loads(raw)
                payload["run_mode"] = tier
                for edge in payload["claim_evidence"]:
                    edge["supporting"] = ["a bare quote"]
                    edge["contradicting"] = ["x", SPAN]
                payload["agent_insights"]["recommended_directions"] = ["plain text"]
                conn.execute(
                    f"UPDATE {table} SET payload_json=? WHERE id=?", (json.dumps(payload), row_id)
                )
        conn.execute("DELETE FROM checkpoints WHERE run_id=?", (run_id,))
        conn.execute(
            "INSERT INTO checkpoints (run_id, seq, stage, schema_version, last_event_seq, "
            "state_json, created_at) VALUES (?,1,'old',1,0,?,0)",
            (run_id, json.dumps({"provider": "mock", "legacy": True})),
        )


@pytest.fixture
def legacy_db(isolated_db: str) -> dict[str, Any]:
    db = isolated_db
    old, _ = _modern_run(db, "Old advanced", OLD_OWNER, RunStatus.COMPLETED)
    default, _ = _modern_run(db, "Old default", OLD_OWNER, RunStatus.BLOCKED)
    modern, _ = _modern_run(db, "Modern", NEW_OWNER, RunStatus.COMPLETED)
    demo, _ = _modern_run(db, "Demo", "__demo__", RunStatus.COMPLETED)
    _age(db, old, tier="advanced", provider="mock", alias_config=False)
    _age(db, default, tier="default", provider="engine")
    _age(db, demo, tier="advanced", provider="mock")
    chat = interviews.create_interview(OLD_OWNER, "A challenge", db_path=db)
    with sqlite3.connect(db) as conn:
        fields = json.loads(
            conn.execute("SELECT fields_json FROM interviews WHERE id=?", (chat["id"],)).fetchone()[
                0
            ]
        )
        del fields["lab_constraints"]
        conn.execute(
            "UPDATE interviews SET fields_json=? WHERE id=?", (json.dumps(fields), chat["id"])
        )
    owners = {old: OLD_OWNER, default: OLD_OWNER, modern: NEW_OWNER}
    return {
        "db": db,
        "old": old,
        "default": default,
        "modern": modern,
        "demo": demo,
        "owners": owners,
    }


def _copy(source: str, name: str, tmp_path: Path) -> str:
    target = tmp_path / name
    backup_database(Path(source), target)
    return str(target)


def _apply(path: str, *, allow: bool = False) -> int:
    args = ["--db", path, "--apply"] + (["--allow-in-flight"] if allow else [])
    return int(mig.main(args))


def _census(path: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()
    assert mig.main(["--db", path, "--census"]) == 0
    out = capsys.readouterr().out
    report: dict[str, Any] = json.loads(out.split("\ndeletable:")[0])
    return report


def _dump_run(path: str, run_id: str) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(path) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        found: dict[str, list[tuple[Any, ...]]] = {}
        for name in names:
            columns = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
            key = "id" if name == "runs" else "run_id"
            if key in columns:
                found[name] = conn.execute(
                    f"SELECT * FROM {name} WHERE {key}=?", (run_id,)
                ).fetchall()
        return found


def _updated_at(path: str) -> list[tuple[str, float]]:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT id, updated_at FROM runs ORDER BY id").fetchall()


def _dump(path: str) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(path) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n: conn.execute(f"SELECT * FROM {n} ORDER BY 1").fetchall() for n in sorted(names)}


def test_census_counts_each_old_format_group(
    legacy_db: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    report = _census(legacy_db["db"], capsys)
    assert report["M01"]["runs_affected"] == 2
    # profile, report and report event per run, plus both config tiers on one
    assert report["M01"]["old_format_rows"] == 8
    assert report["M01"]["unknown_tier_values"] == []
    assert report["M02"] == {
        "old_format_rows": 2,
        "malformed_rows": 0,
        "runs_affected": 2,
        "by_provider": {"engine": 1, "mock": 1},
    }
    assert report["M03"]["runs_affected"] == 2
    assert report["M03"]["old_format_rows"] == 6
    assert report["M04"]["old_format_rows"] == 4
    assert report["M05"]["old_format_rows"] == 4
    assert report["M06"]["old_format_rows"] == 4
    assert report["M07"]["old_format_rows"] == 2
    assert report["M08"]["old_format_rows"] == 1
    assert report["demo_runs_old_format"]["M01"] > 0
    assert report["C01_non_engine_checkpoints"] == {"terminal_runs": 2, "all_runs": 2}
    assert report["provider_counts"] == {"engine": 2, "mock": 2}
    assert report["quiescence"]["quiescent"] is True
    assert report["K06_reports_missing_key"]["meta_review"] == 0


def test_apply_clears_every_residual_and_skips_demo_and_modern(
    legacy_db: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    db = legacy_db["db"]
    modern_before = _dump_run(db, legacy_db["modern"])
    demo_before = _dump_run(db, legacy_db["demo"])
    updated_before = _updated_at(db)
    assert _apply(db) == 0
    after = _census(db, capsys)
    for key in mig.IDS:
        assert after[key]["old_format_rows"] == 0
    assert after["C01_non_engine_checkpoints"]["all_runs"] == 0
    assert _dump_run(db, legacy_db["modern"]) == modern_before
    assert _dump_run(db, legacy_db["demo"]) == demo_before
    assert _updated_at(db) == updated_before
    assert after["demo_runs_old_format"]
    capsys.readouterr()
    assert mig.main(["--db", db, "--census"]) == 0
    tail = capsys.readouterr().out.split("\ndeletable:")[1]
    assert "M01" in tail.split("\nmust_stay:")[1]


def test_apply_to_a_demo_free_database_lists_every_m_id_as_deletable(
    legacy_db: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    db = legacy_db["db"]
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE client_id='__demo__'")
    capsys.readouterr()
    assert _apply(db) == 0
    out = capsys.readouterr().out
    assert f"deletable: {[*mig.IDS, *mig.GATED]}" in out
    must_stay = out.split("must_stay: ")[1].strip()
    assert must_stay == str(sorted(mig.ALWAYS_STAY))


def test_second_apply_changes_nothing(legacy_db: dict[str, Any]) -> None:
    db = legacy_db["db"]
    assert _apply(db) == 0
    first = _dump(db)
    conn = mig._open(Path(db), "rw")
    conn.execute("BEGIN IMMEDIATE")
    changed = mig.apply_all(conn)
    conn.execute("COMMIT")
    conn.close()
    assert not any(changed.values())
    assert _apply(db) == 0
    assert _dump(db) == first


def test_census_never_modifies_the_database(legacy_db: dict[str, Any]) -> None:
    db = legacy_db["db"]
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = Path(db).read_bytes()
    assert mig.main(["--db", db, "--census"]) == 0
    assert Path(db).read_bytes() == before


def test_missing_database_is_refused_and_not_created(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    assert mig.main(["--db", str(path), "--census"]) == 1
    assert mig.main(["--db", str(path), "--apply"]) == 1
    assert not path.exists()


def test_gate_refuses_in_flight_work_unless_allowed(
    legacy_db: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    db = legacy_db["db"]
    paused = seed_run("Paused", client_id=OLD_OWNER, llm_backend="real", db_path=db)
    runs.update_run_status(paused.id, RunStatus.PAUSED, db_path=db)
    seed_checkpoint(paused.id, {"provider": "mock"}, stage="old", db_path=db)
    before = _dump(db)
    assert _apply(db) == 3
    assert _dump(db) == before
    gate = _census(db, capsys)["quiescence"]
    assert gate["quiescent"] is False
    assert [paused.id, "paused"] in gate["in_flight_runs"]

    assert _apply(db, allow=True) == 0
    after = _census(db, capsys)
    assert after["M01"]["old_format_rows"] == 0
    # The paused run's checkpoint is never deleted, so C-branches stay.
    assert after["C01_non_engine_checkpoints"]["all_runs"] == 1
    assert mig.main(["--db", db, "--census"]) == 0
    stay = capsys.readouterr().out.split("must_stay: ")[1]
    assert "'C01'" in stay


def test_failed_run_with_a_checkpoint_and_open_tasks_trip_the_gate(
    legacy_db: dict[str, Any],
) -> None:
    db = legacy_db["db"]
    failed = seed_run("Failed", client_id=OLD_OWNER, llm_backend="real", db_path=db)
    runs.update_run_status(failed.id, RunStatus.FAILED, db_path=db)
    seed_checkpoint(failed.id, {"provider": "engine"}, stage="x", db_path=db)
    assert _apply(db) == 3


@pytest.mark.parametrize(
    ("table", "column"), [("runs", "llm_backend"), ("evidence", "passage_text")]
)
def test_drift_preflight_exits_2_when_a_column_is_missing(
    tmp_path: Path, table: str, column: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(tmp_path / "drift.db")
    store_db._initialized.discard(path)
    with store_db.connect(path):
        pass
    with sqlite3.connect(path) as conn:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    assert mig.main(["--db", path, "--census"]) == 2
    assert column in capsys.readouterr().err
    assert _apply(path) == 2


ENDPOINTS = (
    "",
    "/report",
    "/report.md",
    "/hypotheses",
    "/evidence",
    "/reviews",
    "/matches",
    "/claim-evidence",
    "/citations",
    "/safety",
)


def _snapshot(
    path: str, owners: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> dict[tuple[str, str], tuple[int, Any]]:
    monkeypatch.setenv("COSCIENTIST_DB_PATH", path)
    store_db._initialized.discard(path)
    out: dict[tuple[str, str], tuple[int, Any]] = {}
    client = TestClient(app, raise_server_exceptions=False)
    for run_id, owner in owners.items():
        for endpoint in ENDPOINTS:
            response = client.get(f"/api/runs/{run_id}{endpoint}", headers={"X-Client-ID": owner})
            if endpoint == "/report.md" or response.status_code == 500:
                body = response.text
            else:
                body = response.json()
            out[(run_id, endpoint)] = (response.status_code, body)
    chat = client.get("/api/interviews", headers={"X-Client-ID": OLD_OWNER})
    out[("", "interviews")] = (chat.status_code, chat.json())
    return out


def _diff(a: Any, b: Any, path: str = "") -> set[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return {d for k in a.keys() | b.keys() for d in _diff(a.get(k), b.get(k), f"{path}.{k}")}
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return {d for x, y in zip(a, b, strict=True) for d in _diff(x, y, f"{path}[*]")}
    return set() if a == b else {path}


def test_every_api_read_is_unchanged_except_the_documented_upgrades(
    legacy_db: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owners = legacy_db["owners"]
    before_db = _copy(legacy_db["db"], "before.db", tmp_path)
    after_db = _copy(legacy_db["db"], "after.db", tmp_path)
    assert _apply(after_db) == 0
    before = _snapshot(before_db, owners, monkeypatch)
    after = _snapshot(after_db, owners, monkeypatch)
    assert before.keys() == after.keys()
    # The contract has no "default" run mode, so those runs fail to serve until migrated.
    unservable = {(legacy_db["default"], ""), (legacy_db["default"], "/report")}
    assert {k for k, v in before.items() if v[0] != 200} == unservable
    assert all(after[k][0] == 200 for k in unservable)
    fixed = {key: after.pop(key) for key in unservable}
    for key in unservable:
        del before[key]

    allowed = {
        "": {".run_mode", ".profile", ".config.tier", ".config.setup.tier", ".llm_backend"},
        "/report": {
            ".payload.run_mode",
            ".payload.claim_evidence[*].supporting[*]",
            ".payload.claim_evidence[*].supporting[*].evidence_id",
            ".payload.claim_evidence[*].supporting[*].quote",
            ".payload.claim_evidence[*].supporting[*].url",
            ".payload.claim_evidence[*].supporting[*].start",
            ".payload.claim_evidence[*].supporting[*].end",
            ".payload.agent_insights.recommended_directions[*]",
            ".payload.agent_insights.recommended_directions[*].focus_area",
            ".payload.agent_insights.recommended_directions[*].recommendation",
            ".payload.agent_insights.recommended_directions[*].justification",
        },
        "/evidence": {".evidence[*].retracted", ".evidence[*].passage_text"},
        "/reviews": {".reviews[*].verdict"},
    }
    changed_keys: set[tuple[str, str]] = set()
    for key in before:
        found = _diff(before[key][1], after[key][1])
        if not found:
            continue
        changed_keys.add(key)
        endpoint_allowed = allowed.get(key[1], set())
        extra = {
            f
            for f in found
            if f not in endpoint_allowed
            and not f.startswith(".claims")
            and "claim_evidence" not in f
        }
        extra -= {f for f in extra if f.startswith(".evidence[*].") and "passage_text" in f}
        assert not extra, (key, extra)
    assert (legacy_db["modern"], "") not in changed_keys
    assert (legacy_db["modern"], "/report") not in changed_keys
    for run_id in (legacy_db["old"], legacy_db["default"]):
        assert (run_id, "/report.md") not in changed_keys
        assert before[(run_id, "/report.md")] == after[(run_id, "/report.md")]
        assert before[(run_id, "/hypotheses")] == after[(run_id, "/hypotheses")]
        assert before[(run_id, "/matches")] == after[(run_id, "/matches")]
        assert before[(run_id, "/safety")] == after[(run_id, "/safety")]
        assert before[(run_id, "/citations")] == after[(run_id, "/citations")]
    old = after[(legacy_db["old"], "")][1]
    assert (old["run_mode"], old["llm_backend"]) == ("ultra", "offline")
    assert fixed[(legacy_db["default"], "")][1]["run_mode"] == "standard"
    assert fixed[(legacy_db["default"], "")][1]["llm_backend"] == "real"
    review = after[(legacy_db["old"], "/reviews")][1]["reviews"][0]
    assert review["verdict"] == "oppose"
    spans = after[(legacy_db["old"], "/claim-evidence")][1]["claim_evidence"][0]
    assert spans["supporting"] == [{"evidence_id": "", "quote": "a bare quote", "url": ""}]
    directions = after[(legacy_db["old"], "/report")][1]["payload"]["agent_insights"]
    assert directions["recommended_directions"] == [
        {"focus_area": "", "recommendation": "plain text", "justification": ""}
    ]
    assert after[("", "interviews")][1] == before[("", "interviews")][1]


def test_run_provenance_and_passages_read_the_same_after_migration(
    legacy_db: dict[str, Any],
) -> None:
    from app.claims.grounding import evidence_passages

    db = legacy_db["db"]
    old_id = legacy_db["old"]
    before_offline = runs.run_used_offline(runs.get_run(old_id, db_path=db))  # type: ignore[arg-type]
    before_passages = evidence_passages(old_id, db_path=db)
    assert _apply(db) == 0
    assert runs.run_used_offline(runs.get_run(old_id, db_path=db)) is before_offline  # type: ignore[arg-type]
    assert evidence_passages(old_id, db_path=db) == before_passages


@pytest.mark.parametrize("value", [*mig.TIER_ALIASES, *mig.TIERS, "weird", "", None])
def test_tier_converter_matches_the_live_normalizer(value: str | None) -> None:
    from app.run_modes import normalize_run_tier

    if value in mig.TIER_ALIASES:
        assert mig.tier_alias(value) == normalize_run_tier(value)
    else:
        assert mig.tier_alias(value) == value
    assert normalize_run_tier(mig.tier_alias(value)) == normalize_run_tier(value)


def test_frozen_vocabularies_match_the_live_ones() -> None:
    from app.human_input import VERDICT_REVIEW_SCORES
    from app.run_modes import RUN_TIER_DEFAULTS

    assert set(RUN_TIER_DEFAULTS) | {"standard"} == mig.TIERS
    assert tuple(VERDICT_REVIEW_SCORES) == mig.VERDICTS


@pytest.mark.parametrize(
    ("verdict", "summary"),
    [
        (None, "I support this"),
        ("", "needs revise"),
        ("garbage", "we oppose"),
        (None, "no keywords"),
        ("  OPPOSE ", "support"),
        ("support", ""),
        (None, "support and oppose"),
    ],
)
def test_verdict_converter_matches_the_live_reader(verdict: str | None, summary: str) -> None:
    from app.engine_tasks.inputs import _row_verdict

    live = _row_verdict({"verdict": verdict, "summary": summary})
    converted = mig.scientist_verdict(verdict, summary)
    assert (converted or str(verdict).strip().lower()) == live


def test_passage_and_direction_converters_match_the_live_helpers() -> None:
    from app.report.content import _recommended_direction
    from app.store.records import _evidence_passage_text

    for title, abstract in [("T", "A"), ("T", ""), ("", ""), (" T ", " A ")]:
        live = _evidence_passage_text(NewEvidence(run_id="r", title=title, abstract=abstract))
        assert mig.passage_text(title, abstract) == live
    assert mig.passage_text("T", None) == "T"
    assert mig.direction("plain") == _recommended_direction("plain")
    full = {"focus_area": "f", "recommendation": "r", "justification": "j"}
    assert mig.direction(full) == _recommended_direction(full)


def test_span_converter_emits_the_contract_required_keys() -> None:
    from app.api_contracts.science import SupportSpan

    assert set(mig.span("quote")) == {"evidence_id", "quote", "url"}
    assert set(mig.span("quote")) <= set(SupportSpan.__annotations__)
    already = copy.deepcopy(SPAN)
    assert mig.span(already) is already
