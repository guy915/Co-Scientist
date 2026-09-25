"""Run the frozen, keyless M11 precise-rung paired PubMed pilot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
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
INDEPENDENT_PREREG = HERE / "novelty-precise-rung-01b2b-independent-prereg-v1.json"
INDEPENDENT_PREREG_SHA256 = (
    "dec79fbe21bec82ee6535cc711cc66b2f37da61d5ef79a2eb4c0f7c2e8b8b3e8"
)
INDEPENDENT_INPUT = HERE / "novelty-precise-rung-01b2b-independent-input-v1.json"
INDEPENDENT_INPUT_SHA256 = (
    "a51c88afd45a81b84b614e730f0459f5e6bb567c3c37958982312106a50781c0"
)
INDEPENDENT_AMENDMENT = (
    HERE / "novelty-precise-rung-01b2b-protocol-amendment-2026-09-25.json"
)
LIFECYCLE_DRIVER = HERE / "novelty_precise_rung_lifecycle_driver.py"
LIFECYCLE_DRIVER_RELPATH = (
    "references/external/sakana/novelty_precise_rung_lifecycle_driver.py"
)
CASE_CONTEXT_RELPATH = "references/external/sakana/novelty-precise-rung-01b2b-independent-case-context-2026-09-25.json"
CASE_CONTEXT_PROTOCOL = "novelty-precise-rung-independent-query-context-v1"
RUNNER_RELPATH = "references/external/sakana/novelty_precise_rung_runner.py"
BASELINE_COMMIT = "1ce3992ce0950b45979f7325fd66f7383f41afa0"
MAX_OUTER_CALLS = 12
INDEPENDENT_MAX_OUTER_CALLS = 8
MAX_RUNG_CALLS = 3
MAX_ESEARCH_CALLS = 36
INDEPENDENT_MAX_ESEARCH_CALLS = 24
MAX_IDS_PER_CALL = 9
MAX_PAPERS = 3
MIN_CALL_INTERVAL_SECONDS = 2.0
INDEPENDENT_PILOT_ID = "m11novrung01b2bindependentv1"
INDEPENDENT_PROTOCOL_ID = "M11-NOV-RUNG-01b2b-independent-v1"
SERVER_LAUNCHER = HERE / "novelty_precise_rung_server_launcher.py"
SERVER_LAUNCHER_RELPATH = (
    "references/external/sakana/novelty_precise_rung_server_launcher.py"
)
RUNTIME_SUPPORT_TREE = ROOT / "engine/src/co_scientist"
SHARED_PILOT_SOURCE = HERE / "novelty_sort_pilot.py"
ENGINE_PROJECT_SOURCE = ROOT / "engine/pyproject.toml"
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


def _save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _discard_empty(paths: list[Path]) -> None:
    for path in paths:
        if path.is_file() and not path.is_symlink() and path.stat().st_size == 0:
            path.unlink()


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
    case_context_items: list[dict[str, str]] = field(default_factory=list)
    case_ids: set[str] = field(default_factory=set)
    request_by_id: dict[str, Request] = field(default_factory=lambda: REQUEST_BY_ID)
    call_order: tuple[tuple[str, str], ...] = CALL_ORDER
    preregistered_slugs: dict[tuple[str, str], str] = field(default_factory=dict)
    max_outer_calls: int = MAX_OUTER_CALLS
    max_esearch_calls: int = MAX_ESEARCH_CALLS
    max_metadata_ids: int = MAX_OUTER_CALLS * MAX_IDS_PER_CALL
    pilot_label: str = "M11-NOV-RUNG-01a"
    protocol: str = "original"


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


def _require_committed_clean(path: Path, label: str) -> None:
    relative = path.resolve().relative_to(ROOT).as_posix()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--", relative],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if tracked.returncode or changed.returncode or changed.stdout.strip():
        raise ValueError(f"Independent {label} must be committed and clean")


def _validate_runtime_support(pins: Any) -> None:
    sources = (
        ("engine_source_tree_sha256", RUNTIME_SUPPORT_TREE, True),
        ("shared_pilot_sha256", SHARED_PILOT_SOURCE, False),
        ("engine_project_sha256", ENGINE_PROJECT_SOURCE, False),
    )
    if not isinstance(pins, dict) or set(pins) != {item[0] for item in sources}:
        raise ValueError("Independent runtime support pins are incomplete")
    for key, path, is_tree in sources:
        _require_committed_clean(path, "runtime support")
        actual = _tree_sha256(_tree_files(path)) if is_tree else _sha256_file(path)
        if pins[key] != actual:
            raise ValueError("Independent runtime support differs from amendment")


def _attest_builds(
    args: argparse.Namespace,
    pins: dict[str, tuple[str, str]],
    candidate_diff_sha256: str,
) -> dict[str, Any]:
    roots = {
        name: Path(getattr(args, f"{name}_root")).expanduser().resolve()
        for name in pins
    }
    files = {
        name: _tree_files(root / "engine/mcp_server") for name, root in roots.items()
    }
    commits = {name: _commit(root) for name, root in roots.items()}
    trees = {name: _tree_sha256(files[name]) for name in files}
    for name, (commit_pin, tree_pin) in pins.items():
        if commits[name] != commit_pin:
            raise ValueError(f"{name.title()} process commit differs from its pin")
        if trees[name] != tree_pin:
            raise ValueError(f"{name.title()} source tree differs from its pin")
    diff_sha, changed_files = _candidate_diff(
        roots["candidate"], commits["baseline"], commits["candidate"]
    )
    if diff_sha != candidate_diff_sha256:
        raise ValueError("Candidate runtime diff differs from its pin")
    return {
        "baseline": trees["baseline"],
        "candidate": trees["candidate"],
        "candidate_diff_sha256": diff_sha,
        "candidate_changed_files": list(changed_files),
    }


def _field_mismatches(value: Any, expected: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return ["receipt"]
    return [field for field, pin in expected.items() if value.get(field) != pin]


def _require_pins(value: Any, expected: dict[str, Any], label: str) -> None:
    mismatches = _field_mismatches(value, expected)
    if mismatches:
        raise ValueError(f"{label} pins mismatch: {mismatches}")


def _original_protocol(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    _require_pins(
        amendment,
        {
            "status": "authorized_for_retrieval",
            "live_retrieval_authorized": True,
            "prereg_sha256": prereg_digest,
            "corrected_frozen_inputs_sha256": frozen_inputs_digest,
            "corrected_source_manifest_sha256": source_manifest_digest,
            "baseline_commit": BASELINE_COMMIT,
            "runner_path": RUNNER_RELPATH,
            "runner_sha256": _sha256_file(Path(__file__).resolve()),
        },
        "Protocol amendment",
    )

    builds = _attest_builds(
        args,
        {
            "baseline": (BASELINE_COMMIT, amendment["baseline_tree_sha256"]),
            "candidate": (
                amendment["candidate_commit"],
                amendment["candidate_tree_sha256"],
            ),
        },
        candidate_diff_sha256=amendment["candidate_diff_sha256"],
    )

    return amendment, builds | {
        "frozen_inputs_sha256": frozen_inputs_digest,
        "source_manifest_sha256": source_manifest_digest,
    }


def _independent_schedule(
    runner_inputs: dict[str, Any],
) -> tuple[dict[str, Request], tuple[tuple[str, str], ...]]:
    run_paths = runner_inputs.get("run_artifact_paths")
    if not isinstance(run_paths, dict):
        raise ValueError("Independent run artifact paths are missing")
    pilot_id = run_paths.get("pilot_run_id")
    template = f"{pilot_id}_{{request_id_lower}}_{{arm}}"
    if (
        pilot_id != INDEPENDENT_PILOT_ID
        or run_paths.get("per_call_run_id_template") != template
        or run_paths.get("per_call_slug_template") != template
    ):
        raise ValueError(
            "Independent run ID and slug template must match preregistration"
        )
    inputs = runner_inputs.get("request_inputs")
    expected_ids = ("R03", "R04", "R05", "R06")
    if (
        not isinstance(inputs, list)
        or tuple(row.get("request_id") for row in inputs if isinstance(row, dict))
        != expected_ids
    ):
        raise ValueError("Independent preregistration must contain only R03-R06")
    requests = {
        row["request_id"]: Request(row["request_id"], row["exact_query"])
        for row in inputs
    }
    schedule = runner_inputs.get("paired_call_order")
    if not isinstance(schedule, list):
        raise ValueError("Independent paired call schedule is missing")
    call_order = tuple(
        (row.get("request_id"), row.get("arm"))
        for row in schedule
        if isinstance(row, dict)
    )
    expected_order = tuple(
        (request_id, arm)
        for request_id in expected_ids
        for arm in ("baseline", "candidate")
    )
    if (
        len(call_order) != len(schedule)
        or call_order != expected_order
        or any(row.get("order") != index for index, row in enumerate(schedule, 1))
    ):
        raise ValueError("Independent paired call order must be exactly R03-R06")
    return requests, call_order


def _validate_lifecycle_driver(pinned: Any) -> str:
    if not isinstance(pinned, dict) or set(pinned) != {
        "driver_path",
        "driver_sha256",
        "launcher_path",
        "launcher_sha256",
        "baseline",
        "candidate",
    }:
        raise ValueError(
            "Independent amendment must pin driver, launcher, and receipts"
        )
    driver = LIFECYCLE_DRIVER.resolve()
    digest = pinned.get("driver_sha256")
    if (
        pinned.get("driver_path") != LIFECYCLE_DRIVER_RELPATH
        or not driver.is_file()
        or driver.is_symlink()
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or _sha256_file(driver) != digest
    ):
        raise ValueError("Independent lifecycle-driver hash does not match amendment")

    parent_pid = os.getppid()
    if os.getenv("COSCIENTIST_M11_RUNG_LIFECYCLE_PARENT_PID") != str(parent_pid):
        raise ValueError("Independent runner must be a direct lifecycle-driver child")
    if os.getenv("COSCIENTIST_M11_RUNG_LIFECYCLE_DRIVER_PATH") != str(driver):
        raise ValueError("Independent lifecycle-driver path environment is missing")
    nonce = os.getenv("COSCIENTIST_M11_RUNG_LIFECYCLE_INVOCATION_NONCE", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", nonce):
        raise ValueError("Independent lifecycle invocation nonce is missing")
    process = subprocess.run(
        ["ps", "-p", str(parent_pid), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if process.returncode or str(driver) not in shlex.split(process.stdout.strip()):
        raise ValueError("Independent runner parent is not the pinned lifecycle driver")
    return digest


def _independent_protocol(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not INDEPENDENT_PREREG.is_file() or INDEPENDENT_PREREG.is_symlink():
        raise ValueError("Independent preregistration is missing")
    prereg_digest = _sha256_file(INDEPENDENT_PREREG)
    if prereg_digest != INDEPENDENT_PREREG_SHA256:
        raise ValueError("Independent preregistration changed")
    if not INDEPENDENT_INPUT.is_file() or INDEPENDENT_INPUT.is_symlink():
        raise ValueError("Key-free independent runner-input artifact is missing")
    runner_input_sha256 = _sha256_file(INDEPENDENT_INPUT)
    if runner_input_sha256 != INDEPENDENT_INPUT_SHA256:
        raise ValueError("Key-free independent runner-input artifact changed")
    runner_inputs = json.loads(INDEPENDENT_INPUT.read_text(encoding="utf-8"))
    if (
        runner_inputs.get("input_artifact_id")
        != "M11-NOV-RUNG-01b2b-independent-input-v1"
        or runner_inputs.get("version") != 1
        or runner_inputs.get("status")
        != "runner_inputs_only_not_execution_authorization"
    ):
        raise ValueError("Independent runner-input identity or status changed")

    hashes = runner_inputs["source_hash_pins"]
    if hashes["source_preregistration_sha256"] != PREREG_SHA256:
        raise ValueError("Source preregistration is not the pinned original")
    for path_value, expected, label in (
        (
            hashes["source_preregistration_path"],
            hashes["source_preregistration_sha256"],
            "Source preregistration",
        ),
        (
            hashes["candidate_build_evidence_path"],
            hashes["candidate_build_evidence_sha256"],
            "Candidate-build evidence",
        ),
    ):
        path = ROOT / path_value
        if (
            path.parent.resolve() != HERE.resolve()
            or not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != expected
        ):
            raise ValueError(f"{label} is missing or changed")
    requests, scheduled = _independent_schedule(runner_inputs)
    input_digest = _canonical_json_sha256(runner_inputs["request_inputs"])
    source_digest = hashes["source_evidence_canonical_sha256"]
    pair_digest = hashes["pair_definitions_canonical_sha256"]
    if input_digest != hashes["request_inputs_canonical_sha256"]:
        raise ValueError("Independent runner inputs or digest pins changed")

    pin = runner_inputs["source_and_build_pins"]
    baseline_pin, candidate_pin = pin["baseline"], pin["candidate"]

    if not INDEPENDENT_AMENDMENT.is_file() or INDEPENDENT_AMENDMENT.is_symlink():
        raise ValueError("Independent amendment is missing; retrieval is closed")
    for path, label in (
        (INDEPENDENT_PREREG, "preregistration"),
        (INDEPENDENT_INPUT, "runner-input artifact"),
        (SERVER_LAUNCHER, "launcher"),
        (LIFECYCLE_DRIVER, "lifecycle driver"),
        (Path(__file__).resolve(), "runner"),
        (INDEPENDENT_AMENDMENT, "amendment"),
    ):
        _require_committed_clean(path, label)
    amendment = json.loads(INDEPENDENT_AMENDMENT.read_text(encoding="utf-8"))
    expected_pins = {
        "status": "authorized_for_retrieval",
        "live_retrieval_authorized": True,
        "prereg_sha256": prereg_digest,
        "runner_input_sha256": runner_input_sha256,
        "source_prereg_sha256": hashes["source_preregistration_sha256"],
        "request_inputs_sha256": input_digest,
        "source_evidence_sha256": source_digest,
        "pair_definitions_sha256": pair_digest,
        "baseline_commit": baseline_pin["commit"],
        "baseline_tree_sha256": baseline_pin["mcp_server_tree_sha256"],
        "candidate_commit": candidate_pin["commit"],
        "candidate_tree_sha256": candidate_pin["mcp_server_tree_sha256"],
        "candidate_diff_sha256": candidate_pin["runtime_diff_sha256"],
        "runner_path": RUNNER_RELPATH,
        "runner_sha256": _sha256_file(Path(__file__).resolve()),
        "planned_outer_pubmed_mcp_calls": INDEPENDENT_MAX_OUTER_CALLS,
        "absolute_outer_pubmed_mcp_call_cap": 12,
        "max_esearch_calls": INDEPENDENT_MAX_ESEARCH_CALLS,
        "retry_or_recovery_calls": 0,
        "result_path": runner_inputs["run_artifact_paths"]["result_path"],
        "blind_review_path": runner_inputs["run_artifact_paths"]["blind_review_path"],
        "case_context_path": CASE_CONTEXT_RELPATH,
        "case_context_protocol": CASE_CONTEXT_PROTOCOL,
    }
    _require_pins(amendment, expected_pins, "Independent amendment")
    _validate_runtime_support(amendment.get("runtime_support"))
    _validate_lifecycle_driver(amendment["trace_preflight"])

    builds = _attest_builds(
        args,
        {
            "baseline": (
                baseline_pin["commit"],
                baseline_pin["mcp_server_tree_sha256"],
            ),
            "candidate": (
                candidate_pin["commit"],
                candidate_pin["mcp_server_tree_sha256"],
            ),
        },
        candidate_diff_sha256=candidate_pin["runtime_diff_sha256"],
    )

    return amendment, {
        "protocol": "independent",
        "protocol_id": "M11-NOV-RUNG-01b2b-independent-v1",
        "pilot_id": runner_inputs["run_artifact_paths"]["pilot_run_id"],
        "preregistered_slugs": {
            (request_id, arm): _call_slug(
                "independent",
                runner_inputs["run_artifact_paths"]["pilot_run_id"],
                request_id,
                arm,
            )
            for request_id, arm in scheduled
        },
        "request_by_id": requests,
        "call_order": scheduled,
        "max_outer_calls": INDEPENDENT_MAX_OUTER_CALLS,
        "max_esearch_calls": INDEPENDENT_MAX_ESEARCH_CALLS,
        "max_metadata_ids": INDEPENDENT_MAX_OUTER_CALLS * MAX_IDS_PER_CALL,
        "prereg_sha256": prereg_digest,
        "runner_input_sha256": runner_input_sha256,
        "source_prereg_sha256": hashes["source_preregistration_sha256"],
        "frozen_inputs_sha256": input_digest,
        "source_manifest_sha256": source_digest,
        "pair_definitions_sha256": pair_digest,
        "amendment_path": INDEPENDENT_AMENDMENT,
        "result_path": runner_inputs["run_artifact_paths"]["result_path"],
        "blind_review_path": runner_inputs["run_artifact_paths"]["blind_review_path"],
        "case_context_path": amendment["case_context_path"],
        "case_context_protocol": amendment["case_context_protocol"],
        "trace_preflight": amendment["trace_preflight"],
        **builds,
    }


def _protocol(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = getattr(args, "protocol", "original")
    if protocol == "original":
        return _original_protocol(args)
    if protocol == "independent":
        return _independent_protocol(args)
    raise ValueError("Unknown retrieval protocol")


def _call_slug(protocol: str, pilot_id: str, request_id: str, arm: str) -> str:
    suffix = f"{request_id.lower()}_{arm}"
    if protocol == "independent":
        return f"{pilot_id}_{suffix}"
    return f"m11novrung_{pilot_id}_{suffix}"


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


def _validate_launcher_receipts(
    args: argparse.Namespace,
    arms: dict[str, Arm],
    pinned: Any,
) -> dict[str, str]:
    if not isinstance(pinned, dict) or set(pinned) != {
        "driver_path",
        "driver_sha256",
        "launcher_path",
        "launcher_sha256",
        "baseline",
        "candidate",
    }:
        raise ValueError(
            "Independent amendment must pin the launcher and both receipts"
        )
    launcher = SERVER_LAUNCHER.resolve()
    if (
        pinned["launcher_path"] != SERVER_LAUNCHER_RELPATH
        or not launcher.is_file()
        or launcher.is_symlink()
        or _sha256_file(launcher) != pinned["launcher_sha256"]
    ):
        raise ValueError("Independent launcher hash does not match the amendment")

    receipt_hashes: dict[str, str] = {}
    for name, arm in arms.items():
        pin = pinned[name]
        receipt_arg = getattr(args, f"{name}_launch_receipt", None)
        if not isinstance(pin, dict) or set(pin) != {"receipt_path", "receipt_sha256"}:
            raise ValueError(f"{name} launch receipt is not pinned")
        if not receipt_arg:
            raise ValueError(f"{name} launch receipt is required")
        receipt_path = Path(receipt_arg).expanduser().resolve()
        if (
            str(receipt_path) != pin["receipt_path"]
            or not receipt_path.is_file()
            or receipt_path.is_symlink()
        ):
            raise ValueError(f"{name} launch receipt path is missing or changed")
        receipt_hash = _sha256_file(receipt_path)
        if receipt_hash != pin["receipt_sha256"]:
            raise ValueError(f"{name} launch receipt hash differs from the amendment")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected = {
            "schema_version": "novelty_precise_rung_launcher_receipt_v1",
            "status": "passed",
            "launcher_path": SERVER_LAUNCHER_RELPATH,
            "launcher_sha256": pinned["launcher_sha256"],
            "source_root": str(arm.root),
            "source_tree_sha256": arm.tree_sha256,
            "serving_pid": arm.pid,
            "bind_host": "127.0.0.1",
            "bind_port": arm.port,
            "max_workers": 1,
            "reload": False,
            "cache_root": str(arm.cache),
            "trace_enabled": True,
            "credential_env_names": [MCP_SECRET],
            "secret_env_name": MCP_SECRET,
            "secret_free": True,
            "entrez": {
                "max_tries": 1,
                "sleep_between_tries": 0,
                "api_key_absent": True,
            },
        }
        mismatches = _field_mismatches(receipt, expected)
        secret_length = (
            receipt.get("secret_length") if isinstance(receipt, dict) else None
        )
        if mismatches or not isinstance(secret_length, int) or secret_length < 32:
            raise ValueError(
                f"{name} launcher receipt process pins mismatch: {mismatches or ['secret_length']}"
            )

        probe_id = f"m11_launcher_probe_{arm.pid}"
        trace_path = (
            arm.cache / "pubmed" / probe_id / "runs" / probe_id / ".search-trace.json"
        )
        trace = receipt.get("maintained_trace")
        if not isinstance(trace, dict):
            raise ValueError(f"{name} maintained-trace receipt is missing")
        selected_ids = trace.get("selected_ids")
        final_ids = trace.get("final_ids")
        trace_pins = {
            "enabled": True,
            "run_id": probe_id,
            "slug": probe_id,
            "path": str(trace_path),
            "source_file_path": str(arm.source_file),
            "server_build_id": arm.build_id,
            "process_id": arm.pid,
            "sort": arm.sort,
            "manifest_run_id": probe_id,
            "validated": True,
            "readiness_artifacts_removed": True,
            "cache_empty_after_cleanup": True,
            "fake_entrez_calls": {"esearch": 1, "efetch": 6, "elink": 3},
        }
        if (
            _field_mismatches(trace, trace_pins)
            or not re.fullmatch(r"[0-9a-f]{64}", str(trace.get("sha256", "")))
            or not isinstance(selected_ids, list)
            or not selected_ids
            or len(selected_ids) > MAX_IDS_PER_CALL
            or any(not isinstance(pmid, str) for pmid in selected_ids)
            or not isinstance(final_ids, list)
            or not final_ids
            or len(final_ids) > MAX_PAPERS
            or any(pmid not in selected_ids for pmid in final_ids)
            or trace.get("manifest_ids") != final_ids
        ):
            raise ValueError(
                f"{name} maintained trace does not match its process/cache"
            )

        transient = receipt.get("transient_probe")
        if _field_mismatches(
            transient,
            {
                "patch_target": "Bio.Entrez.urlopen",
                "injected_status": 503,
                "underlying_attempts": 1,
                "external_traffic": False,
                "restored": True,
            },
        ):
            raise ValueError(
                f"{name} receipt does not prove exactly one offline transient attempt"
            )
        receipt_hashes[name] = receipt_hash
    return receipt_hashes


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
    context = (
        (ROOT / hashes["case_context_path"]).resolve()
        if hashes.get("protocol") == "independent"
        else None
    )
    artifact_paths = (output, blind, *((context,) if context is not None else ()))
    if len(set(artifact_paths)) != len(artifact_paths) or any(
        path.exists() for path in artifact_paths
    ):
        raise ValueError("Result artifacts must use new unique paths")
    if any(
        path == arm.cache or arm.cache in path.parents or path in arm.cache.parents
        for path in artifact_paths
        for arm in arms.values()
    ):
        raise ValueError("Artifacts must be outside both server caches")
    trace_receipt_hashes: dict[str, str] = {}
    if getattr(args, "protocol", "original") == "independent":
        if (
            output != (ROOT / hashes["result_path"]).resolve()
            or blind != (ROOT / hashes["blind_review_path"]).resolve()
            or context != (ROOT / CASE_CONTEXT_RELPATH).resolve()
            or hashes.get("case_context_protocol") != CASE_CONTEXT_PROTOCOL
        ):
            raise ValueError(
                "Independent artifact paths/protocol differ from amendment"
            )
        trace_receipt_hashes = _validate_launcher_receipts(
            args, arms, hashes["trace_preflight"]
        )
        receipt_paths = {
            Path(getattr(args, f"{name}_launch_receipt")).expanduser().resolve()
            for name in arms
        }
        if len(receipt_paths) != len(arms):
            raise ValueError("Each independent arm needs its own launch receipt")
        if any(
            path == arm.cache or arm.cache in path.parents or path in arm.cache.parents
            for path in receipt_paths
            for arm in arms.values()
        ):
            raise ValueError("Launch receipts must be outside both server caches")
        if any(path in set(artifact_paths) for path in receipt_paths):
            raise ValueError("Launch receipts must not overlap result artifacts")
        if any(any(arm.cache.iterdir()) for arm in arms.values()):
            raise ValueError("Launcher readiness artifacts remain in a server cache")
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
            **{
                key: value
                for key, value in hashes.items()
                if key
                in {
                    "protocol",
                    "protocol_id",
                    "pilot_id",
                    "request_by_id",
                    "call_order",
                    "max_outer_calls",
                    "max_esearch_calls",
                    "max_metadata_ids",
                    "preregistered_slugs",
                    "prereg_sha256",
                    "runner_input_sha256",
                    "source_prereg_sha256",
                    "pair_definitions_sha256",
                    "amendment_path",
                    "case_context_path",
                    "case_context_protocol",
                }
            },
            **(
                {
                    "trace_preflight_manifest_sha256": {},
                    "trace_preflight_receipt_sha256": trace_receipt_hashes,
                }
                if getattr(args, "protocol", "original") == "independent"
                else {}
            ),
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


def _independent_case_artifacts(
    runtime: Runtime,
    request: Request,
    arm: Arm,
    papers: list[dict[str, Any]],
    blind_items: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    review_by_item = {item.get("item_id"): item for item in blind_items}
    if len(review_by_item) != len(blind_items) or len(papers) != len(blind_items):
        raise ValueError("Independent papers and blind abstracts do not align")
    public_papers: list[dict[str, Any]] = []
    public_items: list[dict[str, str]] = []
    locked_items: list[dict[str, str]] = []
    for paper in papers:
        item_id = paper.get("blind_item_id")
        review = review_by_item.get(item_id)
        if not isinstance(review, dict) or not isinstance(review.get("abstract"), str):
            raise ValueError("Independent paper has no matching blind abstract")
        case_id = secrets.token_urlsafe(18)
        if not case_id or case_id in runtime.case_ids:
            raise ValueError("Independent opaque case ID is empty or duplicated")
        runtime.case_ids.add(case_id)
        public_paper = {
            key: value for key, value in paper.items() if key != "blind_item_id"
        }
        public_paper["case_id"] = case_id
        public_papers.append(public_paper)
        public_items.append({"case_id": case_id, "abstract": review["abstract"]})
        runtime.case_context_items.append({"case_id": case_id, "query": request.query})
        locked_items.append(
            {
                "case_id": case_id,
                "request_id": request.request_id,
                "arm": arm.name,
                "pmid": str(paper["pmid"]),
                "source_title": str(review.get("title", "")),
            }
        )
    return public_papers, public_items, locked_items


async def _execute(
    runtime: Runtime, request: Request, arm: Arm, order: int
) -> dict[str, Any]:
    suffix = f"{request.request_id.lower()}_{arm.name}"
    slug = _call_slug(runtime.protocol, runtime.pilot_id, request.request_id, arm.name)
    if runtime.protocol == "independent":
        preregistered_slug = runtime.preregistered_slugs.get(
            (request.request_id, arm.name)
        )
        if preregistered_slug != slug:
            raise ValueError(
                "Independent call slug differs from preflight preregistration"
            )
        slug = preregistered_slug
    run_id = f"{runtime.pilot_id}_{suffix}"
    namespace = arm.cache / "pubmed" / slug
    if namespace.exists():
        raise ValueError("Request-by-arm cache namespace already exists")
    params = _params(runtime.tool, request, run_id, slug)
    entry = _record(order, request, arm, slug, run_id, params)
    stage = "initialize"
    tool_call_started = False
    verified_rung_count = 0
    try:
        client = await _client(runtime, arm.name)
        stage = "transport"
        entry["started_at_utc"] = _utc_now()
        runtime.last_start = time.monotonic()
        tool_call_started = True
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
        verified_rung_count = len(trace["attempts"])
        runtime.esearch_calls += verified_rung_count
        if runtime.esearch_calls > runtime.max_esearch_calls:
            raise ValueError("Batch exceeded its preregistered ESearch hard bound")
        runtime.metadata_ids += len(trace["fetched"])
        if runtime.metadata_ids > runtime.max_metadata_ids:
            raise ValueError("Batch exceeded its preregistered metadata-ID hard bound")
        if runtime.protocol == "independent":
            stage = "blind"
            papers, blind_items, locked_items = _independent_case_artifacts(
                runtime, request, arm, papers, blind_items
            )
            runtime.blind_items.extend(blind_items)
            entry["locked_case_map"] = locked_items
        entry.update(
            status="complete",
            papers=papers,
            trace=trace,
            esearch_call_count=len(trace["attempts"]),
            metadata_ids_submitted=len(trace["fetched"]),
            finished_at_utc=_utc_now(),
        )
        if runtime.protocol == "independent":
            entry.update(
                external_request_count="unknown",
                verified_esearch_rung_count=verified_rung_count,
            )
        if runtime.protocol == "original":
            runtime.blind_items.extend(blind_items)
    except Exception as exc:
        entry.update(
            status="error",
            error_stage=stage,
            error_class=type(exc).__name__,
        )
        if runtime.protocol == "independent" and tool_call_started:
            entry.update(
                external_request_count="unknown",
                verified_esearch_rung_count=verified_rung_count,
            )
        if stage == "trace" and isinstance(exc, FileNotFoundError):
            entry["missing_trace_path"] = str(trace_path)[:500]
    return entry


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(
    runtime: Runtime,
    report: dict[str, Any],
    output: Path,
    blind_output: Path,
    case_context_output: Path | None = None,
) -> int:
    if len(runtime.call_order) != runtime.max_outer_calls:
        raise ValueError("Preregistered call schedule differs from its hard call bound")
    report["esearch_call_count_scope"] = "verified_trace_only"
    for order, (request_id, arm_name) in enumerate(runtime.call_order, 1):
        if runtime.last_start is not None:
            await asyncio.sleep(
                max(
                    0.0,
                    MIN_CALL_INTERVAL_SECONDS - (time.monotonic() - runtime.last_start),
                )
            )
        active_call = {
            "order": order,
            "request_id": request_id,
            "arm": arm_name,
            "external_request_count": "unknown",
        }
        report["active_call"] = active_call
        _save(output, report)
        interrupted = False
        try:
            entry = await _execute(
                runtime,
                runtime.request_by_id[request_id],
                runtime.arms[arm_name],
                order,
            )
        except (asyncio.CancelledError, KeyboardInterrupt) as exc:
            interrupted = True
            entry = {
                **active_call,
                "status": "error",
                "error_stage": "interrupted",
                "error_class": type(exc).__name__,
            }
            if runtime.protocol == "independent":
                entry["verified_esearch_rung_count"] = 0
        report["calls"].append(entry)
        report["esearch_call_count"] = runtime.esearch_calls
        report["metadata_ids_submitted"] = runtime.metadata_ids
        if not interrupted:
            report.pop("active_call", None)
        _save(output, report)
        if interrupted or entry["status"] == "error":
            stage = "interrupted" if interrupted else entry["error_stage"]
            report.update(
                status="STOPPED",
                stopped_at_order=order,
                error={"stage": stage, "class": entry["error_class"]},
                ended_at_utc=_utc_now(),
            )
            _save(output, report)
            _discard_empty(
                [blind_output, *([case_context_output] if case_context_output else [])]
            )
            return 1
    secrets.SystemRandom().shuffle(runtime.blind_items)
    _save(
        blind_output,
        {
            "protocol": f"{runtime.pilot_label} blinded relevance batch",
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
    if runtime.protocol == "independent":
        if case_context_output is None:
            raise ValueError("Independent query-context output path is required")
        context = {
            "protocol": CASE_CONTEXT_PROTOCOL,
            "result_sha256": _sha256_file(output),
            "blind_review_sha256": _sha256_file(blind_output),
            "items": runtime.case_context_items,
        }
        _save(case_context_output, context)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", choices=("original", "independent"), default="original"
    )
    for name in EXPECTED_SORT:
        parser.add_argument(f"--{name}-url", required=True)
        parser.add_argument(f"--{name}-root", required=True)
        parser.add_argument(f"--{name}-cache", required=True)
        parser.add_argument(f"--{name}-pid", required=True, type=int)
        parser.add_argument(f"--{name}-launch-receipt")
    parser.add_argument("--output", required=True)
    parser.add_argument("--blind-output")
    return parser


def _persist_stopped(
    output: Path | None,
    exc: BaseException,
    stage: str,
    *,
    initialize_if_empty: bool = False,
) -> None:
    if output is None or not output.is_file():
        return
    try:
        if initialize_if_empty and output.stat().st_size == 0:
            _save(
                output,
                {
                    "status": "STOPPED",
                    "error": {"stage": stage, "class": type(exc).__name__},
                    "ended_at_utc": _utc_now(),
                    "calls": [],
                    "model_inference_calls": 0,
                    "paid_calls": 0,
                },
            )
            return
        report = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            return
        active = report.get("active_call")
        if isinstance(active, dict):
            calls = report.setdefault("calls", [])
            if not any(row.get("order") == active.get("order") for row in calls):
                interrupted = {
                    **active,
                    "status": "error",
                    "error_stage": stage,
                    "error_class": type(exc).__name__,
                }
                if report.get("protocol") == "independent":
                    interrupted.update(
                        external_request_count="unknown",
                        verified_esearch_rung_count=0,
                    )
                calls.append(interrupted)
        report.update(
            status="STOPPED",
            error={"stage": stage, "class": type(exc).__name__},
            ended_at_utc=_utc_now(),
        )
        _save(output, report)
    except (OSError, json.JSONDecodeError, TypeError):
        return


def _persist_preflight_failure(args: argparse.Namespace, exc: Exception) -> None:
    if args.protocol != "independent" or not INDEPENDENT_AMENDMENT.is_file():
        return
    output = Path(args.output).expanduser().absolute()
    try:
        _reserve(output)
        _save(
            output,
            {
                "pilot": INDEPENDENT_PROTOCOL_ID,
                "status": "STOPPED",
                "error": {"stage": "preflight", "class": type(exc).__name__},
                "ended_at_utc": _utc_now(),
                "calls": [],
                "model_inference_calls": 0,
                "paid_calls": 0,
            },
        )
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output: Path | None = None
    blind: Path | None = None
    context_output: Path | None = None
    reserved_paths: list[Path] = []
    report_reservations_complete = False
    try:
        arms, output, blind, hashes = _preflight(args)
        protocol = hashes.get("protocol", "original")
        context_output = (
            (ROOT / hashes["case_context_path"]).resolve()
            if protocol == "independent"
            else None
        )
        paths_to_reserve = [output, blind]
        if context_output is not None:
            paths_to_reserve.append(context_output)
        for path in paths_to_reserve:
            _reserve(path)
            reserved_paths.append(path)
        report_reservations_complete = True
        amendment_path = hashes.get("amendment_path", AMENDMENT)
        pilot_id = hashes.get("pilot_id", uuid.uuid4().hex[:12])
        pilot_label = hashes.get("protocol_id", "M11-NOV-RUNG-01a")
        max_outer_calls = hashes.get("max_outer_calls", MAX_OUTER_CALLS)
        max_esearch_calls = hashes.get("max_esearch_calls", MAX_ESEARCH_CALLS)
        report: dict[str, Any] = {
            "pilot": pilot_label,
            "pilot_run_id": pilot_id,
            "status": "RUNNING",
            "started_at_utc": _utc_now(),
            "prereg_sha256": hashes.get("prereg_sha256", PREREG_SHA256),
            "frozen_inputs_sha256": hashes["frozen_inputs_sha256"],
            "source_manifest_sha256": hashes["source_manifest_sha256"],
            "protocol_amendment_sha256": _sha256_file(amendment_path),
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
            "max_outer_calls": max_outer_calls,
            "max_esearch_calls": max_esearch_calls,
            "esearch_call_count": 0,
            "esearch_call_count_scope": "verified_trace_only",
            "calls": [],
        }
        if protocol == "independent":
            report.update(
                protocol=protocol,
                case_context_path=str(context_output),
                case_context_protocol=hashes["case_context_protocol"],
                absolute_outer_pubmed_mcp_call_cap=12,
                max_metadata_ids=hashes["max_metadata_ids"],
                retry_or_recovery_calls=0,
                runner_input_sha256=hashes["runner_input_sha256"],
                source_prereg_sha256=hashes["source_prereg_sha256"],
            )
        if "pair_definitions_sha256" in hashes:
            report["pair_definitions_sha256"] = hashes["pair_definitions_sha256"]
        if "trace_preflight_manifest_sha256" in hashes:
            report["trace_preflight_manifest_sha256"] = hashes[
                "trace_preflight_manifest_sha256"
            ]
        if "trace_preflight_receipt_sha256" in hashes:
            report["trace_preflight_receipt_sha256"] = hashes[
                "trace_preflight_receipt_sha256"
            ]
        _save(output, report)
        registry = ToolRegistry(
            config_path=str(ROOT / "engine/src/co_scientist/config/tools.yaml"),
            skip_user_config=True,
        )
        tool = registry.get_tool("pubmed_fulltext")
        if tool is None or tool.mcp_tool_name != "pubmed_search_with_fulltext":
            raise ValueError("Maintained PubMed ToolConfig is unavailable")
        runtime = Runtime(
            arms,
            tool,
            pilot_id,
            ResponseParser(tool),
            request_by_id=hashes.get("request_by_id", REQUEST_BY_ID),
            call_order=hashes.get("call_order", CALL_ORDER),
            preregistered_slugs=hashes.get("preregistered_slugs", {}),
            max_outer_calls=max_outer_calls,
            max_esearch_calls=max_esearch_calls,
            max_metadata_ids=hashes.get(
                "max_metadata_ids", MAX_OUTER_CALLS * MAX_IDS_PER_CALL
            ),
            pilot_label=pilot_label,
            protocol=protocol,
        )
        result = asyncio.run(
            _run(runtime, report, output, blind, case_context_output=context_output)
        )
        _discard_empty(
            [blind, *([context_output] if context_output is not None else [])]
        )
        return result
    except (KeyboardInterrupt, asyncio.CancelledError) as exc:
        print(f"Pilot stopped: {type(exc).__name__}", file=sys.stderr)
        if output in reserved_paths:
            _persist_stopped(
                output,
                exc,
                "interrupted",
                initialize_if_empty=report_reservations_complete,
            )
        _discard_empty([path for path in reserved_paths if path != output])
        return 2
    except Exception as exc:
        print(f"Pilot stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        if output is None:
            _persist_preflight_failure(args, exc)
        if output in reserved_paths:
            _persist_stopped(
                output,
                exc,
                "runner",
                initialize_if_empty=report_reservations_complete,
            )
        _discard_empty([path for path in reserved_paths if path != output])
        _discard_empty(reserved_paths)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
