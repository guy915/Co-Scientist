"""Record identifier-only Europe PMC results for the frozen M7 source trial."""

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from co_scientist.mcp_client import MCPToolClient


async def run(plan_path: Path, output_path: Path, only_case: str | None = None) -> bool:
    source = plan_path.read_bytes()
    plan = json.loads(source)
    fixture_path = plan_path.with_name("novelty-inputs-v1.json")
    if (
        hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        != plan["frozen_input_sha256"]
    ):
        raise ValueError("M7 novelty inputs differ from the frozen fixture")

    client = MCPToolClient(server_url="http://127.0.0.1:8899/mcp")
    await client.initialize()
    report = {
        "kind": "live public Europe PMC MCP retrieval; no model inference",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": hashlib.sha256(source).hexdigest(),
        "input_sha256": plan["frozen_input_sha256"],
        "tool": "search_europepmc",
        "max_results": plan["max_results_per_call"],
        "calls": [],
    }
    for query_type in ("ablation", "primary"):
        for case in plan["cases"]:
            if only_case and (case["id"] != only_case or query_type != "primary"):
                continue
            query = case[f"{query_type}_query"]
            entry = {"id": case["id"], "query_type": query_type, "query": query}
            try:
                raw = await client.call_tool(
                    "search_europepmc",
                    query=query,
                    max_results=plan["max_results_per_call"],
                )
                data = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(data, dict) or not isinstance(
                    data.get("records"), list
                ):
                    raise TypeError("Europe PMC result lacks a record list")
                entry["source"] = data.get("source")
                entry["papers"] = [
                    {
                        "source_id": paper.get("source_id"),
                        "pmid": paper.get("pmid"),
                        "doi": paper.get("doi"),
                        "title": paper.get("title"),
                        "is_preprint": paper.get("is_preprint"),
                        "has_abstract": bool(paper.get("abstract")),
                    }
                    for paper in data["records"]
                    if isinstance(paper, dict)
                ]
                entry["hit"] = any(
                    case["target_pmid"] == str(paper["pmid"])
                    or case["target_doi"].lower() == str(paper["doi"]).lower()
                    for paper in entry["papers"]
                )
            except Exception as exc:
                entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
            report["calls"].append(entry)
            output_path.write_text(json.dumps(report, indent=2) + "\n")
            print(
                case["id"],
                query_type,
                "error" if "error" in entry else entry["hit"],
                flush=True,
            )
            await asyncio.sleep(1)
    return all("error" not in call for call in report["calls"])


if __name__ == "__main__":
    success = asyncio.run(
        run(
            Path(sys.argv[1]),
            Path(sys.argv[2]),
            sys.argv[3] if len(sys.argv) > 3 else None,
        )
    )
    raise SystemExit(0 if success else 1)
