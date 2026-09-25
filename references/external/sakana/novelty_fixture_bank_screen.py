"""Screen the frozen M11 fixture bank through the configured validator search."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from co_scientist.agents.generation.literature_tools.validate_search import (
    _NoveltySearchContext,
    _find_search_tool,
    _search_papers_for_hypothesis,
)
from co_scientist.config.registry import ToolRegistry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = Path(__file__).resolve().parents[3]
PREREG_V1 = ROOT / "references/external/sakana/novelty-fixture-bank-prereg-v1.json"
PREREG_V2 = ROOT / "references/external/sakana/novelty-fixture-bank-prereg-v2.json"
PREREG = PREREG_V1
RESULT_DIR = ROOT / "references/external/sakana"
TOOL_CONFIG = Path("engine/src/co_scientist/config/tools.yaml")
EXPECTED_PREREG_SHA256 = (
    "66e616e0b4e9089b4b8d971781ce0a15f81cf202c4a949a645a7bd8b13e810a1"
)
EXPECTED_PREREG_V2_SHA256 = (
    "a1b1df652f7c8beb4dfc070f88e1986f555e1d61b9027470086a0508432453ca"
)
BANKS: dict[int, dict[str, Any]] = {
    1: {
        "path": PREREG_V1,
        "sha256": EXPECTED_PREREG_SHA256,
        "status": "PREREGISTERED_BEFORE_ANY_VALIDATOR_SCREEN",
        "slug_prefix": "m11_nov_01a3b2",
        "result_prefix": "novelty-fixture-bank-screen-results-v1",
        "private_prefix": "cosci-m11-nov-01a3b2-labels",
    },
    2: {
        "path": PREREG_V2,
        "sha256": EXPECTED_PREREG_V2_SHA256,
        "status": "PREREGISTERED_BEFORE_ANY_V2_VALIDATOR_SCREEN",
        "slug_prefix": "m11_nov_01a3b2_v2",
        "result_prefix": "novelty-fixture-bank-screen-results-v2",
        "private_prefix": "cosci-m11-nov-01a3b2-v2-labels",
    },
}
MCP_SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"
CREDENTIAL_SUFFIXES = (
    "_API_KEY",
    "_TOKEN",
    "_SECRET",
    "_ACCESS_KEY",
    "_PASSWORD",
    "_PRIVATE_KEY",
)
MAX_TRACE_IDS = 9
MIN_CALL_START_SPACING_SECONDS = 1.2


class MCPResponseError(RuntimeError):
    """A maintained MCP call returned an explicit error payload."""

    def __init__(self, status: int | None, retry_after: str | None):
        super().__init__("MCP returned an error payload")
        self.status_code = status
        self.retry_after = retry_after


class _RecordingClient:
    """Capture one outer MCP response while preserving the client's behavior."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.last_tool: str | None = None
        self.last_params: dict[str, Any] | None = None
        self.last_response: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    async def call_tool(self, tool_name: str, **params: Any) -> Any:
        self.last_tool = tool_name
        self.last_params = dict(params)
        self.last_response = None
        self.last_response = await self.client.call_tool(tool_name, **params)
        return self.last_response


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bank_config(bank_version: int = 1) -> dict[str, Any]:
    try:
        return BANKS[bank_version]
    except KeyError as exc:
        raise ValueError(f"Unsupported fixture bank version: {bank_version}") from exc


def _load_preregistration(bank_version: int = 1) -> dict[str, Any]:
    bank = _bank_config(bank_version)
    if _sha256(bank["path"]) != bank["sha256"]:
        raise ValueError("Fixture-bank preregistration hash changed")
    return json.loads(bank["path"].read_text(encoding="utf-8"))


