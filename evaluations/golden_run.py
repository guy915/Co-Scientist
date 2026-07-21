"""Local MCP-backed golden run.

Drives one small biomedical run through the real production path
(app ``run_workflow`` -> engine -> MCP/INDRA -> drain -> report) against the
LOCAL MCP server, with the INDRA cancer tools config and the semantic (LLM)
claim assessor enabled, then asserts the acceptance from the persisted store
and writes a reproducibility artifact under ``evaluations/results/``.

Acceptance (P0.6): nonzero *real* evidence records (not mock), nonempty support
passages, and at least one authorized INDRA tool invocation with
``indra_cancer.yaml`` — the live acceptance behind CITE-CLAIM-001 and
TOOLS-CONFIG-001.

This makes real provider (DeepSeek) + MCP (PubMed/INDRA) calls and is run out of
band, never in CI. It is LOCAL only; it never touches Railway prod. Re-running
is safe (fresh temp DB each time).

Run:
    DEEPSEEK_API_KEY=... \
    PYTHONPATH=engine/src:app \
    .venv/bin/python -m evaluations.golden_run
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import tempfile
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_RESULTS_DIR = _ROOT / "evaluations" / "results"
_INDRA_CONFIG = (
    _ROOT
    / "engine"
    / "src"
    / "co_scientist"
    / "config"
    / "examples"
    / "indra_cancer.yaml"
)
# The worktree carries no .env; the provider key lives in the main checkout's.
_MAIN_ENV = pathlib.Path("/Users/guy/Code/Co-Scientist/.env")

_INDRA_TOOLS = {
    "query_mechanistic_statements",
    "query_gene_disease_network",
    "query_drug_info",
    "query_gene_codependents",
    "query_pathways",
    "query_clinical_trials",
    "query_causal_subnetwork",
    "run_enrichment_analysis",
}

_GOAL = (
    "Identify a novel small-molecule combination to overcome osimertinib "
    "resistance in EGFR-mutant non-small-cell lung cancer."
)


def _load_provider_key() -> str:
    """Read DEEPSEEK_API_KEY from the environment or the main checkout .env."""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if _MAIN_ENV.exists():
        for line in _MAIN_ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _configure_env(db_path: str) -> None:
    """Set the run's environment BEFORE any app import loads settings.

    Literature review is left enabled (no FORCE_LITERATURE_REVIEW=0), so the
    INDRA/PubMed search tools actually run — the whole point of the golden run.
    """
    os.environ["MODEL_NAME"] = "deepseek/deepseek-chat"
    os.environ["MCP_SERVER_URL"] = "http://localhost:8888/mcp"
    os.environ["TOOLS_CONFIG"] = str(_INDRA_CONFIG)
    os.environ["CLAIM_ASSESSOR"] = "llm"
    os.environ["COSCIENTIST_DB_PATH"] = db_path
    os.environ["DEEPSEEK_API_KEY"] = _load_provider_key()
    os.environ.pop("FORCE_LITERATURE_REVIEW", None)


def _install_tool_call_counter() -> dict[str, int]:
    """Patch the MCP client so every tool invocation is counted by name.

    Lit-review search calls ``call_tool``; tool-calling generation (if any)
    calls ``execute_tool_call``. Both are wrapped so the counts are ground
    truth for "which MCP tools were actually invoked", independent of how
    evidence is later shaped.
    """
    from co_scientist import mcp_client

    counts: dict[str, int] = {}
    orig_call = mcp_client.MCPToolClient.call_tool
    orig_exec = mcp_client.MCPToolClient.execute_tool_call

    async def _counted_call(self: Any, tool_name: str, **kwargs: Any) -> Any:
        counts[tool_name] = counts.get(tool_name, 0) + 1
        return await orig_call(self, tool_name, **kwargs)

    async def _counted_exec(self: Any, tool_call: Any) -> Any:
        name = getattr(getattr(tool_call, "function", None), "name", "?")
        counts[name] = counts.get(name, 0) + 1
        return await orig_exec(self, tool_call)

    mcp_client.MCPToolClient.call_tool = (  # type: ignore[method-assign]
        _counted_call
    )
    mcp_client.MCPToolClient.execute_tool_call = (  # type: ignore[method-assign]
        _counted_exec
    )
    return counts


async def _drive_run(run_id: str, db_path: str) -> int:
    """Run the workflow to completion, returning the number of events seen."""
    from app import engine_adapter

    seen = 0
    async for _event in engine_adapter.run_workflow(
        run_id=run_id,
        research_goal=_GOAL,
        config={
            "initial_hypotheses_count": 2,
            "max_iterations": 1,
            "evolution_max_count": 2,
            "tournament_pairs": 2,
            "evidence_count": 6,
            "enable_literature_review": True,
        },
        db_path=db_path,
        force_provider="engine",
        sleep_seconds=0,
    ):
        seen += 1
    return seen


def _collect(run_id: str, db_path: str) -> dict[str, Any]:
    """Read the persisted artifacts the acceptance is asserted against."""
    from app import store

    evidence = store.list_evidence(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    matches = store.list_matches(run_id, db_path=db_path)
    report = store.get_latest_report(run_id, db_path=db_path)
    hypotheses = store.list_hypotheses(run_id, db_path=db_path)
    return {
        "evidence": evidence,
        "claim_edges": claim_edges,
        "matches": matches,
        "report": report,
        "hypotheses": hypotheses,
    }


def _support_passages(
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten every supporting/contradicting span across all claim edges."""
    spans: list[dict[str, Any]] = []
    for edge in claim_edges:
        for key in ("supporting", "contradicting"):
            for span in edge.get(key) or []:
                if isinstance(span, dict):
                    spans.append(span)
    return spans


