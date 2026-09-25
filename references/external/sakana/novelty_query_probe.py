"""Run the preregistered, keyless M11-NOV-00b PubMed query comparison."""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from co_scientist.agents.generation.literature_review.queries import (
    _distill_goal_to_query,
)
from co_scientist.config.registry import ToolRegistry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = (
    ROOT / "references/external/sakana/novelty-result-conditioned-fixture-v1.json"
)
PREREG_PATH = ROOT / "references/external/sakana/novelty-query-prereg-v1.json"
AMENDMENT_PATH = (
    ROOT / "references/external/sakana/novelty-query-prereg-amendment-v1.json"
)
OUTPUT_PATH = ROOT / "references/external/sakana/novelty-query-results-v1.json"
FIXTURE_SHA256 = "e0f30c2be18b0b983bdf713efe3c251f065b41601a6d2c0b3a869599ea4eecbb"
QUERY_HELPER = (
    ROOT / "engine/src/co_scientist/agents/generation/literature_review/queries.py"
)
QUERY_HELPER_SHA256 = "8c480080494a8d4f55851d06b8b04749804170f80d413a83925c4d8c30c2b0f1"
MAX_PAPERS = 3
MCP_ENDPOINTS = {
    "baseline": "http://127.0.0.1:8899/mcp",
    "candidate": "http://127.0.0.1:8900/mcp",
}


class _PubMedResultError(RuntimeError):
    def __init__(self, *, rate_limited: bool):
        super().__init__("PubMed MCP returned an upstream error payload")
        self.rate_limited = rate_limited


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_class(exc: Exception) -> str:
    message = str(exc).lower()
    if getattr(exc, "rate_limited", False) or any(
        marker in message for marker in ("429", "rate limit", "too many requests")
    ):
        return "mcp_or_upstream_error_rate_limited"
    if "http error" in message or "internal server error" in message:
        return "mcp_or_upstream_error"
    if isinstance(exc, ValueError):
        return "malformed_result"
    if "mcp" in type(exc).__name__.lower() or "tool" in message:
        return "mcp_or_upstream_error"
    return "transport_error"