def _new_output_paths(
    bank_version: int = 1,
    *,
    result_dir: Path | None = None,
    private_dir: Path | None = None,
) -> tuple[Path, Path]:
    bank = _bank_config(bank_version)
    result_dir = RESULT_DIR if result_dir is None else result_dir
    private_dir = Path("/tmp") if private_dir is None else private_dir
    result = result_dir / f"{bank['result_prefix']}-{uuid.uuid4().hex[:12]}.json"
    private = private_dir / f"{bank['private_prefix']}-{uuid.uuid4().hex}.json"
    return result, private


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _check_server_tree_clean() -> None:
    """Reject modified, staged, or untracked maintained MCP source files."""
    status = _git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        "engine/mcp_server",
    )
    if status:
        raise ValueError("Maintained MCP source tree is dirty or untracked")


def _check_environment(env: dict[str, str] | None = None) -> None:
    """Require exact-zero admission and reject inherited service credentials."""
    env = os.environ if env is None else env
    if env.get("COSCIENTIST_REQUIRE_FREE_MODELS") != "1":
        raise ValueError("Set COSCIENTIST_REQUIRE_FREE_MODELS=1")
    if any(
        value and name != MCP_SECRET_ENV and name.endswith(CREDENTIAL_SUFFIXES)
        for name, value in env.items()
    ):
        raise ValueError("Screen requires a credential-free environment")


def _check_prereg(
    prereg: dict[str, Any], *, cache_root: Path, bank_version: int = 1
) -> str:
    """Enforce the committed protocol, its code hashes, and source checkout."""
    bank = _bank_config(bank_version)
    if _sha256(bank["path"]) != bank["sha256"]:
        raise ValueError("Fixture-bank preregistration hash changed")
    if prereg.get("status") != bank["status"]:
        raise ValueError("Fixture-bank protocol is not preregistered")
    boundary = prereg["validation_boundary"]
    for path_key, hash_key in (
        ("validator", "validator_sha256"),
        ("parser", "parser_sha256"),
        ("tool_config", "tool_config_sha256"),
    ):
        path = boundary[path_key]
        if _sha256(ROOT / path) != boundary[hash_key]:
            raise ValueError(f"Frozen validator source changed: {path}")
    registered_commit = boundary["code_commit_before_registration"]
    _check_server_tree_clean()
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", registered_commit, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode:
        raise ValueError("Registered validator commit is not an ancestor")
    server_tree = _git("rev-parse", f"{registered_commit}:engine/mcp_server")
    if boundary.get("mcp_tree") and boundary["mcp_tree"] != server_tree:
        raise ValueError("Registered MCP source tree differs from preregistration")
    if _git("rev-parse", "HEAD:engine/mcp_server") != server_tree:
        raise ValueError("Maintained MCP source tree changed after preregistration")
    pairs = prereg["cases_in_fixed_order"]
    if len(pairs) != 6 or prereg["screening_protocol"]["maximum_outer_calls"] != 12:
        raise ValueError("Expected the frozen six-pair, twelve-call screen")
    for pair in pairs:
        for arm in ("positive", "distinct_control"):
            draft = pair[arm]["draft"]
            if not draft or len(draft) > 200:
                raise ValueError("Frozen draft is empty or exceeds the query bound")
            target = pair[arm].get("target_pmid", pair[arm].get("anchor_pmid"))
            if not str(target).isdigit():
                raise ValueError("Frozen source PMID is malformed")
    if cache_root.is_symlink() or not cache_root.is_absolute():
        raise ValueError("Screen cache must be an absolute, non-symlink directory")
    if not cache_root.is_dir() or any(cache_root.iterdir()):
        raise ValueError("Screen cache must exist and be newly empty")
    return server_tree