def _assess(
    collected: dict[str, Any], tool_calls: dict[str, int]
) -> dict[str, Any]:
    """Compute the acceptance checks over the persisted artifacts."""
    evidence = collected["evidence"]
    sources = sorted({str(e.get("source") or "") for e in evidence})
    indra_calls = {t: c for t, c in tool_calls.items() if t in _INDRA_TOOLS}
    spans = _support_passages(collected["claim_edges"])
    nonempty_spans = [s for s in spans if str(s.get("quote") or "").strip()]

    checks = {
        "nonzero_evidence": len(evidence) > 0,
        "no_mock_sources": bool(evidence) and "mock" not in sources,
        "at_least_one_indra_invocation": sum(indra_calls.values()) > 0,
        "nonempty_support_passages": len(nonempty_spans) > 0,
        "report_produced": collected["report"] is not None,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "evidence_count": len(evidence),
        "evidence_sources": sources,
        "tool_calls": dict(sorted(tool_calls.items())),
        "indra_calls": dict(sorted(indra_calls.items())),
        "claim_edge_count": len(collected["claim_edges"]),
        "support_span_count": len(nonempty_spans),
        "match_count": len(collected["matches"]),
        "hypothesis_count": len(collected["hypotheses"]),
    }


def _sample_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A compact evidence sample for the artifact (title/source/url only)."""
    return [
        {
            "title": e.get("title"),
            "source": e.get("source"),
            "url": e.get("url"),
            "has_abstract": bool(e.get("abstract")),
        }
        for e in evidence[:6]
    ]


def _sample_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A compact support-span sample for the artifact."""
    return [
        {
            "evidence_id": s.get("evidence_id"),
            "quote": s.get("quote"),
            "url": s.get("url"),
        }
        for s in spans[:6]
    ]


def run() -> dict[str, Any]:
    """Execute the golden run and return the reproducibility report."""
    tmp_db = tempfile.mkdtemp(prefix="golden-run-")
    db_path = str(pathlib.Path(tmp_db) / "golden.db")
    _configure_env(db_path)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("no DEEPSEEK_API_KEY available; cannot run")

    tool_calls = _install_tool_call_counter()

    from app import store

    run_row = store.create_run(_GOAL, "standard", "engine", {}, db_path=db_path)
    events = asyncio.run(_drive_run(run_row.id, db_path))
    collected = _collect(run_row.id, db_path)
    assessment = _assess(collected, tool_calls)

    report_row = collected["report"] or {}
    return {
        "goal": _GOAL,
        "provider": "engine",
        "model": os.environ["MODEL_NAME"],
        "mcp_server_url": os.environ["MCP_SERVER_URL"],
        "tools_config": os.environ["TOOLS_CONFIG"],
        "claim_assessor": os.environ["CLAIM_ASSESSOR"],
        "run_id": run_row.id,
        "events_streamed": events,
        "acceptance": assessment,
        "evidence_sample": _sample_evidence(collected["evidence"]),
        "support_span_sample": _sample_spans(
            _support_passages(collected["claim_edges"])
        ),
        "report_hypothesis_count": (report_row.get("payload") or {}).get(
            "hypothesis_count"
        ),
        "reproduce": (
            "DEEPSEEK_API_KEY=... PYTHONPATH=engine/src:app "
            ".venv/bin/python -m evaluations.golden_run"
        ),
        "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def main() -> int:
    """Run the golden run, write the artifact, print a compact summary."""
    report = run()
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _RESULTS_DIR / f"golden-run-indra-{date}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    a = report["acceptance"]
    print(f"golden run: {'PASS' if a['passed'] else 'FAIL'}")
    print(
        f"  evidence={a['evidence_count']} sources={a['evidence_sources']} "
        f"claim_edges={a['claim_edge_count']} spans={a['support_span_count']}"
    )
    print(f"  indra_calls={a['indra_calls']}")
    print(f"  checks={a['checks']}")
    print(f"wrote {out.relative_to(_ROOT)}")
    return 0 if a["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
