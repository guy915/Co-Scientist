"""Run the frozen keyless PubMed sort pilot; build IDs are precomputed before server launch."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from co_scientist.config.registry import ToolRegistry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "references/external/sakana"
PREREG = HERE / "novelty-retrieval-diagnosis-prereg-v1.md"
RECOVERY = HERE / "novelty-fixture-recovery-results-v1.json"
FIXTURE = HERE / "novelty-result-conditioned-fixture-v1.json"
FROZEN_HASHES = {
    PREREG: "a9bf6d2e052aedb383a10c94eed9794329290598d5935d17b0d8fc7aa7af7ee0",
    RECOVERY: "8f00b038a38295034086dfeb7c65c0c618669144839d674a184d3afb28483e15",
    FIXTURE: "e0f30c2be18b0b983bdf713efe3c251f065b41601a6d2c0b3a869599ea4eecbb",
}
QUERY_BUILDER_COMMIT = "dd61ae99"
QUERY_BUILDER_SHA256 = (
    "9b2a2838e57fb059733ca9a989d7622aa77d6f7ab0e1019c6267bae94214bee0"
)
MIN_CALL_INTERVAL_SECONDS = 2.0
MAX_OUTER_CALLS = 12
MCP_SECRET = "COSCIENTIST_MCP_SHARED_SECRET"
EXPECTED_SORT = {"baseline": "pub_date", "candidate": "relevance"}
BUILD_RECEIPT = HERE / "novelty-sort-pilot-builds-v1.json"
BUILD_RECEIPT_SHA256 = (
    "742df86e1e111848da7a872066dacda3b3cca67bfda2e193a376b9abced3e6dd"
)
EXPECTED_SOURCE_COMMIT = "d521e9ecc7e60bbc9cb3f36ff61438c0ffcb4b33"


@dataclass(frozen=True)
class PilotCase:
    case_id: str
    pair: str
    kind: str
    draft: str
    query: str
    target_pmid: str
    own_anchor_pmid: str | None


# Fields: case, pair, kind, draft, exact builder query, target PMID, own anchor.
CASES = tuple(
    PilotCase(*row.split("|")[:-1], row.split("|")[-1] or None)
    for row in """