def _check_runtime(
    prereg: dict[str, Any], *, bank_version: int = 1
) -> tuple[str, Path, str]:
    _check_environment()
    endpoint = os.environ.get("COSCIENTIST_CAMPAIGN_MCP_URL", "")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.port
        or parsed.path != "/mcp"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MCP endpoint must be plain loopback HTTP /mcp")
    if os.environ.get("MCP_SERVER_URL") != endpoint:
        raise ValueError("MCP_SERVER_URL must match the qualified loopback endpoint")
    if len(os.environ.get(MCP_SECRET_ENV, "")) < 32:
        raise ValueError(
            "A transient loopback MCP secret of 32+ characters is required"
        )
    if os.environ.get("COSCIENTIST_PUBMED_PILOT_TRACE") != "1":
        raise ValueError("Maintained PubMed run tracing must be enabled")
    cache_root = Path(os.environ.get("COSCIENTIST_LIT_REVIEW_DIR", ""))
    expected_build = _check_prereg(
        prereg, cache_root=cache_root, bank_version=bank_version
    )
    if os.environ.get("COSCIENTIST_PUBMED_PILOT_BUILD_ID") != expected_build:
        raise ValueError("MCP trace build ID must match the frozen maintained source")
    if any(
        (ROOT / name).exists()
        for name in (".env", "engine/.env", "engine/mcp_server/.env")
    ):
        raise ValueError(
            "Remove repository .env files before credential-free screening"
        )
    return endpoint, cache_root, expected_build


def _error_metadata(exc: Exception) -> tuple[int | None, str | None, bool]:
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    headers = getattr(exc, "headers", None) or getattr(response, "headers", None)
    retry_after = None
    if headers is not None:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after is None:
        retry_after = getattr(exc, "retry_after", None)
    message = str(exc).lower()
    if status is None:
        match = re.search(r"\b(?:http\s*)?(?:status\s*)?(\d{3})\b", message)
        status = int(match.group(1)) if match else None
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    limited = status == 429 or "rate limit" in message or "too many requests" in message
    return status, str(retry_after) if retry_after is not None else None, limited


def _payload_error(response: Any) -> MCPResponseError | None:
    if not isinstance(response, str):
        payload = response
    else:
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            status_match = re.search(r"\b429\b", response)
            return MCPResponseError(429, None) if status_match else None
    if not isinstance(payload, dict) or "error" not in payload:
        return None
    error = payload["error"]
    text = str(error).lower()
    status = payload.get("status_code") or payload.get("status")
    if status is None:
        match = re.search(r"\b(?:http\s*)?(?:status\s*)?(\d{3})\b", text)
        status = int(match.group(1)) if match else None
    retry_after = payload.get("retry_after")
    return MCPResponseError(
        int(status) if status is not None and str(status).isdigit() else None,
        str(retry_after) if retry_after is not None else None,
    )


def _trace_path(cache_root: Path, slug: str, run_id: str) -> Path:
    return cache_root / "pubmed" / slug / "runs" / run_id / ".search-trace.json"