def _upstream_http_status(exc: Exception) -> int | None:
    match = re.search(r"HTTP Error (\d{3})", str(exc), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _case_params(case_id: str, tool_config: Any, query: str) -> dict[str, Any]:
    safe_id = case_id.replace("-", "_")
    run_id = f"m11_nov_00b_{safe_id}"
    canonical = {
        "query": query,
        "max_papers": MAX_PAPERS,
        "slug": run_id,
        "run_id": run_id,
    }
    return tool_config.map_parameters(canonical)


def _write(report: dict[str, Any]) -> None:
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n")


async def _parsed_ids(raw: Any, parser: ResponseParser) -> list[str]:
    payload = parser.parse_response(raw)
    if not isinstance(payload, dict):
        raise ValueError("PubMed response was not a dictionary")
    if payload.get("error"):
        error = str(payload["error"]).lower()
        raise _PubMedResultError(
            rate_limited=any(
                marker in error for marker in ("429", "rate limit", "too many requests")
            )
        )
    articles = parser.parse_to_articles(payload)
    ids = [str(article.source_id) for article in articles if article.source_id]
    if payload and not ids:
        raise ValueError("Nonempty PubMed response yielded no parsed paper IDs")
    if len(ids) > MAX_PAPERS:
        raise ValueError("PubMed MCP returned more than max_papers")
    return ids


async def _main() -> int:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    fixture = json.loads(fixture_bytes)
    prereg = json.loads(PREREG_PATH.read_text())
    amendment = json.loads(AMENDMENT_PATH.read_text())
    if hashlib.sha256(fixture_bytes).hexdigest() != FIXTURE_SHA256:
        raise ValueError("Frozen novelty fixture hash changed")
    if _sha256(QUERY_HELPER) != QUERY_HELPER_SHA256:
        raise ValueError("Frozen deterministic keyword helper changed")
    if prereg["status"] != "PREREGISTERED_BEFORE_IMPLEMENTATION_AND_LIVE_COMPARISON":
        raise ValueError("Preregistration status is not eligible")
    if amendment["correction"]["comparison_status_at_amendment"] != (
        "No PubMed MCP tool call or outcome observed."
    ):
        raise ValueError("Unexpected preregistration amendment state")

    registry = ToolRegistry(
        config_path=str(ROOT / "engine/src/co_scientist/config/tools.yaml"),
        skip_user_config=True,
    )
    tool_config = registry.get_tool("pubmed_fulltext")
    if tool_config is None:
        raise ValueError("Configured PubMed fulltext tool is unavailable")
    parser = ResponseParser(tool_config)
    setup_attempts: list[dict[str, Any]] = []
    if OUTPUT_PATH.exists():
        previous = json.loads(OUTPUT_PATH.read_text())
        if previous.get("status") == "INCOMPLETE_SETUP_ERROR":
            setup_attempts.append(
                {
                    "started_at_utc": previous.get("started_at_utc"),
                    "ended_at_utc": previous.get("ended_at_utc"),
                    "status": previous.get("status"),
                    "pubmed_tool_calls": len(previous.get("calls", [])),
                    "classification": "campaign_endpoint_configuration",
                    "exception_type": previous.get("stop_reason", {}).get(
                        "exception_type"
                    ),
                    "sanitized_detail": (
                        "Campaign mode requires one explicitly qualified "
                        "MCP endpoint per client initialization."
                    ),
                }
            )
    report: dict[str, Any] = {
        "name": "M11-NOV-00b paired PubMed query comparison",
        "status": "RUNNING",
        "started_at_utc": _utc_now(),
        "prereg_path": str(PREREG_PATH.relative_to(ROOT)),
        "prereg_commit": "65749e328c74f983e02d3f1ce740b0efb0d92e6f",
        "amendment_path": str(AMENDMENT_PATH.relative_to(ROOT)),
        "amendment_commit": subprocess.run(
            ["git", "rev-parse", "888d29f2"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "fixture_sha256": FIXTURE_SHA256,
        "keyword_helper_sha256": QUERY_HELPER_SHA256,
        "checkout_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "maintained_mcp_tree": subprocess.run(
            ["git", "rev-parse", "HEAD:engine/mcp_server"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "server_endpoints": MCP_ENDPOINTS,
        "tool": tool_config.mcp_tool_name,
        "mcp_http_status": "Not exposed by the maintained MCP client result.",
        "common_request_parameters": {
            "max_papers": MAX_PAPERS,
            "recency_years": "omitted; maintained tool default is 0",
            "slug_and_run_id": "m11_nov_00b_{case_id_with_hyphens_replaced_by_underscores}",
        },
        "runtime": {
            "api_key_present": bool(os.environ.get("ENTREZ_API_KEY")),
            "email_present": bool(os.environ.get("ENTREZ_EMAIL")),
            "free_mode_required": os.environ.get("COSCIENTIST_REQUIRE_FREE_MODELS")
            == "1",
            "model_inference_calls": 0,
            "paid_calls": 0,
            "estimated_cost_usd": 0,
            "cache_roots": {
                "baseline": "/tmp/cosci-m11-nov-00b/baseline",
                "candidate": "/tmp/cosci-m11-nov-00b/candidate",
            },
        },
        "calls": [],
        "setup_attempts": setup_attempts,
        "stop_reason": None,
    }
    _write(report)

    clients: dict[str, MCPToolClient] = {}
    try:
        for arm, endpoint in MCP_ENDPOINTS.items():
            # Campaign admission intentionally binds each client to one
            # explicitly qualified endpoint; initialize them sequentially.
            os.environ["COSCIENTIST_CAMPAIGN_MCP_URL"] = endpoint
            client = MCPToolClient(server_url=endpoint)
            await client.initialize()
            clients[arm] = client
    except Exception as exc:
        report["status"] = "INCOMPLETE_SETUP_ERROR"
        report["stop_reason"] = {
            "classification": "campaign_endpoint_configuration",
            "exception_type": type(exc).__name__,
        }
        report["ended_at_utc"] = _utc_now()
        _write(report)
        return 1

    control_by_id = {item["id"]: item for item in fixture["distinct_idea_controls"]}
    completed = True
    for pair in prereg["design"]["pairs"]:
        cases = [
            (
                "positive",
                fixture["known_prior_art_candidates"][
                    next(
                        index
                        for index, item in enumerate(
                            fixture["known_prior_art_candidates"]
                        )
                        if item["id"] == pair["positive_case"]
                    )
                ],
                pair["positive_target_pmid"],
                pair["control_case"],
            ),
            (
                "control",
                control_by_id[pair["control_case"]],
                pair["control_anchor_pmid"],
                pair["control_pair_positive_pmid"],
            ),
        ]
        for kind, case, anchor_pmid, paired_positive_pmid in cases:
            draft = case["draft"]
            case_id = case["id"]
            expected_candidate = pair["candidate_queries"][kind]
            candidate_query = _distill_goal_to_query(draft)
            if candidate_query != expected_candidate:
                raise ValueError(
                    f"Frozen keyword helper output changed for case {case_id}"
                )
            candidate_params = _case_params(case_id, tool_config, candidate_query)
            baseline_params = _case_params(case_id, tool_config, draft[:200])
            if set(candidate_params) != set(baseline_params) or any(
                candidate_params[key] != baseline_params[key]
                for key in candidate_params
                if key != "query"
            ):
                raise ValueError("Arm request parameters differ beyond query")

            for arm, params in (
                ("baseline", baseline_params),
                ("candidate", candidate_params),
            ):
                started = _utc_now()
                start_clock = time.monotonic()
                call: dict[str, Any] = {
                    "order": len(report["calls"]) + 1,
                    "pair_id": pair["id"],
                    "case_id": case_id,
                    "case_kind": kind,
                    "arm": arm,
                    "query_source": (
                        "draft_prefix_200"
                        if arm == "baseline"
                        else "frozen_keyword_helper"
                    ),
                    "query_length": len(params["query"]),
                    "wire_parameters_without_query": {
                        key: value for key, value in params.items() if key != "query"
                    },
                    "anchor_pmid": anchor_pmid,
                    "paired_positive_pmid": (
                        paired_positive_pmid if kind == "control" else None
                    ),
                    "started_at_utc": started,
                }
                try:
                    os.environ["COSCIENTIST_CAMPAIGN_MCP_URL"] = MCP_ENDPOINTS[arm]
                    raw = await clients[arm].call_tool(
                        tool_config.mcp_tool_name, **params
                    )
                    ids = await _parsed_ids(raw, parser)
                    call["classification"] = (
                        "success_nonempty" if ids else "success_empty"
                    )
                    call["mcp_call_returned"] = True
                    call["returned_ids"] = ids
                    call["returned_count"] = len(ids)
                    call["anchor_hit"] = anchor_pmid in ids
                    call["paired_positive_hit"] = (
                        paired_positive_pmid in ids if kind == "control" else None
                    )
                except Exception as exc:
                    call["classification"] = _error_class(exc)
                    call["mcp_call_returned"] = False
                    call["exception_type"] = type(exc).__name__
                    call["returned_ids"] = []
                    call["returned_count"] = 0
                    call["anchor_hit"] = False
                    call["paired_positive_hit"] = False if kind == "control" else None
                    if call["classification"] == "mcp_or_upstream_error":
                        status_code = _upstream_http_status(exc)
                        if status_code is not None:
                            call["upstream_http_status"] = status_code
                        call["sanitized_error"] = (
                            "PubMed MCP tool execution surfaced an upstream "
                            f"HTTP {status_code or 'error'}."
                        )
                    call["elapsed_ms"] = round((time.monotonic() - start_clock) * 1000)
                    call["ended_at_utc"] = _utc_now()
                    report["calls"].append(call)
                    report["status"] = "INCOMPLETE_RETRIEVAL_ERROR"
                    report["stop_reason"] = {
                        "classification": call["classification"],
                        "case_id": case_id,
                        "arm": arm,
                    }
                    if call.get("upstream_http_status") is not None:
                        report["stop_reason"]["upstream_http_status"] = call[
                            "upstream_http_status"
                        ]
                    report["stop_reason"]["rate_limited"] = (
                        call["classification"] == "mcp_or_upstream_error_rate_limited"
                    )
                    report["ended_at_utc"] = call["ended_at_utc"]
                    _write(report)
                    completed = False
                    break
                call["elapsed_ms"] = round((time.monotonic() - start_clock) * 1000)
                call["ended_at_utc"] = _utc_now()
                report["calls"].append(call)
                _write(report)
                await asyncio.sleep(1.2)
            if not completed:
                break
        if not completed:
            return 1

    by_case_arm = {(call["case_id"], call["arm"]): call for call in report["calls"]}
    positives = [pair["positive_case"] for pair in prereg["design"]["pairs"]]
    controls = [pair["control_case"] for pair in prereg["design"]["pairs"]]
    base_positive_hits = sum(
        by_case_arm[(case_id, "baseline")]["anchor_hit"] for case_id in positives
    )
    candidate_positive_hits = sum(
        by_case_arm[(case_id, "candidate")]["anchor_hit"] for case_id in positives
    )
    base_control_hits = sum(
        by_case_arm[(case_id, "baseline")]["anchor_hit"] for case_id in controls
    )
    candidate_control_hits = sum(
        by_case_arm[(case_id, "candidate")]["anchor_hit"] for case_id in controls
    )
    baseline_target_ids = {
        pair["positive_case"]: pair["positive_target_pmid"]
        for pair in prereg["design"]["pairs"]
        if pair["positive_target_pmid"]
        in by_case_arm[(pair["positive_case"], "baseline")]["returned_ids"]
    }
    positive_losses = [
        case_id
        for case_id, target_id in baseline_target_ids.items()
        if target_id not in by_case_arm[(case_id, "candidate")]["returned_ids"]
    ]
    baseline_cross_hits = sum(
        by_case_arm[(pair["control_case"], "baseline")]["paired_positive_hit"]
        for pair in prereg["design"]["pairs"]
    )
    candidate_cross_hits = sum(
        by_case_arm[(pair["control_case"], "candidate")]["paired_positive_hit"]
        for pair in prereg["design"]["pairs"]
    )
    control_non_regression = candidate_control_hits >= base_control_hits
    no_cross_hit_regression = candidate_cross_hits <= baseline_cross_hits
    primary_improvement = candidate_positive_hits > base_positive_hits
    no_baseline_target_loss = not positive_losses
    adopt = (
        primary_improvement
        and no_baseline_target_loss
        and control_non_regression
        and no_cross_hit_regression
    )
    if adopt:
        disposition = "ADOPTABLE_BY_PREREGISTERED_RETRIEVAL_GATES"
    elif (
        not no_baseline_target_loss
        or not control_non_regression
        or not no_cross_hit_regression
    ):
        disposition = "DO_NOT_ADOPT_MATERIAL_REGRESSION"
    else:
        disposition = "INCONCLUSIVE_NO_PRIMARY_IMPROVEMENT"
    report["metrics"] = {
        "positive_target_recall_at_3": {
            "baseline": f"{base_positive_hits}/3",
            "candidate": f"{candidate_positive_hits}/3",
            "strict_improvement": primary_improvement,
        },
        "positive_baseline_target_losses": positive_losses,
        "control_anchor_hits_at_3": {
            "baseline": f"{base_control_hits}/3",
            "candidate": f"{candidate_control_hits}/3",
            "non_regression": control_non_regression,
        },
        "control_paired_positive_cross_hits": {
            "baseline": baseline_cross_hits,
            "candidate": candidate_cross_hits,
            "non_regression": no_cross_hit_regression,
            "interpretation": "An exact result ID is retrieval evidence only, not a semantic rejection verdict.",
        },
    }
    report["status"] = "COMPLETE"
    report["disposition"] = disposition
    report["ended_at_utc"] = _utc_now()
    _write(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "disposition": disposition,
                "metrics": report["metrics"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