stmn2-tdp43-recovery|stmn2|positive|In motor neurons with TDP-43 dysfunction, use of a cryptic STMN2 polyadenylation signal produces truncated transcripts and limits axonal repair.|TDP-43 STMN2 motor neurons dysfunction cryptic polyadenylation signal produces truncated transcripts limits axonal repair|30643298|
unc13a-cognitive-control|stmn2|control|In Alzheimer’s disease, the UNC13A cryptic-exon risk variant may associate with cognitive decline without tracking TDP-43 pathology.|UNC13A TDP-43 Alzheimer s disease cryptic-exon risk variant cognitive decline without tracking pathology associate|30643298|42596024
sars-entry-recovery|sars|positive|In airway epithelial cells, reducing TMPRSS2 activity should decrease ACE2-dependent infection by SARS-CoV-2 spike-bearing virus.|TMPRSS2 ACE2-dependent SARS-CoV-2 airway epithelial cells reducing activity decrease infection spike-bearing virus|32142651|
sars-isg15-endothelium-control|sars|control|In vascular endothelial cells, SARS-CoV-2 spike S1 may induce inflammatory dysfunction through interferon and ISG15 signaling.|SARS-CoV-2 S1 ISG15 vascular endothelial cells spike induce inflammatory dysfunction through interferon signaling|32142651|42150851
qa1b-tumor-recovery|qa1b|positive|Interferon-rich tumors increase Qa-1b ligand display, engaging inhibitory NKG2A/CD94 on cytotoxic CD8 cells and weakening antitumor killing.|Qa-1b NKG2A/CD94 CD8 Interferon-rich tumors increase ligand display engaging inhibitory cytotoxic cells weakening antitumor killing|36151395|
qa1-cmv-effector-control|qa1b|control|During murine cytomegalovirus infection, Qa-1-restricted CD8 T cells may recognize viral peptides and support host defense.|Qa-1-restricted CD8 During murine cytomegalovirus infection T cells recognize viral peptides support host defense|36151395|41417899
""".strip().splitlines()
)
# Preregistered case indices and arm order.
CALL_ORDER = (
    (0, "baseline"),
    (0, "candidate"),
    (1, "candidate"),
    (1, "baseline"),
    (2, "candidate"),
    (2, "baseline"),
    (3, "baseline"),
    (3, "candidate"),
    (4, "baseline"),
    (4, "candidate"),
    (5, "candidate"),
    (5, "baseline"),
)


@dataclass(frozen=True)
class Arm:
    name: str
    url: str
    cache: Path
    build_id: str
    sort: str
    port: int
    pid: int
    source_file: Path


@dataclass
class PilotRuntime:
    arms: dict[str, Arm]
    tool: Any
    pilot_id: str
    parser: ResponseParser
    clients: dict[str, MCPToolClient] = field(default_factory=dict)
    last_start: float | None = None
    blind_items: list[dict[str, str]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_frozen_inputs() -> None:
    for path, digest in FROZEN_HASHES.items():
        if _sha256(path) != digest:
            raise ValueError(f"Frozen input changed: {path.name}")
    if len(CASES) != 6 or len(CALL_ORDER) != MAX_OUTER_CALLS:
        raise ValueError("Frozen pilot case count or order changed")


def _loopback_url(value: str) -> tuple[str, int]:
    parsed = urlsplit(value)
    port = parsed.port
    valid = (
        parsed.scheme == "http"
        and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        and bool(port)
        and parsed.path == "/mcp"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
    if not valid:
        raise ValueError("MCP URL must be plain loopback http://host:port/mcp")
    return value, port


def _cache(value: str) -> Path:
    path = Path(value).expanduser()
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_dir()
        or any(path.iterdir())
    ):
        raise ValueError("Server caches must be existing empty absolute directories")
    return path.resolve()


def _source_files(source: Path) -> dict[str, bytes]:
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Isolated server source directory is missing")
    return {
        str(path.relative_to(source)): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _source_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _attest_builds() -> tuple[dict[str, Path], dict[str, str]]:
    if _sha256(BUILD_RECEIPT) != BUILD_RECEIPT_SHA256:
        raise ValueError("Committed build receipt changed")
    receipt = json.loads(BUILD_RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("source_commit") != EXPECTED_SOURCE_COMMIT:
        raise ValueError("Build source commit differs from the frozen pilot")
    root = Path(receipt["build_root"]).resolve()
    sources = {name: root / name / "engine/mcp_server" for name in EXPECTED_SORT}
    files = {name: _source_files(source) for name, source in sources.items()}
    changed = {
        key
        for key in files["baseline"].keys() | files["candidate"].keys()
        if files["baseline"].get(key) != files["candidate"].get(key)
    }
    sole = "pubmed_client.py"
    if changed != {sole} or receipt.get("sole_modified_file") != sole:
        raise ValueError("Isolated builds differ beyond the preregistered sort literal")
    baseline = files["baseline"][sole]
    candidate = files["candidate"][sole]
    old = b'PUBMED_SEARCH_SORT = "pub_date"'
    new = b'PUBMED_SEARCH_SORT = "relevance"'
    if baseline.count(old) != 1 or baseline.replace(old, new) != candidate:
        raise ValueError("Candidate source is not the sole sort-literal change")
    hashes = {name: _source_hash(content) for name, content in files.items()}
    if any(hashes[name] != receipt.get(f"{name}_build_id") for name in EXPECTED_SORT):
        raise ValueError("Isolated server source hash differs from committed receipt")
    return sources, hashes


def _listening_pid(port: int) -> int:
    result = subprocess.run(
        ["lsof", "-nP", "-Fpn", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.splitlines()
    pids = [line[1:] for line in lines if line.startswith("p")]
    addresses = [line[1:] for line in lines if line.startswith("n")]
    if (
        result.returncode != 0
        or len(pids) != 1
        or not pids[0].isdigit()
        or len(addresses) != 1
        or addresses[0] not in {f"127.0.0.1:{port}", f"[::1]:{port}"}
    ):
        raise ValueError(f"Expected exactly one loopback listener on port {port}")
    return int(pids[0])


def _preflight(args: argparse.Namespace) -> tuple[dict[str, Arm], Path, Path]:
    _check_frozen_inputs()
    if os.getenv("COSCIENTIST_REQUIRE_FREE_MODELS") != "1":
        raise ValueError("Set COSCIENTIST_REQUIRE_FREE_MODELS=1")
    if len(os.getenv(MCP_SECRET, "")) < 32:
        raise ValueError("A transient MCP shared secret of 32+ characters is required")
    suffixes = (
        "_API_KEY",
        "_TOKEN",
        "_SECRET",
        "_ACCESS_KEY",
        "_PASSWORD",
        "_PRIVATE_KEY",
    )
    credential = next(
        (
            key
            for key, val in os.environ.items()
            if val and key != MCP_SECRET and key.endswith(suffixes)
        ),
        None,
    )
    if credential:
        raise ValueError(f"Credential-free admission failed: {credential} is set")
    if any(
        (ROOT / p).exists() for p in (".env", "engine/.env", "engine/mcp_server/.env")
    ):
        raise ValueError("Repository .env files must be absent for keyless admission")

    sources, hashes = _attest_builds()
    arms = {}
    for name, sort in EXPECTED_SORT.items():
        url, port = _loopback_url(getattr(args, f"{name}_url"))
        build_id = getattr(args, f"{name}_build_id")
        if build_id != hashes[name]:
            raise ValueError(f"{name} build ID differs from attested source")
        pid = getattr(args, f"{name}_pid")
        if pid < 1 or _listening_pid(port) != pid:
            raise ValueError(f"{name} PID does not own port {port}")
        arms[name] = Arm(
            name,
            url,
            _cache(getattr(args, f"{name}_cache")),
            build_id,
            sort,
            port,
            pid,
            (sources[name] / "pubmed_client.py").resolve(),
        )
    base, candidate = arms["baseline"], arms["candidate"]
    if base.port == candidate.port or base.build_id == candidate.build_id:
        raise ValueError("Pilot arms need distinct ports and build IDs")
    if (
        base.cache == candidate.cache
        or base.cache in candidate.cache.parents
        or candidate.cache in base.cache.parents
    ):
        raise ValueError("Pilot caches must be separate and non-nested")
    output = Path(args.output).expanduser().resolve()
    blind = (
        Path(args.blind_output).expanduser().resolve()
        if args.blind_output
        else output.with_name(f"{output.stem}-blind-review.json")
    )
    if output == blind or output.exists() or blind.exists():
        raise ValueError("Result artifacts must use new unique paths")
    if any(
        path == arm.cache or arm.cache in path.parents or path in arm.cache.parents
        for path in (output, blind)
        for arm in arms.values()
    ):
        raise ValueError("Artifacts must be outside both server caches")
    return arms, output, blind


@contextmanager
def _endpoint(url: str) -> Iterator[None]:
    names = ("MCP_SERVER_URL", "COSCIENTIST_CAMPAIGN_MCP_URL")
    old = {key: os.environ.get(key) for key in names}
    os.environ.update({key: url for key in names})
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _reserve(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)


def _save(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


async def _client(runtime: PilotRuntime, name: str) -> MCPToolClient:
    if name not in runtime.clients:
        arm = runtime.arms[name]
        with _endpoint(arm.url):
            client = MCPToolClient(server_url=arm.url)
            await client.initialize()
        runtime.clients[name] = client
    return runtime.clients[name]


def _papers(
    raw: Any, parser: ResponseParser
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    payload = parser.parse_response(raw)
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("MCP returned an error or malformed payload")
    articles = parser.parse_to_articles(payload)
    if len(articles) != len(payload) or len(articles) > 3:
        raise ValueError("MCP response exceeded or violated the three-paper cap")
    records, review = [], []
    for article in articles:
        if not article.source_id:
            raise ValueError("Parsed paper is missing its PMID")
        abstract = article.abstract or ""
        item_id = secrets.token_urlsafe(12)
        records.append({"pmid": str(article.source_id), "blind_item_id": item_id})
        review.append(
            {"item_id": item_id, "title": article.title, "abstract": abstract}
        )
    return records, review


def _ids(value: Any, limit: int) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError("Malformed or over-limit ID list in trace")
    return value


def _rung(row: Any, sort: str, ids_key: str) -> None:
    if not isinstance(row, dict) or row.get("sort") != sort:
        raise ValueError("Malformed search rung or unexpected sort")
    ids = _ids(row.get(ids_key), 9)
    if (
        not isinstance(row.get("rung_index"), int)
        or not isinstance(row.get("rung_type"), str)
        or not isinstance(row.get("count"), int)
        or row["count"] < len(ids)
    ):
        raise ValueError("Search rung fields or count are malformed")


def _trace(raw: Any, arm: Arm, run_id: str) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or raw.get("run_id") != run_id
        or raw.get("server_build_id") != arm.build_id
    ):
        raise ValueError("Trace run/build readback does not match this call")
    pid = raw.get("process_id")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid != arm.pid
        or raw.get("source_file") != str(arm.source_file)
        or raw.get("sort") != arm.sort
    ):
        raise ValueError("Trace process ID or actual sort is invalid")
    attempts = raw.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
        raise ValueError("Trace must preserve the one-to-three-rung search ladder")
    for attempt in attempts:
        _rung(attempt, arm.sort, "first_ids")
    selected = raw.get("selected")
    if selected is not None:
        _rung(selected, arm.sort, "ids")
    _ids(raw.get("final_ids"), 3)
    fetched, supplements = raw.get("fetched"), raw.get("shared_pool_supplements")
    prior = raw.get("pre_search_shared_pool")
    if (
        not isinstance(prior, dict)
        or prior.get("file_count") != 0
        or prior.get("metadata_count") != 0
        or prior.get("first_ids") != []
    ):
        raise ValueError("Shared pool was not empty before the case search")
    if (
        not isinstance(fetched, list)
        or len(fetched) > 9
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("pmid"), str)
            or any(
                not isinstance(row.get(flag), bool)
                for flag in ("fetched", "pmc_available", "abstract_available")
            )
            for row in fetched
        )
    ):
        raise ValueError("Trace fetch flags are malformed or exceed nine IDs")
    if [row["pmid"] for row in fetched] != (
        selected["ids"] if selected is not None else []
    ) or any(row["fetched"] is not True for row in fetched):
        raise ValueError("Selected paper metadata was not completely fetched")
    if (
        not isinstance(supplements, list)
        or len(supplements) > 3
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("pmid"), str)
            or row.get("source") != "shared_pool"
            or row.get("origin") != "current_search"
            or row.get("preexisting") is not False
            or row.get("matched_esearch_first_ids") is not True
            for row in supplements
        )
    ):
        raise ValueError("Trace shared-pool provenance is malformed")
    return raw


def _params(tool: Any, case: PilotCase, run_id: str, slug: str) -> dict[str, Any]:
    params = tool.map_parameters(
        {"query": case.query, "max_papers": 3, "slug": slug, "run_id": run_id}
    )
    if (
        set(params) != {"query", "max_papers", "slug", "run_id"}
        or params["query"] != case.query
        or params["max_papers"] != 3
    ):
        raise ValueError("Maintained ToolConfig mapping changed the frozen request")
    anchors = (case.target_pmid, case.own_anchor_pmid)
    if any(
        anchor and anchor in str(value)
        for anchor in anchors
        for value in params.values()
    ):
        raise ValueError("Target or control anchor leaked into MCP parameters")
    return params


def _record(
    order: int,
    case: PilotCase,
    arm: Arm,
    slug: str,
    run_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "order": order,
        "case_id": case.case_id,
        "arm": arm.name,
        "endpoint_url": arm.url,
        "sort": arm.sort,
        "port": arm.port,
        "cache": str(arm.cache),
        "server_build_id": arm.build_id,
        "slug": slug,
        "run_id": run_id,
        "parameters": params,
        "shared_pool_empty_before_search": True,
        "status": "RUNNING",
    }


async def _execute(
    runtime: PilotRuntime, case: PilotCase, arm: Arm, order: int
) -> dict[str, Any]:
    suffix = f"{order:02d}_{arm.name}"
    slug, run_id = (
        f"m11nov01a3a_{runtime.pilot_id}_{suffix}",
        f"{runtime.pilot_id}_{suffix}",
    )
    namespace = arm.cache / "pubmed" / slug
    if namespace.exists():
        raise ValueError("Case-by-arm namespace already exists")
    params = _params(runtime.tool, case, run_id, slug)
    entry = _record(order, case, arm, slug, run_id, params)
    stage = "initialize"
    try:
        client = await _client(runtime, arm.name)
        stage = "transport"
        runtime.last_start = time.monotonic()
        entry["started_at_utc"] = _utc_now()
        with _endpoint(arm.url):
            raw = await client.call_tool(runtime.tool.mcp_tool_name, **params)
        stage = "parse"
        papers, review = _papers(raw, runtime.parser)
        stage = "trace"
        trace = _trace(
            json.loads(
                (namespace / "runs" / run_id / ".search-trace.json").read_text(
                    encoding="utf-8"
                )
            ),
            arm,
            run_id,
        )
        if [item["pmid"] for item in papers] != trace["final_ids"]:
            raise ValueError("Parsed response IDs differ from the trace")
        entry.update(
            {
                "status": "complete",
                "papers": papers,
                "trace": trace,
                "finished_at_utc": _utc_now(),
            }
        )
        for item in review:
            item["draft"] = case.draft
            runtime.blind_items.append(item)
    except Exception as exc:
        entry.update(
            {"status": "error", "error_stage": stage, "error_class": type(exc).__name__}
        )
    return entry


async def _run(
    runtime: PilotRuntime, report: dict[str, Any], output: Path, blind_output: Path
) -> int:
    for order, (case_index, arm_name) in enumerate(CALL_ORDER, 1):
        if runtime.last_start is not None:
            await asyncio.sleep(
                max(
                    0,
                    MIN_CALL_INTERVAL_SECONDS - (time.monotonic() - runtime.last_start),
                )
            )
        entry = await _execute(
            runtime, CASES[case_index], runtime.arms[arm_name], order
        )
        report["calls"].append(entry)
        if entry["status"] == "error":
            report.update(
                status="STOPPED",
                stopped_at_order=order,
                error={"stage": entry["error_stage"], "class": entry["error_class"]},
                ended_at_utc=_utc_now(),
            )
            _save(output, report)
            return 1
        _save(output, report)
    random.SystemRandom().shuffle(runtime.blind_items)
    _reserve(blind_output)
    _save(
        blind_output,
        {
            "protocol": "M11-NOV-01a3a blinded relevance batch",
            "items": runtime.blind_items,
        },
    )
    report.update(
        status="COMPLETED",
        blinded_review_path=str(blind_output),
        blinded_review_items=len(runtime.blind_items),
        ended_at_utc=_utc_now(),
    )
    _save(output, report)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in EXPECTED_SORT:
        parser.add_argument(f"--{name}-url", required=True)
        parser.add_argument(f"--{name}-cache", required=True)
        parser.add_argument(f"--{name}-build-id", required=True)
        parser.add_argument(f"--{name}-pid", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--blind-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result: Path | None = None
    try:
        arms, output, blind = _preflight(args)
        _reserve(output)
        result = output
        pilot_id = uuid.uuid4().hex[:12]
        report: dict[str, Any] = {
            "pilot": "M11-NOV-01a3a",
            "pilot_run_id": pilot_id,
            "status": "RUNNING",
            "started_at_utc": _utc_now(),
            "input_hashes": {
                path.name: digest for path, digest in FROZEN_HASHES.items()
            },
            "query_builder": {
                "commit": QUERY_BUILDER_COMMIT,
                "sha256": QUERY_BUILDER_SHA256,
            },
            "model_inference_calls": 0,
            "paid_calls": 0,
            "calls": [],
        }
        _save(output, report)
        registry = ToolRegistry(
            config_path=str(ROOT / "engine/src/co_scientist/config/tools.yaml"),
            skip_user_config=True,
        )
        tool = registry.get_tool("pubmed_fulltext")
        if tool is None or tool.mcp_tool_name != "pubmed_search_with_fulltext":
            raise ValueError("Maintained PubMed ToolConfig is unavailable")
        runtime = PilotRuntime(arms, tool, pilot_id, ResponseParser(tool))
        return asyncio.run(_run(runtime, report, output, blind))
    except Exception as exc:
        print(f"Pilot stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        if result is not None:
            try:
                report = json.loads(result.read_text(encoding="utf-8"))
                report.update(
                    {
                        "status": "STOPPED",
                        "error": {"stage": "runner", "class": type(exc).__name__},
                        "ended_at_utc": _utc_now(),
                    }
                )
                _save(result, report)
            except (OSError, json.JSONDecodeError):
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