def _trace_evidence(path: Path, run_id: str, expected_build: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Maintained PubMed trace is missing")
    trace = json.loads(path.read_text(encoding="utf-8"))
    if trace.get("run_id") != run_id or trace.get("server_build_id") != expected_build:
        raise ValueError("Maintained PubMed trace does not match this request/build")
    attempts = trace.get("attempts", [])
    fetched = trace.get("fetched", [])
    if len(attempts) > 8 or len(fetched) > MAX_TRACE_IDS:
        raise ValueError("Maintained PubMed trace exceeds its frozen bound")
    return {
        "run_id": run_id,
        "server_build_id": expected_build,
        "sort": trace.get("sort"),
        "attempts": [
            {
                "rung_index": item.get("rung_index"),
                "rung_type": item.get("rung_type"),
                "count": item.get("count"),
                "first_ids": list(item.get("first_ids", []))[:MAX_TRACE_IDS],
                "sort": item.get("sort"),
            }
            for item in attempts
        ],
        "selected": {
            key: trace.get("selected", {}).get(key)
            for key in ("rung_index", "rung_type", "count", "ids", "sort")
        }
        if isinstance(trace.get("selected"), dict)
        else None,
        "pre_search_shared_pool": {
            "file_count": trace.get("pre_search_shared_pool", {}).get("file_count"),
            "metadata_count": trace.get("pre_search_shared_pool", {}).get(
                "metadata_count"
            ),
            "first_ids": trace.get("pre_search_shared_pool", {}).get("first_ids", [])[
                :MAX_TRACE_IDS
            ],
        },
        "fetched": [
            {
                "pmid": item.get("pmid"),
                "fetched": item.get("fetched"),
                "pmc_available": item.get("pmc_available"),
                "abstract_available": item.get("abstract_available"),
            }
            for item in fetched
        ],
        "final_ids": list(trace.get("final_ids", []))[:3],
        "shared_pool_supplements": [
            {
                key: item.get(key)
                for key in (
                    "pmid",
                    "source",
                    "origin",
                    "preexisting",
                    "matched_esearch_first_ids",
                )
            }
            for item in trace.get("shared_pool_supplements", [])[:3]
        ],
    }


def _write_json(path: Path, value: dict[str, Any], *, private: bool = False) -> None:
    encoded = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if not path.exists():
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
        return
    path.write_text(encoded, encoding="utf-8")
    if private:
        path.chmod(0o600)


def _blank_error_payload(client: _RecordingClient, parser: ResponseParser) -> Any:
    response = client.last_response
    if response is None:
        return None
    payload = parser.parse_response(response)
    return payload if isinstance(payload, dict) else None


async def _screen(
    prereg: dict[str, Any],
    registry: ToolRegistry,
    client: Any,
    cache_root: Path,
    result_path: Path,
    private_path: Path,
    *,
    expected_build_id: str,
    sleep: Any = asyncio.sleep,
    bank_version: int = 1,
) -> dict[str, Any]:
    """Make one configured validator search per frozen draft and stop on error."""
    if result_path.exists() or private_path.exists():
        raise ValueError("Screen artifacts already exist; never overwrite a prior run")
    tool_id, tool = _find_search_tool(registry)
    if (
        tool_id != "pubmed_fulltext"
        or not tool
        or tool.mcp_tool_name != "pubmed_search_with_fulltext"
    ):
        raise ValueError("First validation search tool differs from preregistration")
    parser = ResponseParser(tool)
    recorder = (
        client if isinstance(client, _RecordingClient) else _RecordingClient(client)
    )
    nonce = uuid.uuid4().hex[:12]
    report: dict[str, Any] = {
        "name": prereg["name"],
        "status": "RUNNING",
        "prereg_sha256": _sha256(_bank_config(bank_version)["path"]),
        "tool": tool.mcp_tool_name,
        "model_inference_calls": 0,
        "paid_calls": 0,
        "raw_abstracts_in_result": False,
        "calls": [],
    }
    private_packet: dict[str, Any] = {"status": "BLIND_LABELS_PENDING", "items": []}
    _write_json(result_path, report)
    _write_json(private_path, private_packet, private=True)
    order = 0

    for pair in prereg["cases_in_fixed_order"]:
        for arm in ("positive", "distinct_control"):
            order += 1
            draft = pair[arm]["draft"]
            run_id = f"{_bank_config(bank_version)['slug_prefix']}_{nonce}_{order:02d}"
            call: dict[str, Any] = {
                "order": order,
                "pair_id": pair["id"],
                "arm": arm,
                "target_pmid": pair[arm].get("target_pmid"),
                "anchor_pmid": pair[arm].get("anchor_pmid"),
                "draft": draft,
                "wire_query": draft[:200],
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "papers": [],
            }
            if order > 1:
                await sleep(MIN_CALL_START_SPACING_SECONDS)
            error: Exception | None = None
            papers: dict[str, dict[str, Any]] = {}
            ctx = _NoveltySearchContext(
                mcp_client=recorder,
                tool_registry=registry,
                shared_slug=run_id,
                run_id=run_id,
            )
            try:
                # This is the production helper: one configured MCP call, parameter map,
                # and ResponseParser pass. No novelty model stage is invoked.
                papers = await _search_papers_for_hypothesis(draft, ctx, max_papers=3)
                payload_error = _payload_error(recorder.last_response)
                if payload_error is not None:
                    raise payload_error
            except Exception as exc:
                error = exc
            call["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
            call["tool"] = recorder.last_tool
            call["wire_parameters"] = recorder.last_params
            payload = _blank_error_payload(recorder, parser)
            raw_records = payload if isinstance(payload, dict) else {}
            for rank, (paper_id, metadata) in enumerate(papers.items(), start=1):
                source = raw_records.get(str(paper_id), {})
                abstract = (
                    source.get("abstract", "") if isinstance(source, dict) else ""
                )
                abstract = abstract if isinstance(abstract, str) else ""
                blind_id = uuid.uuid4().hex
                paper = {
                    "rank": rank,
                    "pmid": str(paper_id),
                    "title": metadata.get("title"),
                    "authors": metadata.get("authors", []),
                    "year": metadata.get("year"),
                    "doi": source.get("doi") if isinstance(source, dict) else None,
                    "abstract_available": bool(abstract.strip()),
                    "abstract_sha256": hashlib.sha256(
                        abstract.encode("utf-8")
                    ).hexdigest()
                    if abstract
                    else None,
                    "fulltext_available": bool(metadata.get("fulltext")),
                    "blind_id": blind_id,
                }
                call["papers"].append(paper)
                private_packet["items"].append(
                    {
                        "blind_id": blind_id,
                        "draft": draft,
                        "abstract": abstract,
                        "label": None,
                        "rationale": None,
                    }
                )
            try:
                call["trace"] = _trace_evidence(
                    _trace_path(cache_root, run_id, run_id), run_id, expected_build_id
                )
            except Exception as exc:
                call["trace_error"] = type(exc).__name__
                if error is None:
                    error = exc
            call["target_in_first_three"] = any(
                paper["pmid"] == str(call["target_pmid"] or call["anchor_pmid"])
                for paper in call["papers"]
            )
            if error is None:
                call["classification"] = (
                    "success_nonempty" if papers else "success_empty"
                )
            else:
                status, retry_after, limited = _error_metadata(error)
                call["classification"] = (
                    "rate_limited" if limited else "retrieval_error"
                )
                call["exception_type"] = type(error).__name__
                call["upstream_http_status"] = status
                call["retry_after"] = retry_after
            report["calls"].append(call)
            _write_json(result_path, report)
            secrets.SystemRandom().shuffle(private_packet["items"])
            _write_json(private_path, private_packet, private=True)
            if error is not None:
                report["status"] = (
                    "INCOMPLETE_RATE_LIMIT"
                    if call["classification"] == "rate_limited"
                    else "INCOMPLETE_ERROR"
                )
                _write_json(result_path, report)
                return report

    report["status"] = "SCREEN_COMPLETE_LABELS_PENDING"
    report["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["private_label_packet"] = str(private_path)
    _write_json(result_path, report)
    private_packet["items"].sort(key=lambda item: item["blind_id"])
    _write_json(private_path, private_packet, private=True)
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank-version", type=int, choices=tuple(BANKS), default=1)
    return parser.parse_args(argv)


async def _main(bank_version: int | None = None) -> int:
    bank_version = _parse_args().bank_version if bank_version is None else bank_version
    prereg = _load_preregistration(bank_version)
    endpoint, cache_root, expected_build = _check_runtime(
        prereg, bank_version=bank_version
    )
    output_path, private_path = _new_output_paths(bank_version)
    if output_path.exists() or private_path.exists():
        raise ValueError("Unique screen output path already exists")
    registry = ToolRegistry(
        config_path=str(ROOT / TOOL_CONFIG),
        skip_user_config=True,
    )
    client = MCPToolClient(server_url=endpoint)
    await client.initialize()
    report = await _screen(
        prereg,
        registry,
        client,
        cache_root,
        output_path,
        private_path,
        expected_build_id=expected_build,
        bank_version=bank_version,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "calls": len(report["calls"]),
                "result": str(output_path),
                "private_label_packet": str(private_path),
            }
        )
    )
    return 0 if report["status"] == "SCREEN_COMPLETE_LABELS_PENDING" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
