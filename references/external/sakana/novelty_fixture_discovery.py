"""Run the preregistered keyless M11-NOV-01a PubMed fixture screen."""

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

from co_scientist.config.registry import ToolRegistry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "references/external/sakana/novelty-fixture-discovery-prereg-v1.json"
OUTPUT = ROOT / "references/external/sakana/novelty-fixture-discovery-results-v1.json"
ENDPOINT = "http://127.0.0.1:8899/mcp"
KEYS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "ENTREZ_API_KEY",
    "OPENALEX_API_KEY",
    "BRAVE_API_KEY",
    "TAVILY_API_KEY",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(report: dict[str, Any]) -> None:
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def _check_prereg(prereg: dict[str, Any]) -> None:
    if OUTPUT.exists():
        raise ValueError("Discovery result already exists; never overwrite it")
    if prereg["status"] != "PREREGISTERED_BEFORE_DISCOVERY_CALLS":
        raise ValueError("Discovery protocol is not preregistered")
    source = prereg["source_scope"]
    for name, digest in (
        (source["public_fixture"], source["public_fixture_sha256"]),
        (
            source["independent_abstract_label_note"],
            source["independent_abstract_label_note_sha256"],
        ),
        (source["tool_config"], source["tool_config_sha256"]),
        ("engine/mcp_server/pubmed_query.py", source["pubmed_query_source_sha256"]),
    ):
        if _sha256(ROOT / name) != digest:
            raise ValueError(f"Frozen source changed: {name}")
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD:engine/mcp_server"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tree != source["mcp_tree_commit"]:
        raise ValueError("Maintained MCP tree changed after preregistration")
    if os.environ.get("COSCIENTIST_REQUIRE_FREE_MODELS") != "1":
        raise ValueError("Campaign free-mode gate is required")
    if any(os.environ.get(key) for key in KEYS):
        raise ValueError("Discovery requires a credential-free environment")
    if (ROOT / "engine/mcp_server/.env").exists():
        raise ValueError("MCP colocated .env would load ambient credentials")
    if len(prereg["cases_in_call_order"]) != 3:
        raise ValueError("Expected exactly three frozen discovery cases")


def _papers(raw: Any, parser: ResponseParser) -> list[dict[str, str | None]]:
    payload = parser.parse_response(raw)
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("MCP returned a malformed or error payload")
    articles = parser.parse_to_articles(payload)
    if payload and not articles:
        raise ValueError("Nonempty MCP response yielded no parsed papers")
    if len(articles) > 3:
        raise ValueError("MCP returned more than three papers")
    return [
        {"pmid": str(article.source_id), "title": article.title, "doi": article.doi}
        for article in articles
        if article.source_id
    ]


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
    os.environ["COSCIENTIST_CAMPAIGN_MCP_URL"] = ENDPOINT
    client = MCPToolClient(server_url=ENDPOINT)
    await client.initialize()
    report: dict[str, Any] = {
        "name": prereg["name"],
        "status": "RUNNING",
        "started_at_utc": _utc_now(),
        "prereg_path": str(PREREG.relative_to(ROOT)),
        "prereg_sha256": _sha256(PREREG),
        "checkout_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "mcp_endpoint": ENDPOINT,
        "tool": tool.mcp_tool_name,
        "model_inference_calls": 0,
        "paid_calls": 0,
        "calls": [],
    }
    _write(report)
    for index, case in enumerate(prereg["cases_in_call_order"]):
        if index:
            await asyncio.sleep(1.2)
        query = case["draft"][:200]
        run_id = "m11_nov_01a_" + case["id"].replace("-", "_")
        params = tool.map_parameters(
            {"query": query, "max_papers": 3, "slug": run_id, "run_id": run_id}
        )
        call: dict[str, Any] = {
            "order": index + 1,
            "case_id": case["id"],
            "target_pmid": case["target_pmid"],
            "wire_parameters": params,
            "started_at_utc": _utc_now(),
        }
        try:
            raw = await client.call_tool(tool.mcp_tool_name, **params)
            papers = _papers(raw, parser)
            call["papers"] = papers
            call["target_in_first_three"] = any(
                paper["pmid"] == case["target_pmid"] for paper in papers
            )
            call["classification"] = "success_nonempty" if papers else "success_empty"
        except Exception as exc:
            message = str(exc).lower()
            match = re.search(r"(?:http error|status)\s*(\d{3})", message)
            call["classification"] = (
                "rate_limited"
                if "429" in message or "rate limit" in message
                else "retrieval_error"
            )
            call["exception_type"] = type(exc).__name__
            call["upstream_http_status"] = int(match.group(1)) if match else None
            call["papers"] = []
            call["target_in_first_three"] = False
            call["ended_at_utc"] = _utc_now()
            report["calls"].append(call)
            report["status"] = "INCOMPLETE_RETRIEVAL_ERROR"
            report["ended_at_utc"] = call["ended_at_utc"]
            _write(report)
            return 1
        call["ended_at_utc"] = _utc_now()
        report["calls"].append(call)
        _write(report)
    report["status"] = "COMPLETE"
    report["ended_at_utc"] = _utc_now()
    report["exact_target_hits"] = sum(
        bool(call["target_in_first_three"]) for call in report["calls"]
    )
    _write(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "exact_target_hits": report["exact_target_hits"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
