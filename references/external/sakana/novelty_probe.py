"""Record identifier-only PubMed results for the frozen M7 novelty inputs."""

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from co_scientist.mcp_client import MCPToolClient


async def run(input_path: Path, output_path: Path) -> bool:
    source = input_path.read_bytes()
    inputs = json.loads(source)
    client = MCPToolClient(server_url="http://127.0.0.1:8899/mcp")
    await client.initialize()
    report = {
        "kind": "live public MCP retrieval; no model inference",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": hashlib.sha256(source).hexdigest(),
        "tool": "pubmed_search_with_fulltext",
        "max_papers": inputs["baseline"]["max_papers"],
        "calls": [],
    }
    for case in inputs["cases"]:
        query = case["draft_hypothesis"][:200]
        entry = {"id": case["id"], "query": query, "target_pmid": case["target_pmid"]}
        try:
            raw = await client.call_tool(
                "pubmed_search_with_fulltext",
                query=query,
                slug=f"m7_novelty_{case['id'].replace('-', '_')}",
                max_papers=inputs["baseline"]["max_papers"],
            )
            papers = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(papers, dict):
                raise TypeError("PubMed result is not a paper mapping")
            entry["papers"] = [
                {
                    "id": key,
                    "pmid": paper.get("pmid"),
                    "doi": paper.get("doi"),
                    "title": paper.get("title"),
                }
                for key, paper in papers.items()
                if isinstance(paper, dict)
            ]
            entry["hit"] = any(
                case["target_pmid"] in (paper["id"], paper["pmid"])
                or case["target_doi"].lower() == str(paper["doi"]).lower()
                for paper in entry["papers"]
            )
        except Exception as exc:
            entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["calls"].append(entry)
        output_path.write_text(json.dumps(report, indent=2) + "\n")
        print(case["id"], "error" if "error" in entry else entry["hit"], flush=True)
        await asyncio.sleep(1)
    return all("error" not in call for call in report["calls"])


if __name__ == "__main__":
    success = asyncio.run(run(Path(sys.argv[1]), Path(sys.argv[2])))
    raise SystemExit(0 if success else 1)
