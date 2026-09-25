"""Run the frozen, keyless M11 precise-rung paired PubMed pilot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from co_scientist.config.registry import ToolRegistry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser
import novelty_sort_pilot as shared_pilot

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "references/external/sakana"
PREREG = HERE / "novelty-precise-rung-prereg-v1.json"
PREREG_SHA256 = "5b9d7a0ac076fb44574a2b357f6b7de2a5bc151140049ac478f6d3e96b69d08b"
AMENDMENT = HERE / "novelty-precise-rung-protocol-amendment-2026-09-25.json"
RUNNER_RELPATH = "references/external/sakana/novelty_precise_rung_runner.py"
BASELINE_COMMIT = "1ce3992ce0950b45979f7325fd66f7383f41afa0"
MAX_OUTER_CALLS = 12
MAX_RUNG_CALLS = 3
MAX_ESEARCH_CALLS = 36
MAX_IDS_PER_CALL = 9
MAX_PAPERS = 3
MIN_CALL_INTERVAL_SECONDS = 2.0
MCP_SECRET = "COSCIENTIST_MCP_SHARED_SECRET"
EXPECTED_SORT = {"baseline": "pub_date", "candidate": "pub_date"}
EXPECTED_DIFF_PATHS = (
    "engine/mcp_server/pubmed_query.py",
    "engine/mcp_server/tests/test_pubmed_query.py",
)
_cache = shared_pilot._cache
_endpoint = shared_pilot._endpoint
_listening_pid = shared_pilot._listening_pid
_loopback_url = shared_pilot._loopback_url
_papers = shared_pilot._papers
_reserve = shared_pilot._reserve
_save = shared_pilot._save


@dataclass(frozen=True)
class Request:
    request_id: str
    query: str


REQUESTS = (
    Request(
        "R01",
        "PML supports detached breast cancer cell survival by increasing fatty-acid oxidation, ATP production, and resistance to anoikis.",
    ),
    Request(
        "R02",
        "MYC induces ADHFE1 in breast cancer, generating D-2-hydroxyglutarate and reactive oxygen that drive reductive glutamine metabolism, dedifferentiation, and mesenchymal transition.",
    ),
    Request(
        "R03",
        "Loss of folliculin activates AMPK–PGC-1α mitochondrial biogenesis and ROS-driven HIF transcription, promoting Warburg reprogramming and tumorigenesis.",
    ),
    Request(
        "R04",
        "Hypoxic tumor cells export lactate that oxygenated cancer cells import through MCT1 for oxidative metabolism, creating a metabolic symbiosis.",
    ),
    Request(
        "R05",
        "In lung cancer, c-Maf programs immunosuppressive macrophages through TCA-cycle and UDP-GlcNAc metabolism, suppressing T-cell activity and promoting tumor progression.",
    ),
    Request(
        "R06",
        "Tumor lactate activates macrophage mTORC1, suppresses TFEB-dependent ATP6V0d2, and supports HIF-2α-mediated VEGF production and tumor growth.",
    ),
)
CALL_ORDER = tuple(
    (request.request_id, arm)
    for request in REQUESTS
    for arm in ("baseline", "candidate")
)
REQUEST_BY_ID = {request.request_id: request for request in REQUESTS}


@dataclass(frozen=True)
class Arm:
    name: str
    url: str
    root: Path
    cache: Path
    build_id: str
    commit: str
    tree_sha256: str
    diff_sha256: str
    sort: str
    port: int
    pid: int
    source_file: Path


@dataclass
class Runtime:
    arms: dict[str, Arm]
    tool: Any
    pilot_id: str
    parser: ResponseParser
    clients: dict[str, MCPToolClient] = field(default_factory=dict)
    last_start: float | None = None
    esearch_calls: int = 0
    metadata_ids: int = 0
    blind_items: list[dict[str, str]] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _tree_files(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Isolated MCP source tree is missing or symlinked")
    files: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("Isolated MCP source tree contains a symlink")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _tree_sha256(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, contents in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(contents)
        digest.update(b"\0")
    return digest.hexdigest()


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Could not attest isolated build with git")
    return result.stdout


def _commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").decode("ascii").strip()


def _candidate_diff(
    root: Path, baseline: str, candidate: str
) -> tuple[str, tuple[str, ...]]:
    changed = tuple(
        line
        for line in _git(
            root,
            "diff",
            "--name-only",
            baseline,
            candidate,
            "--",
            "engine/mcp_server",
        )
        .decode("utf-8")
        .splitlines()
    )
    if changed != EXPECTED_DIFF_PATHS:
        raise ValueError("Candidate diff includes an unapproved file")
    diff = _git(
        root,
        "diff",
        "--no-ext-diff",
        "--binary",
        baseline,
        candidate,
        "--",
        "engine/mcp_server/pubmed_query.py",
    )
    return hashlib.sha256(diff).hexdigest(), changed


def _protocol(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    if not PREREG.is_file() or PREREG.is_symlink():
        raise ValueError("Frozen preregistration is missing")
    prereg_digest = _sha256_file(PREREG)
    if prereg_digest != PREREG_SHA256:
        raise ValueError("Frozen preregistration changed")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    try:
        frozen_inputs_digest = _canonical_json_sha256(prereg["request_inputs"])
        source_manifest_digest = _canonical_json_sha256(prereg["source_evidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Frozen preregistration digest inputs are invalid") from exc
    if not AMENDMENT.is_file() or AMENDMENT.is_symlink():
        raise ValueError("Dated protocol amendment is missing; retrieval is closed")
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    required = {
        "status",
        "live_retrieval_authorized",
        "prereg_sha256",
        "baseline_commit",
        "baseline_tree_sha256",
        "candidate_commit",
        "candidate_tree_sha256",
        "candidate_diff_sha256",
        "runner_path",
        "runner_sha256",
        "corrected_frozen_inputs_sha256",
        "corrected_source_manifest_sha256",
    }
    if not isinstance(amendment, dict) or not required <= amendment.keys():
        raise ValueError("Protocol amendment is incomplete")
    if amendment["status"] != "authorized_for_retrieval":
        raise ValueError("Protocol amendment has not authorized retrieval")
    if amendment["live_retrieval_authorized"] is not True:
        raise ValueError("Live retrieval authorization is closed")
    if amendment["prereg_sha256"] != prereg_digest:
        raise ValueError("Protocol amendment does not pin the frozen preregistration")
    if amendment["corrected_frozen_inputs_sha256"] != frozen_inputs_digest:
        raise ValueError("Protocol amendment does not pin canonical request inputs")
    if amendment["corrected_source_manifest_sha256"] != source_manifest_digest:
        raise ValueError("Protocol amendment does not pin canonical source evidence")
    if amendment["baseline_commit"] != BASELINE_COMMIT:
        raise ValueError("Protocol amendment changed the preregistered baseline")
    if amendment["runner_path"] != RUNNER_RELPATH:
        raise ValueError("Protocol amendment names a different runner")
    if amendment["runner_sha256"] != _sha256_file(Path(__file__).resolve()):
        raise ValueError("Protocol amendment does not pin this runner build")

    roots = {
        "baseline": Path(args.baseline_root).expanduser().resolve(),
        "candidate": Path(args.candidate_root).expanduser().resolve(),
    }
    files = {
        name: _tree_files(root / "engine/mcp_server") for name, root in roots.items()
    }
    commits = {name: _commit(root) for name, root in roots.items()}
    if commits["baseline"] != BASELINE_COMMIT:
        raise ValueError("Baseline process is not built from the preregistered commit")
    if commits["candidate"] != amendment["candidate_commit"]:
        raise ValueError("Candidate process commit differs from the amendment")
    trees = {name: _tree_sha256(files[name]) for name in files}
    if trees["baseline"] != amendment["baseline_tree_sha256"]:
        raise ValueError("Baseline source tree differs from the amendment")
    if trees["candidate"] != amendment["candidate_tree_sha256"]:
        raise ValueError("Candidate source tree differs from the amendment")
    diff_sha, changed_files = _candidate_diff(
        roots["candidate"], commits["baseline"], commits["candidate"]
    )
    if diff_sha != amendment["candidate_diff_sha256"]:
        raise ValueError("Candidate runtime diff differs from the amendment")
    for name in files["baseline"].keys() | files["candidate"].keys():
        if name not in {
            "pubmed_query.py",
            "tests/test_pubmed_query.py",
        } and files["baseline"].get(name) != files["candidate"].get(name):
            raise ValueError("Candidate changes an unapproved MCP server file")

    return amendment, {name: trees[name] for name in trees} | {
        "candidate_diff_sha256": diff_sha,
        "candidate_changed_files": list(changed_files),
        "frozen_inputs_sha256": frozen_inputs_digest,
        "source_manifest_sha256": source_manifest_digest,
    }


def _check_environment(roots: dict[str, Path]) -> None:
    if len(os.getenv(MCP_SECRET, "")) < 32:
        raise ValueError("A transient MCP shared secret of 32+ characters is required")
    credential_suffixes = (
        "_API_KEY",
        "_ACCESS_KEY_ID",
        "_ACCESS_KEY",
        "_KEY",
        "_TOKEN",
        "_SECRET",
        "_PASSWORD",
        "_PRIVATE_KEY",
        "_CREDENTIALS",
    )
    credential = next(
        (
            key
            for key, value in os.environ.items()
            if value
            and key != MCP_SECRET
            and (
                key.endswith(credential_suffixes)
                or key == "GOOGLE_APPLICATION_CREDENTIALS"
            )
        ),
        None,
    )
    if credential:
        raise ValueError(f"Ambient credential is set: {credential}")
    if os.getenv("DISABLE_SSL_VERIFY", "").lower() in {"1", "true", "yes"}:
        raise ValueError("TLS verification must stay enabled")
    for root in (ROOT, *roots.values()):
        if any(
            (root / path).exists()
            for path in (".env", "engine/.env", "engine/mcp_server/.env")
        ):
            raise ValueError("Build roots must not contain .env credential files")


def _preflight(
    args: argparse.Namespace,
) -> tuple[dict[str, Arm], Path, Path, dict[str, Any]]:
    _, hashes = _protocol(args)
    roots = {
        "baseline": Path(args.baseline_root).expanduser().resolve(),
        "candidate": Path(args.candidate_root).expanduser().resolve(),
    }
    _check_environment(roots)
    arms: dict[str, Arm] = {}
    for name, sort in EXPECTED_SORT.items():
        url, port = _loopback_url(getattr(args, f"{name}_url"))
        pid = getattr(args, f"{name}_pid")
        if pid < 1 or _listening_pid(port) != pid:
            raise ValueError(f"{name} PID does not own port {port}")
        arms[name] = Arm(
            name=name,
            url=url,
            root=roots[name],
            cache=_cache(getattr(args, f"{name}_cache")),
            build_id=hashes[name],
            commit=_commit(roots[name]),
            tree_sha256=hashes[name],
            diff_sha256=hashes["candidate_diff_sha256"],
            sort=sort,
            port=port,
            pid=pid,
            source_file=(roots[name] / "engine/mcp_server/pubmed_client.py").resolve(),
        )
    base, candidate = arms["baseline"], arms["candidate"]
    if base.port == candidate.port or base.build_id == candidate.build_id:
        raise ValueError("Pilot arms need distinct ports and source builds")
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
    return (
        arms,
        output,
        blind,
        {
            "baseline_tree_sha256": base.tree_sha256,
            "candidate_tree_sha256": candidate.tree_sha256,
            "candidate_diff_sha256": candidate.diff_sha256,
            "candidate_changed_files": hashes["candidate_changed_files"],
            "frozen_inputs_sha256": hashes["frozen_inputs_sha256"],
            "source_manifest_sha256": hashes["source_manifest_sha256"],
        },
    )


async def _client(runtime: Runtime, name: str) -> MCPToolClient:
    if name not in runtime.clients:
        arm = runtime.arms[name]
        with _endpoint(arm.url):
            client = MCPToolClient(server_url=arm.url)
            await client.initialize()
        runtime.clients[name] = client
    return runtime.clients[name]


def _id_list(value: Any, limit: int) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError("Malformed or over-limit PMID list in trace")
    return value


def _validate_rung(row: Any, sort: str, ids_key: str) -> None:
    if not isinstance(row, dict) or row.get("sort") != sort:
        raise ValueError("Malformed search rung or unexpected sort")
    ids = _id_list(row.get(ids_key), MAX_IDS_PER_CALL)
    if (
        not isinstance(row.get("rung_index"), int)
        or isinstance(row.get("rung_index"), bool)
        or not isinstance(row.get("rung_type"), str)
        or not isinstance(row.get("count"), int)
        or isinstance(row.get("count"), bool)
        or row["count"] < len(ids)
    ):
        raise ValueError("Search rung fields or count are malformed")
    if len(ids) != min(row["count"], MAX_IDS_PER_CALL) or len(ids) != len(set(ids)):
        raise ValueError("Search rung ID prefix is incomplete or contains duplicates")


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
        raise ValueError("Trace process ID, source file, or actual sort is invalid")
    attempts = raw.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= MAX_RUNG_CALLS:
        raise ValueError("Trace must preserve one-to-three ESearch rungs")
    indexes: list[int] = []
    for attempt in attempts:
        _validate_rung(attempt, arm.sort, "first_ids")
        indexes.append(attempt["rung_index"])
    if indexes != list(range(1, len(indexes) + 1)):
        raise ValueError("Trace rung order is invalid")
    selected = raw.get("selected")
    if selected is not None:
        _validate_rung(selected, arm.sort, "ids")
        if selected.get("rung_index") not in indexes:
            raise ValueError("Selected rung is absent from attempted-rung trace")
        matching_attempt = attempts[indexes.index(selected["rung_index"])]
        if selected.get("rung_type") != matching_attempt["rung_type"]:
            raise ValueError("Selected rung type does not match its attempt")
        selected_ids = selected["ids"]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("Selected PMID list contains duplicates")
    else:
        selected_ids = []
    final_ids = _id_list(raw.get("final_ids"), MAX_PAPERS)
    attempted_ids = {pmid for attempt in attempts for pmid in attempt["first_ids"]}
    if any(pmid not in attempted_ids for pmid in selected_ids):
        raise ValueError("Selected PMID is absent from the attempted-rung trace")
    fetched = raw.get("fetched")
    if (
        not isinstance(fetched, list)
        or len(fetched) > MAX_IDS_PER_CALL
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("pmid"), str)
            or any(
                not isinstance(row.get(field), bool)
                for field in ("fetched", "pmc_available", "abstract_available")
            )
            for row in fetched
        )
    ):
        raise ValueError("Trace metadata-fetch flags are malformed")
    if [row["pmid"] for row in fetched] != selected_ids or any(
        row["fetched"] is not True for row in fetched
    ):
        raise ValueError("Selected PMID metadata was not completely fetched")
    prior = raw.get("pre_search_shared_pool")
    if (
        not isinstance(prior, dict)
        or prior.get("file_count") != 0
        or isinstance(prior.get("file_count"), bool)
        or prior.get("metadata_count") != 0
        or isinstance(prior.get("metadata_count"), bool)
        or prior.get("first_ids") != []
    ):
        raise ValueError("Per-call shared pool was not empty before search")
    supplements = raw.get("shared_pool_supplements")
    if (
        not isinstance(supplements, list)
        or len(supplements) > MAX_PAPERS
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("pmid"), str)
            or row.get("source") != "shared_pool"
            or row.get("origin") != "current_search"
            or not isinstance(row.get("preexisting"), bool)
            or not isinstance(row.get("matched_esearch_first_ids"), bool)
            for row in supplements
        )
    ):
        raise ValueError("Trace pool-supplement provenance is malformed")
    if any(
        row["preexisting"] is not False or row["matched_esearch_first_ids"] is not True
        for row in supplements
    ):
        raise ValueError("Trace shows cross-case shared-pool carry-over")
    if len({row["pmid"] for row in supplements}) != len(supplements) or any(
        row["pmid"] not in selected_ids for row in supplements
    ):
        raise ValueError("Pool supplement is outside the selected current-search IDs")
    if any(pmid not in selected_ids for pmid in final_ids):
        raise ValueError("Final paper is outside selected ESearch IDs")
    return raw


def _params(tool: Any, request: Request, run_id: str, slug: str) -> dict[str, Any]:
    params = tool.map_parameters(
        {
            "query": request.query,
            "max_papers": MAX_PAPERS,
            "recency_years": 0,
            "slug": slug,
            "run_id": run_id,
        }
    )
    expected = {"query", "max_papers", "recency_years", "slug", "run_id"}
    if set(params) != expected or params != {
        "query": request.query,
        "max_papers": MAX_PAPERS,
        "recency_years": 0,
        "slug": slug,
        "run_id": run_id,
    }:
        raise ValueError("Maintained ToolConfig mapping changed the frozen request")
    return params


def _record(
    order: int,
    request: Request,
    arm: Arm,
    slug: str,
    run_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "order": order,
        "request_id": request.request_id,
        "arm": arm.name,
        "endpoint_url": arm.url,
        "sort": arm.sort,
        "port": arm.port,
        "process_id": arm.pid,
        "server_commit": arm.commit,
        "server_tree_sha256": arm.tree_sha256,
        "candidate_diff_sha256": arm.diff_sha256,
        "cache": str(arm.cache),
        "server_build_id": arm.build_id,
        "slug": slug,
        "run_id": run_id,
        "query": request.query,
        "parameters": params,
        "status": "RUNNING",
    }


async def _execute(
    runtime: Runtime, request: Request, arm: Arm, order: int
) -> dict[str, Any]:
    suffix = f"{request.request_id.lower()}_{arm.name}"
    slug = f"m11novrung_{runtime.pilot_id}_{suffix}"
    run_id = f"{runtime.pilot_id}_{suffix}"
    namespace = arm.cache / "pubmed" / slug
    if namespace.exists():
        raise ValueError("Request-by-arm cache namespace already exists")
    params = _params(runtime.tool, request, run_id, slug)
    entry = _record(order, request, arm, slug, run_id, params)
    stage = "initialize"
    try:
        client = await _client(runtime, arm.name)
        stage = "transport"
        entry["started_at_utc"] = _utc_now()
        runtime.last_start = time.monotonic()
        with _endpoint(arm.url):
            raw = await client.call_tool(runtime.tool.mcp_tool_name, **params)
        stage = "parse"
        papers, blind_items = _papers(raw, runtime.parser)
        stage = "trace"
        trace_path = namespace / "runs" / run_id / ".search-trace.json"
        trace = _trace(json.loads(trace_path.read_text(encoding="utf-8")), arm, run_id)
        if [paper["pmid"] for paper in papers] != trace["final_ids"]:
            raise ValueError("Parsed PMID order differs from final trace")
        if any(
            len(attempt["first_ids"]) > MAX_IDS_PER_CALL
            for attempt in trace["attempts"]
        ):
            raise ValueError("An ESearch rung exceeded the nine-ID bound")
        runtime.esearch_calls += len(trace["attempts"])
        if runtime.esearch_calls > MAX_ESEARCH_CALLS:
            raise ValueError("Batch exceeded the 36-ESearch hard bound")
        runtime.metadata_ids += len(trace["fetched"])
        if runtime.metadata_ids > MAX_OUTER_CALLS * MAX_IDS_PER_CALL:
            raise ValueError("Batch exceeded the 108-ID metadata bound")
        entry.update(
            status="complete",
            papers=papers,
            trace=trace,
            esearch_call_count=len(trace["attempts"]),
            metadata_ids_submitted=len(trace["fetched"]),
            finished_at_utc=_utc_now(),
        )
        runtime.blind_items.extend(blind_items)
    except Exception as exc:
        entry.update(
            status="error",
            error_stage=stage,
            error_class=type(exc).__name__,
        )
        if stage == "trace" and isinstance(exc, FileNotFoundError):
            entry["missing_trace_path"] = str(trace_path)[:500]
    return entry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(
    runtime: Runtime, report: dict[str, Any], output: Path, blind_output: Path
) -> int:
    for order, (request_id, arm_name) in enumerate(CALL_ORDER, 1):
        if runtime.last_start is not None:
            await asyncio.sleep(
                max(
                    0.0,
                    MIN_CALL_INTERVAL_SECONDS - (time.monotonic() - runtime.last_start),
                )
            )
        entry = await _execute(
            runtime,
            REQUEST_BY_ID[request_id],
            runtime.arms[arm_name],
            order,
        )
        report["calls"].append(entry)
        report["esearch_call_count"] = runtime.esearch_calls
        report["metadata_ids_submitted"] = runtime.metadata_ids
        _save(output, report)
        if entry["status"] == "error":
            report.update(
                status="STOPPED",
                stopped_at_order=order,
                error={"stage": entry["error_stage"], "class": entry["error_class"]},
                ended_at_utc=_utc_now(),
            )
            _save(output, report)
            return 1
    _reserve(blind_output)
    secrets.SystemRandom().shuffle(runtime.blind_items)
    _save(
        blind_output,
        {
            "protocol": "M11-NOV-RUNG-01a blinded relevance batch",
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
        parser.add_argument(f"--{name}-root", required=True)
        parser.add_argument(f"--{name}-cache", required=True)
        parser.add_argument(f"--{name}-pid", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--blind-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output: Path | None = None
    reserved = False
    try:
        arms, output, blind, hashes = _preflight(args)
        _reserve(output)
        reserved = True
        pilot_id = uuid.uuid4().hex[:12]
        report: dict[str, Any] = {
            "pilot": "M11-NOV-RUNG-01a",
            "pilot_run_id": pilot_id,
            "status": "RUNNING",
            "started_at_utc": _utc_now(),
            "prereg_sha256": PREREG_SHA256,
            "frozen_inputs_sha256": hashes["frozen_inputs_sha256"],
            "source_manifest_sha256": hashes["source_manifest_sha256"],
            "protocol_amendment_sha256": _sha256_file(AMENDMENT),
            "runner_path": RUNNER_RELPATH,
            "runner_sha256": _sha256_file(Path(__file__).resolve()),
            "baseline_commit": arms["baseline"].commit,
            "candidate_commit": arms["candidate"].commit,
            "candidate_changed_files": hashes["candidate_changed_files"],
            "build_hashes": {
                name: value
                for name, value in hashes.items()
                if name.endswith("_sha256")
            },
            "model_inference_calls": 0,
            "paid_calls": 0,
            "max_outer_calls": MAX_OUTER_CALLS,
            "max_esearch_calls": MAX_ESEARCH_CALLS,
            "esearch_call_count": 0,
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
        runtime = Runtime(arms, tool, pilot_id, ResponseParser(tool))
        return asyncio.run(_run(runtime, report, output, blind))
    except Exception as exc:
        print(f"Pilot stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        if reserved and output is not None and output.exists():
            try:
                report = json.loads(output.read_text(encoding="utf-8"))
                report.update(
                    status="STOPPED",
                    error={"stage": "runner", "class": type(exc).__name__},
                    ended_at_utc=_utc_now(),
                )
                _save(output, report)
            except (OSError, json.JSONDecodeError):
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
