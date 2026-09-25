"""Run the preregistered keyless M11-NOV-01a2b PubMed fixture screen."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from co_scientist.agents.generation.literature_tools.validate_search import (
    _build_novelty_search_query,
)
from co_scientist.config.registry import ToolRegistry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "references/external/sakana/novelty-fixture-recovery-prereg-v1.json"
OUTPUT = ROOT / "references/external/sakana/novelty-fixture-recovery-results-v1.json"
LOG_PATH = Path("/tmp/cosci-m11-nov-01a2b-mcp.log")
RUNG_LINE = re.compile(
    r"PubMed search: rung_index=(\S+) rung_type=(\S+) result_count=(\d+) "
    r"threshold_met=(True|False) selected_query=(.*)$"
)
MAX_LOG_BYTES_PER_CALL = 1_000_000
MAX_LOGGED_QUERY_CHARS = 160
MCP_SECRET = "COSCIENTIST_MCP_SHARED_SECRET"
CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_ACCESS_KEY")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(report: dict[str, Any]) -> None:
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def _check_prereg(prereg: dict[str, Any]) -> None:
    if OUTPUT.exists():
        raise ValueError("Recovery result already exists; never overwrite it")
    if prereg["status"] != "PREREGISTERED_BEFORE_RECOVERY_CALLS":
        raise ValueError("Recovery protocol is not preregistered")

    source = prereg["source_scope"]
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            source["registration_checkout_commit"],
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise ValueError("Registered source commit is not an ancestor of this checkout")
    for tree_path, key in (
        ("engine/mcp_server", "mcp_server_tree"),
        ("engine/src/co_scientist", "engine_source_tree"),
    ):
        if _git("rev-parse", f"HEAD:{tree_path}") != source[key]:
            raise ValueError(f"Frozen source tree changed: {tree_path}")
    for name, digest in source["runtime_file_sha256"].items():
        if _sha256(ROOT / name) != digest:
            raise ValueError(f"Frozen source changed: {name}")
    for path_key, hash_key in (
        ("public_fixture", "public_fixture_sha256"),
        ("independent_abstract_label_note", "independent_abstract_label_note_sha256"),
    ):
        if _sha256(ROOT / source[path_key]) != source[hash_key]:
            raise ValueError(f"Frozen reference changed: {source[path_key]}")
    original = json.loads((ROOT / source["original_discovery_prereg"]).read_text())
    if (
        _sha256(ROOT / source["original_discovery_prereg"])
        != source["original_discovery_prereg_sha256"]
    ):
        raise ValueError("Original discovery preregistration changed")
    expected = original["cases_in_call_order"]
    cases = prereg["cases_in_call_order"]
    if len(cases) != 3 or len(expected) != 3:
        raise ValueError("Expected exactly three frozen recovery cases")
    for case, old_case in zip(cases, expected, strict=True):
        if (
            case["id"] != old_case["id"]
            or case["target_pmid"] != old_case["target_pmid"]
            or case["raw_draft"] != old_case["draft"]
        ):
            raise ValueError("Recovery case differs from the original preregistration")
        if _build_novelty_search_query(case["raw_draft"]) != case["wire_query"]:
            raise ValueError(f"Frozen production query changed: {case['id']}")

    if os.environ.get("COSCIENTIST_REQUIRE_FREE_MODELS") != "1":
        raise ValueError("Campaign free-mode gate is required")
    if os.environ.get("COSCIENTIST_CACHE_DIR") != prereg["runtime_boundary"]["cache"]:
        raise ValueError("Dedicated screen cache is required")
    endpoint = prereg["request_contract"]["endpoint"]
    if (
        os.environ.get("MCP_SERVER_URL") != endpoint
        or os.environ.get("COSCIENTIST_CAMPAIGN_MCP_URL") != endpoint
    ):
        raise ValueError(
            "Both MCP endpoint gates must name the frozen loopback endpoint"
        )
    if not os.environ.get(MCP_SECRET):
        raise ValueError("Transient loopback MCP authentication is required")
    if any(
        value and name != MCP_SECRET and name.endswith(CREDENTIAL_SUFFIXES)
        for name, value in os.environ.items()
    ):
        raise ValueError("Recovery requires a credential-free environment")
    if any(
        (ROOT / path).exists()
        for path in (".env", "engine/.env", "engine/mcp_server/.env")
    ):
        raise ValueError("A repository .env file could load credentials")

    cache = Path(prereg["runtime_boundary"]["cache"])
    if not cache.is_dir() or cache.is_symlink() or any(cache.iterdir()):
        raise ValueError("The isolated screen cache must exist and be empty")
    if not LOG_PATH.is_file():
        raise ValueError("Dedicated MCP INFO log capture is required")


def _papers(raw: Any, parser: ResponseParser) -> list[dict[str, Any]]:
    payload = parser.parse_response(raw)
    if not isinstance(payload, dict):
        raise ValueError("MCP returned a malformed or error payload")
    if payload.get("error"):
        raise ValueError(f"MCP returned an error payload: {payload['error']}")
    articles = parser.parse_to_articles(payload)
    if payload and not articles:
        raise ValueError("Nonempty MCP response yielded no parsed papers")
    if len(articles) > 3:
        raise ValueError("MCP returned more than three papers")
    papers = []
    for article in articles[:3]:
        if not article.source_id:
            continue
        abstract = article.abstract
        papers.append(
            {
                "pmid": str(article.source_id),
                "title": article.title,
                "doi": article.doi,
                "abstract_sha256": (
                    hashlib.sha256(abstract.encode("utf-8")).hexdigest()
                    if isinstance(abstract, str) and abstract
                    else None
                ),
            }
        )
    return papers


def _rung_events(log_path: Path, start: int) -> tuple[list[dict[str, Any]], int]:
    if log_path.stat().st_size - start > MAX_LOG_BYTES_PER_CALL:
        raise ValueError("MCP log growth exceeded the preregistered capture bound")
    with log_path.open("rb") as stream:
        stream.seek(start)
        raw = stream.read(MAX_LOG_BYTES_PER_CALL + 1)
    if len(raw) > MAX_LOG_BYTES_PER_CALL:
        raise ValueError("MCP log growth exceeded the preregistered capture bound")
    text = raw.decode("utf-8", errors="replace")
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "PubMed search: rung_index=" not in line:
            continue
        match = RUNG_LINE.search(line)
        if not match:
            raise ValueError("Selected-rung log line did not match its frozen format")
        query_log = match.group(5)
        if len(query_log) > MAX_LOGGED_QUERY_CHARS:
            raise ValueError("Selected-query log field exceeded its frozen bound")
        rung = match.group(1)
        events.append(
            {
                "rung_index": int(rung) if rung.isdigit() else None,
                "rung_type": match.group(2),
                "result_count": int(match.group(3)),
                "threshold_met": match.group(4) == "True",
                "selected_query_log": query_log,
            }
        )
    return events, start + len(raw)


async def _main() -> int:
    prereg = json.loads(PREREG.read_text())
    _check_prereg(prereg)
    registry = ToolRegistry(
        config_path=str(ROOT / "engine/src/co_scientist/config/tools.yaml"),
        skip_user_config=True,
    )
    tool = registry.get_tool("pubmed_fulltext")
    if tool is None or tool.mcp_tool_name != "pubmed_search_with_fulltext":
        raise ValueError("Maintained PubMed tool is unavailable")
    parser = ResponseParser(tool)
    log_path = Path(prereg["runtime_boundary"]["server_log_path"])
    if log_path != LOG_PATH:
        raise ValueError("MCP log path differs from the frozen capture path")
    log_offset = log_path.stat().st_size
    client = MCPToolClient(server_url=prereg["request_contract"]["endpoint"])
    try:
        await client.initialize()
    except Exception as exc:
        raise RuntimeError(
            f"MCP initialization failed ({type(exc).__name__})"
        ) from None

    report: dict[str, Any] = {
        "name": prereg["name"],
        "status": "RUNNING",
        "started_at_utc": _utc_now(),
        "prereg_path": str(PREREG.relative_to(ROOT)),
        "prereg_sha256": _sha256(PREREG),
        "checkout_commit": _git("rev-parse", "HEAD"),
        "tool": tool.mcp_tool_name,
        "model_inference_calls": 0,
        "paid_calls": 0,
        "raw_server_logs_retained": False,
        "calls": [],
    }
    _write(report)

    for index, case in enumerate(prereg["cases_in_call_order"]):
        if index:
            await asyncio.sleep(1.2)
        call_started = _utc_now()
        run_id = "m11_nov_01a2b_" + case["id"].replace("-", "_")
        params = tool.map_parameters(
            {
                "query": case["wire_query"],
                "max_papers": 3,
                "slug": run_id,
                "run_id": run_id,
            }
        )
        call: dict[str, Any] = {
            "order": index + 1,
            "case_id": case["id"],
            "target_pmid": case["target_pmid"],
            "raw_draft": case["raw_draft"],
            "wire_query": case["wire_query"],
            "wire_parameters": params,
            "started_at_utc": call_started,
        }
        papers: list[dict[str, Any]] = []
        error: Exception | None = None
        retrieval_failed = False
        try:
            raw = await client.call_tool(tool.mcp_tool_name, **params)
            papers = _papers(raw, parser)
        except Exception as exc:
            error = exc
            retrieval_failed = True

        try:
            events, log_offset = _rung_events(log_path, log_offset)
            if len(events) != 1:
                raise ValueError("Expected one selected-rung log event for this call")
            call["selected_rung"] = events[0]
        except Exception as exc:
            call["selected_rung_evidence_error"] = type(exc).__name__
            if error is None:
                error = exc

        call["ended_at_utc"] = _utc_now()
        call["papers"] = papers
        call["target_in_top_three"] = any(
            paper["pmid"] == case["target_pmid"] for paper in papers
        )
        call["abstract_review"] = {
            "status": "PENDING_PRIMARY_SOURCE_ABSTRACT_REVIEW",
            "papers": [
                {"pmid": paper["pmid"], "label": None, "reason": None}
                for paper in papers
            ],
        }
        if error is None:
            call["classification"] = "success_nonempty" if papers else "success_empty"
        else:
            message = str(error).lower()
            match = re.search(r"(?:http error|status)\s*(\d{3})", message)
            call["classification"] = (
                "rate_limited"
                if "429" in message or "rate limit" in message
                else "retrieval_error"
                if retrieval_failed
                else "selected_rung_evidence_error"
            )
            call["exception_type"] = type(error).__name__
            call["upstream_http_status"] = int(match.group(1)) if match else None
        report["calls"].append(call)
        _write(report)
        if error is not None:
            report["status"] = (
                "INCOMPLETE_RETRIEVAL_ERROR"
                if retrieval_failed
                else "INCOMPLETE_EVIDENCE_ERROR"
            )
            report["ended_at_utc"] = call["ended_at_utc"]
            _write(report)
            return 1

    report["status"] = "SCREEN_COMPLETE_ABSTRACT_REVIEW_PENDING"
    report["ended_at_utc"] = _utc_now()
    hits = sum(bool(call["target_in_top_three"]) for call in report["calls"])
    report["exact_target_hits"] = hits
    report["target_recall_at_3"] = hits / 3
    report["abstract_mechanism_relevance"] = "PENDING_PRIMARY_SOURCE_ABSTRACT_REVIEW"
    _write(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "calls": len(report["calls"]),
                "target_recall_at_3": report["target_recall_at_3"],
                "abstract_review_pending": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
