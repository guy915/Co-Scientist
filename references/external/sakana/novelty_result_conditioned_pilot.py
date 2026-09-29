"""Run the offline-testable, preregistration-gated paired novelty pilot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import novelty_fixture_bank_screen as fixture
from co_scientist.config.registry import ToolRegistry
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.llm_free_policy import scoped_campaign_mode
from co_scientist.llm_telemetry import scoped_telemetry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = fixture.ROOT
RESULT_DIR = ROOT / "references/external/sakana"
PILOT_PREREG = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v1.json"
TOOL_CONFIG = fixture.TOOL_CONFIG

PAIR_COUNT = 6
DRAFTS_PER_PAIR = 2
MODEL_CALL_LIMIT = 24
OUTER_MCP_CALL_LIMIT = 36
MAX_PAPERS = 3
MAX_QUERY_CHARS = 200
MAX_ATTEMPTS = 1
MODEL_MAX_TOKENS = 1200
MODEL_TEMPERATURE = 0.0
MODEL_REQUEST_CONFIG = {
    "max_attempts": MAX_ATTEMPTS,
    "max_tokens": MODEL_MAX_TOKENS,
    "temperature": MODEL_TEMPERATURE,
    "enable_thinking": False,
    "use_cache": False,
    "max_price": {"prompt": 0, "completion": 0, "request": 0},
}
MODEL_BOUNDARY_FILES = (
    "engine/src/co_scientist/llm_free_catalog.py",
    "engine/src/co_scientist/llm_free_policy.py",
    "engine/src/co_scientist/llm_request.py",
    "engine/src/co_scientist/llm_call.py",
    "engine/src/co_scientist/llm_json_retry.py",
    "engine/src/co_scientist/llm.py",
    "engine/src/co_scientist/llm_telemetry.py",
    "engine/src/co_scientist/llm_gateway_routing.py",
)

QUERY_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_CHARS}
    },
    "additionalProperties": False,
}

STATIC_PROMPT = (
    "Generate one concise PubMed search query for the scientific draft below. "
    "Use the draft alone. Do not add identifiers. Return JSON with one string "
    "field named query, at most 200 characters.\n\nDraft:\n{draft}"
)
CONDITIONED_PROMPT = (
    "Generate one concise PubMed search query for the scientific draft below. "
    "Use only the draft and the supplied first-search titles and abstracts to "
    "choose useful terminology. Do not add or infer publication identifiers. "
    "Return JSON with one string field named query, at most 200 characters."
    "\n\nDraft:\n{draft}\n\nFirst-search titles and abstracts:\n{evidence}"
)
_CREDENTIAL_SUFFIXES = (
    "_API_KEY",
    "_TOKEN",
    "_SECRET",
    "_ACCESS_KEY",
    "_PASSWORD",
    "_PRIVATE_KEY",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_ids(prereg: dict[str, Any]) -> set[str]:
    return {
        str(arm.get("target_pmid", arm.get("anchor_pmid", "")))
        for pair in prereg["cases_in_fixed_order"]
        for arm in (pair["positive"], pair["distinct_control"])
    }


def _contains_source_id(text: str, source_ids: set[str]) -> bool:
    return any(
        re.search(rf"(?<!\d){re.escape(source_id)}(?!\d)", text)
        for source_id in source_ids
    )


def _prompt(
    variant: str, draft: str, papers: list[dict[str, Any]] | None = None
) -> str:
    if variant == "static":
        return STATIC_PROMPT.format(draft=draft)
    evidence = "\n\n".join(
        "Title: "
        + str(paper["title"] or "")
        + "\nAbstract: "
        + str(paper["abstract"] or "")
        for paper in papers or []
    )
    return CONDITIONED_PROMPT.format(draft=draft, evidence=evidence)


def _telemetry_totals(
    snapshot: dict[str, dict[str, Any]],
) -> tuple[str | None, int, int, int]:
    served_models = {key.split("::", 1)[1] for key in snapshot}
    calls = sum(int(stats.get("calls", 0)) for stats in snapshot.values())
    observed = sum(
        int(stats.get("observed_model_calls", 0)) for stats in snapshot.values()
    )
    retries = sum(int(stats.get("retries", 0)) for stats in snapshot.values())
    served = next(iter(served_models)) if len(served_models) == 1 else None
    return served, calls, observed, retries


async def _generate_query(
    prompt: str,
    *,
    model_name: str,
    model_api_key: str,
    run_id: str,
    expected_source_ids: set[str],
    event: dict[str, Any],
) -> str:
    event["started_at_utc"] = _now()
    event["request_config"] = MODEL_REQUEST_CONFIG
    with scoped_telemetry("m11_nov_01a3b3_query") as telemetry:
        try:
            with scoped_campaign_mode(True):
                result = await call_llm_json(
                    prompt,
                    CompletionSpec(
                        model_name=model_name,
                        max_tokens=MODEL_MAX_TOKENS,
                        temperature=MODEL_TEMPERATURE,
                        json_schema=QUERY_SCHEMA,
                        api_key=model_api_key,
                    ),
                    max_attempts=MAX_ATTEMPTS,
                    options=LLMCallOptions(
                        use_cache=False,
                        run_id=run_id,
                        enable_thinking=False,
                    ),
                )
        finally:
            event["telemetry"] = telemetry.snapshot()
    served_model, calls, observed, retries = _telemetry_totals(event["telemetry"])
    event.update(
        {
            "served_model": served_model,
            "provider_calls": calls,
            "observed_model_calls": observed,
            "retries": retries,
            "cache_hits": sum(
                int(stats.get("cache_hits", 0)) for stats in event["telemetry"].values()
            ),
            "ended_at_utc": _now(),
        }
    )
    if calls != 1 or observed != 1 or retries or event["cache_hits"]:
        raise ValueError("Model call lacks one observed uncached provider response")
    if served_model != model_name:
        raise ValueError("Served model differs from the selected zero-price model")
    query = result.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ValueError("Generated query is empty or exceeds 200 characters")
    if _contains_source_id(query, expected_source_ids):
        raise ValueError("Generated query contains a frozen target or anchor PMID")
    return query


async def _search_once(
    query: str,
    *,
    pair_id: str,
    arm: str,
    stage: str,
    registry: ToolRegistry,
    recorder: Any,
    parser: ResponseParser,
    cache_root: Path,
    expected_build_id: str,
    nonce: str,
    outer_call_number: int,
    endpoint: str,
    serving_process: dict[str, Any],
    draft: str,
    draft_id: str,
    source_ids: set[str],
    first_search_event_id: int | None,
    blind_items: list[dict[str, Any]],
    event: dict[str, Any],
) -> list[dict[str, Any]] | None:
    slug = f"m11_nov_01a3b3_{nonce}_{outer_call_number:02d}"
    event.update(
        {
            "kind": "mcp",
            "pair_id": pair_id,
            "draft_id": draft_id,
            "draft": draft,
            "arm": arm,
            "stage": stage,
            "started_at_utc": _now(),
            "papers": [],
        }
    )
    if first_search_event_id is not None:
        event["first_search_event_id"] = first_search_event_id
    context = fixture._NoveltySearchContext(
        mcp_client=recorder,
        tool_registry=registry,
        shared_slug=slug,
        run_id=slug,
    )
    error: Exception | None = None
    papers: dict[str, dict[str, Any]] = {}
    try:
        _require_same_serving_process(
            endpoint, serving_process, cache_root, expected_build_id
        )
        papers = await fixture._search_papers_for_hypothesis(
            query, context, max_papers=MAX_PAPERS
        )
        _require_same_serving_process(
            endpoint, serving_process, cache_root, expected_build_id
        )
        payload_error = fixture._payload_error(recorder.last_response)
        if payload_error is not None:
            raise payload_error
    except Exception as exc:
        error = exc

    event["ended_at_utc"] = _now()
    event["tool"] = recorder.last_tool
    event["wire_parameters"] = recorder.last_params
    try:
        payload = fixture._blank_error_payload(recorder, parser)
    except Exception as exc:
        payload = None
        error = error or exc
    if error is None:
        if not isinstance(payload, dict):
            error = ValueError("Malformed PubMed response payload")
        elif payload and (
            any(
                not str(pmid).isdecimal() or not isinstance(metadata, dict)
                for pmid, metadata in payload.items()
            )
            or not isinstance(papers, dict)
            or {str(pmid) for pmid in papers} != {str(pmid) for pmid in payload}
        ):
            error = ValueError("Malformed nonempty PubMed response payload")
    records = payload if isinstance(payload, dict) else {}
    private_papers: list[dict[str, Any]] = []
    for rank, (paper_id, metadata) in enumerate(papers.items(), start=1):
        raw = records.get(str(paper_id), {})
        abstract = raw.get("abstract", "") if isinstance(raw, dict) else ""
        abstract = abstract if isinstance(abstract, str) else ""
        title = metadata.get("title")
        if _contains_source_id(str(title or ""), source_ids) or _contains_source_id(
            abstract, source_ids
        ):
            error = ValueError("Retrieved paper text contains a frozen source PMID")
            event["source_text_leak_pmid"] = str(paper_id)
            break
        blind_id = uuid.uuid4().hex
        event["papers"].append(
            {
                "rank": rank,
                "pmid": str(paper_id),
                "title": title,
                "authors": metadata.get("authors", []),
                "year": metadata.get("year"),
                "doi": raw.get("doi") if isinstance(raw, dict) else None,
                "abstract_available": bool(abstract.strip()),
                "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest()
                if abstract
                else None,
                "fulltext_available": bool(metadata.get("fulltext")),
                "blind_id": blind_id,
            }
        )
        private_papers.append(
            {
                "pmid": str(paper_id),
                "title": title,
                "abstract": abstract,
                "rank": rank,
            }
        )
        blind_items.append(
            {
                "blind_id": blind_id,
                "draft": draft,
                "title": title,
                "abstract": abstract,
                "label": None,
                "rationale": None,
            }
        )
    try:
        event["trace"] = fixture._trace_evidence(
            fixture._trace_path(cache_root, slug, slug), slug, expected_build_id
        )
        event["trace"]["serving_process"] = serving_process
        selected = event["trace"].get("selected") or {}
        if (
            len(event["trace"].get("attempts", [])) > 3
            or len(event["trace"].get("fetched", [])) > 9
            or len(selected.get("ids", [])) > 9
        ):
            raise ValueError("Maintained PubMed trace exceeds the pilot rung/ID bound")
    except Exception as exc:
        error = error or exc
        event["trace_error"] = type(exc).__name__
    event["classification"] = (
        "success_nonempty" if error is None and papers else "success_empty"
    )
    if error is not None:
        status, retry_after, limited = fixture._error_metadata(error)
        event.update(
            {
                "classification": "rate_limited" if limited else "retrieval_error",
                "exception_type": type(error).__name__,
                "upstream_http_status": status,
                "retry_after": retry_after,
            }
        )
        return None
    return private_papers


async def run_pilot(
    fixture_prereg: dict[str, Any],
    registry: ToolRegistry,
    client: Any,
    cache_root: Path,
    result_path: Path,
    blind_path: Path,
    *,
    expected_build_id: str,
    model_name: str,
    model_api_key: str,
) -> dict[str, Any]:
    """Run all six frozen pairs using the maintained search and LLM seams."""
    protocol = _load_pilot_protocol()
    if model_name != protocol["model_name"]:
        raise ValueError("Selected model differs from the committed pilot protocol")
    if expected_build_id != protocol.get("mcp_build_id"):
        raise ValueError("MCP build ID differs from the committed pilot protocol")
    endpoint, checked_cache, checked_build_id, serving_process = _check_runtime(
        protocol, fixture_prereg, cache_root=cache_root
    )
    if checked_cache.resolve() != cache_root.resolve():
        raise ValueError("Pilot runtime changed the isolated cache root")
    if checked_build_id != expected_build_id:
        raise ValueError("MCP build ID differs from the checked runtime")
    if getattr(client, "server_url", None) != endpoint:
        raise ValueError("Pilot MCP client differs from the attested endpoint")
    if result_path.exists() or blind_path.exists():
        raise ValueError("Pilot outputs already exist; never overwrite a prior run")
    if cache_root.is_symlink() or not cache_root.is_absolute():
        raise ValueError("Pilot cache must be absolute and not a symlink")
    if not cache_root.is_dir() or any(cache_root.iterdir()):
        raise ValueError("Pilot cache must exist and start empty")
    if fixture_prereg != fixture._load_preregistration(1):
        raise ValueError("Pilot must use the complete frozen v1 fixture bank")
    pairs = fixture_prereg["cases_in_fixed_order"]
    if len(pairs) != PAIR_COUNT:
        raise ValueError("Pilot requires every pair from the frozen v1 bank")
    if not model_name or not model_api_key:
        raise ValueError("A selected model and explicit model API key are required")
    tool_id, tool = fixture._find_search_tool(registry)
    if tool_id != "pubmed_fulltext" or not tool:
        raise ValueError("Configured PubMed validation tool is unavailable")
    if tool.mcp_tool_name != "pubmed_search_with_fulltext":
        raise ValueError("Configured PubMed validation tool differs from the pilot")

    source_ids = _source_ids(fixture_prereg)
    for pair in pairs:
        for arm in ("positive", "distinct_control"):
            draft = pair[arm]["draft"]
            if len(draft) > MAX_QUERY_CHARS or _contains_source_id(draft, source_ids):
                raise ValueError("Frozen draft violates the PMID/query boundary")

    admission_path = _claim_campaign_admission(protocol)
    recorder = (
        client
        if isinstance(client, fixture._RecordingClient)
        else fixture._RecordingClient(client)
    )
    parser = ResponseParser(tool)
    nonce = uuid.uuid4().hex[:12]
    report: dict[str, Any] = {
        "name": "M11-NOV-01a3b3 result-conditioned exploratory paired pilot",
        "status": "RUNNING",
        "fixture_bank_sha256": fixture._bank_config(1)["sha256"],
        "selected_model": model_name,
        "model_call_count": 0,
        "provider_call_count": 0,
        "outer_mcp_call_count": 0,
        "paid_calls": 0,
        "max_model_calls": MODEL_CALL_LIMIT,
        "max_outer_mcp_calls": OUTER_MCP_CALL_LIMIT,
        "max_papers_per_search": MAX_PAPERS,
        "model_request_config": MODEL_REQUEST_CONFIG,
        "campaign_admission": str(admission_path),
        "mcp_serving_process": serving_process,
        "events": [],
    }
    blind_packet: dict[str, Any] = {"status": "BLIND_LABELS_PENDING", "items": []}
    fixture._write_json(result_path, report, private=True)
    fixture._write_json(blind_path, blind_packet, private=True)

    async def generate(
        draft: str,
        variant: str,
        papers: list[dict[str, Any]] | None,
        pair_id: str,
        arm: str,
        draft_id: str,
        first_search_event_id: int | None = None,
    ) -> str | None:
        if report["model_call_count"] >= MODEL_CALL_LIMIT:
            raise ValueError("Pilot exceeded its model call ceiling")
        event = {
            "event_id": len(report["events"]) + 1,
            "kind": "model",
            "pair_id": pair_id,
            "draft_id": draft_id,
            "draft": draft,
            "arm": arm,
            "stage": f"{variant}_query",
            "started_at_utc": _now(),
        }
        if first_search_event_id is not None:
            event["first_search_event_id"] = first_search_event_id
        report["events"].append(event)
        report["model_call_count"] += 1
        fixture._write_json(result_path, report, private=True)
        try:
            prompt = _prompt(variant, draft, papers)
            if _contains_source_id(prompt, source_ids):
                raise ValueError("Model prompt contains a frozen target or anchor PMID")
            query = await _generate_query(
                prompt,
                model_name=model_name,
                model_api_key=model_api_key,
                run_id=f"m11_nov_01a3b3_{nonce}_{report['model_call_count']:02d}",
                expected_source_ids=source_ids,
                event=event,
            )
            event["query"] = query
            event["status"] = "complete"
            report["provider_call_count"] += event["provider_calls"]
            fixture._write_json(result_path, report, private=True)
            return query
        except Exception as exc:
            stats = event.get("telemetry", {})
            served_model, calls, observed, retries = _telemetry_totals(stats)
            event.update(
                {
                    "status": "error",
                    "exception_type": type(exc).__name__,
                    "served_model": served_model,
                    "provider_calls": calls,
                    "observed_model_calls": observed,
                    "retries": retries,
                    "ended_at_utc": _now(),
                }
            )
            report["provider_call_count"] += calls
            report["status"] = _error_status(exc)
            fixture._write_json(result_path, report, private=True)
            return None

    async def search(
        query: str,
        pair_id: str,
        arm: str,
        stage: str,
        draft: str,
        draft_id: str,
        first_search_event_id: int | None = None,
    ) -> list[dict[str, Any]] | None:
        if report["outer_mcp_call_count"] >= OUTER_MCP_CALL_LIMIT:
            raise ValueError("Pilot exceeded its outer MCP call ceiling")
        if _contains_source_id(query, source_ids):
            raise ValueError("PubMed query contains a frozen target or anchor PMID")
        event: dict[str, Any] = {"event_id": len(report["events"]) + 1}
        report["events"].append(event)
        report["outer_mcp_call_count"] += 1
        result = await _search_once(
            query,
            pair_id=pair_id,
            arm=arm,
            stage=stage,
            registry=registry,
            recorder=recorder,
            parser=parser,
            cache_root=cache_root,
            expected_build_id=expected_build_id,
            nonce=nonce,
            outer_call_number=report["outer_mcp_call_count"],
            endpoint=endpoint,
            serving_process=serving_process,
            draft=draft,
            draft_id=draft_id,
            source_ids=source_ids,
            first_search_event_id=first_search_event_id,
            blind_items=blind_packet["items"],
            event=event,
        )
        if result is None:
            report["status"] = (
                "INCOMPLETE_RATE_LIMIT"
                if event.get("classification") == "rate_limited"
                else "INCOMPLETE_ERROR"
            )
        fixture._write_json(result_path, report, private=True)
        fixture._write_json(blind_path, blind_packet, private=True)
        return result

    try:
        await client.initialize()
        with scoped_campaign_mode(True):
            for pair in pairs:
                pair_id = pair["id"]
                for arm in ("positive", "distinct_control"):
                    draft = pair[arm]["draft"]
                    draft_id = f"{pair_id}:{arm}"
                    # The static query is fixed before any first-search evidence exists.
                    static_query = await generate(
                        draft, "static", None, pair_id, arm, draft_id
                    )
                    if static_query is None:
                        return report
                    first = await search(
                        draft[:MAX_QUERY_CHARS],
                        pair_id,
                        "shared",
                        "first_search",
                        draft,
                        draft_id,
                    )
                    if first is None:
                        return report
                    first_search_event_id = report["events"][-1]["event_id"]
                    conditioned_query = await generate(
                        draft,
                        "conditioned",
                        first,
                        pair_id,
                        arm,
                        draft_id,
                        first_search_event_id,
                    )
                    if conditioned_query is None:
                        return report
                    static_followup = await search(
                        static_query,
                        pair_id,
                        "static",
                        "follow_up",
                        draft,
                        draft_id,
                        first_search_event_id,
                    )
                    if static_followup is None:
                        return report
                    candidate_followup = await search(
                        conditioned_query,
                        pair_id,
                        "candidate",
                        "follow_up",
                        draft,
                        draft_id,
                        first_search_event_id,
                    )
                    if candidate_followup is None:
                        return report
        report["status"] = "PILOT_COMPLETE_LABELS_PENDING"
        report["ended_at_utc"] = _now()
        blind_packet["items"].sort(key=lambda item: item["blind_id"])
        fixture._write_json(result_path, report, private=True)
        fixture._write_json(blind_path, blind_packet, private=True)
        return report
    except Exception as exc:
        report["status"] = _error_status(exc)
        report["exception_type"] = type(exc).__name__
        report["ended_at_utc"] = _now()
        fixture._write_json(result_path, report, private=True)
        fixture._write_json(blind_path, blind_packet, private=True)
        return report


def _error_status(exc: Exception) -> str:
    _, _, limited = fixture._error_metadata(exc)
    if limited:
        return "INCOMPLETE_RATE_LIMIT"
    return "INCOMPLETE_ERROR"


def _claim_campaign_admission(protocol: dict[str, Any]) -> Path:
    """Persist the campaign's one-shot claim before its first external call."""
    path = PILOT_PREREG.with_suffix(".admission.json")
    receipt = {
        "status": "CLAIMED",
        "claimed_at_utc": _now(),
        "protocol_sha256": hashlib.sha256(PILOT_PREREG.read_bytes()).hexdigest(),
        "model_name": protocol["model_name"],
        "max_model_calls": MODEL_CALL_LIMIT,
        "max_outer_mcp_calls": OUTER_MCP_CALL_LIMIT,
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("Pilot campaign admission already exists") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _committed_protocol_bytes(path: Path) -> bytes:
    try:
        relative_path = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Pilot protocol must be committed unchanged") from exc
    committed = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if committed.returncode:
        raise ValueError("Pilot protocol must be committed unchanged")
    return committed.stdout


def _model_boundary_hashes() -> dict[str, str]:
    return {
        relative: fixture._sha256(ROOT / relative) for relative in MODEL_BOUNDARY_FILES
    }


def _load_pilot_protocol() -> dict[str, Any]:
    if not PILOT_PREREG.is_file():
        raise ValueError("Pilot is disabled until its protocol is preregistered")
    protocol_bytes = PILOT_PREREG.read_bytes()
    if _committed_protocol_bytes(PILOT_PREREG) != protocol_bytes:
        raise ValueError("Pilot protocol must be committed unchanged")
    protocol = json.loads(protocol_bytes)
    if protocol.get("status") != "PREREGISTERED_BEFORE_ANY_PILOT_CALL":
        raise ValueError("Pilot protocol is not preregistered")
    if protocol.get("fixture_bank_sha256") != fixture._bank_config(1)["sha256"]:
        raise ValueError("Pilot protocol names a different frozen fixture bank")
    if (
        protocol.get("runner_sha256")
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("Pilot runner changed after preregistration")
    if (
        protocol.get("static_prompt_sha256")
        != hashlib.sha256(STATIC_PROMPT.encode()).hexdigest()
    ):
        raise ValueError("Static prompt changed after preregistration")
    if (
        protocol.get("conditioned_prompt_sha256")
        != hashlib.sha256(CONDITIONED_PROMPT.encode()).hexdigest()
    ):
        raise ValueError("Conditioned prompt changed after preregistration")
    if protocol.get("request_config") != MODEL_REQUEST_CONFIG:
        raise ValueError("Pilot request settings differ from preregistration")
    if protocol.get("model_boundary_sha256") != _model_boundary_hashes():
        raise ValueError(
            "Pilot model admission/dispatch sources changed or are unpinned"
        )
    if (
        protocol.get("max_outer_mcp_calls") != OUTER_MCP_CALL_LIMIT
        or protocol.get("max_model_calls") != MODEL_CALL_LIMIT
    ):
        raise ValueError("Pilot call bounds differ from preregistration")
    if not isinstance(protocol.get("model_name"), str) or not protocol["model_name"]:
        raise ValueError("Pilot protocol does not select a model")
    return protocol


def _check_mcp_process(
    endpoint: str,
    *,
    expected_secret: str,
    expected_build_id: str,
    cache_root: Path,
) -> dict[str, Any]:
    """Attest the actual loopback listener's source directory and environment."""
    fixture._check_server_tree_clean()
    source_tree = fixture._git("rev-parse", "HEAD:engine/mcp_server")
    if source_tree != expected_build_id:
        raise ValueError("MCP process source tree differs from the pinned tree")
    source_path = (ROOT / "engine/mcp_server/server.py").resolve(strict=True)
    port = urlsplit(endpoint).port
    if port is None:
        raise ValueError("MCP endpoint has no port")
    listener = subprocess.run(
        ["lsof", "-nP", "-Fpn", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    fields = listener.stdout.splitlines()
    pids = [line[1:] for line in fields if line.startswith("p")]
    addresses = [line[1:] for line in fields if line.startswith("n")]
    if (
        listener.returncode != 0
        or len(pids) != 1
        or not pids[0].isdigit()
        or len(addresses) != 1
        or addresses[0] not in {f"127.0.0.1:{port}", f"[::1]:{port}"}
    ):
        raise ValueError("MCP endpoint is not served by one loopback process")
    pid = pids[0]
    cwd = subprocess.run(
        ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
        capture_output=True,
        text=True,
        check=False,
    )
    working_dirs = [
        line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")
    ]
    if (
        cwd.returncode != 0
        or len(working_dirs) != 1
        or Path(working_dirs[0]).resolve() != (ROOT / "engine").resolve()
    ):
        raise ValueError("MCP process is not running from the pinned engine tree")
    process = subprocess.run(
        ["ps", "eww", "-p", pid],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise ValueError("MCP process environment could not be attested")
    environment = dict(
        re.findall(r"(?<!\S)([A-Za-z_][A-Za-z0-9_]*)=([^\s]*)", process.stdout)
    )
    python_paths = [
        (
            Path(value) if Path(value).is_absolute() else Path(working_dirs[0]) / value
        ).resolve()
        for value in environment.get("PYTHONPATH", "").split(os.pathsep)
        if value
    ]
    engine_path = (ROOT / "engine").resolve()
    if (
        "mcp_server.server:app" not in process.stdout
        or not python_paths
        or any(path != engine_path for path in python_paths)
        or not source_path.is_relative_to(engine_path / "mcp_server")
    ):
        raise ValueError("MCP process does not load the pinned maintained server")
    if any(
        value and name != fixture.MCP_SECRET_ENV and name.endswith(_CREDENTIAL_SUFFIXES)
        for name, value in environment.items()
    ):
        raise ValueError("MCP process failed credential-free admission")
    if (
        environment.get(fixture.MCP_SECRET_ENV) != expected_secret
        or environment.get("COSCIENTIST_REQUIRE_FREE_MODELS") != "1"
        or environment.get("COSCIENTIST_PUBMED_PILOT_TRACE") != "1"
        or environment.get("COSCIENTIST_PUBMED_PILOT_BUILD_ID") != expected_build_id
        or Path(environment.get("COSCIENTIST_LIT_REVIEW_DIR", "")).resolve()
        != cache_root.resolve()
    ):
        raise ValueError("MCP process settings differ from the frozen pilot")
    return {
        "pid": int(pid),
        "listener_address": addresses[0],
        "source_path": str(source_path),
        "mcp_tree": source_tree,
    }


def _require_same_serving_process(
    endpoint: str,
    expected: dict[str, Any],
    cache_root: Path,
    expected_build_id: str,
) -> None:
    actual = _check_mcp_process(
        endpoint,
        expected_secret=os.environ[fixture.MCP_SECRET_ENV],
        expected_build_id=expected_build_id,
        cache_root=cache_root,
    )
    if actual != expected:
        raise ValueError("MCP serving process changed during the pilot")


def _check_runtime(
    protocol: dict[str, Any],
    fixture_prereg: dict[str, Any],
    *,
    cache_root: Path,
) -> tuple[str, Path, str, dict[str, Any]]:
    if os.environ.get("COSCIENTIST_REQUIRE_FREE_MODELS") != "1":
        raise ValueError("Set COSCIENTIST_REQUIRE_FREE_MODELS=1")
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
    if len(os.environ.get(fixture.MCP_SECRET_ENV, "")) < 32:
        raise ValueError(
            "A transient loopback MCP secret of 32+ characters is required"
        )
    if os.environ.get("COSCIENTIST_PUBMED_PILOT_TRACE") != "1":
        raise ValueError("Maintained PubMed run tracing must be enabled")
    boundary = fixture_prereg["validation_boundary"]
    for path_key, hash_key in (
        ("validator", "validator_sha256"),
        ("parser", "parser_sha256"),
        ("tool_config", "tool_config_sha256"),
    ):
        if fixture._sha256(ROOT / boundary[path_key]) != boundary[hash_key]:
            raise ValueError(f"Frozen validator source changed: {boundary[path_key]}")
    fixture._check_server_tree_clean()
    current_mcp_tree = fixture._git("rev-parse", "HEAD:engine/mcp_server")
    if protocol.get("mcp_tree") != current_mcp_tree:
        raise ValueError("Maintained MCP source tree differs from the pilot protocol")
    expected_build = protocol.get("mcp_build_id")
    if expected_build != current_mcp_tree:
        raise ValueError("Pilot build ID must equal the current MCP source tree")
    if os.environ.get("COSCIENTIST_PUBMED_PILOT_BUILD_ID") != expected_build:
        raise ValueError("MCP trace build ID must match the frozen maintained source")
    if any(
        (ROOT / name).exists()
        for name in (".env", "engine/.env", "engine/mcp_server/.env")
    ):
        raise ValueError(
            "Remove repository .env files before credential-free screening"
        )
    serving_process = _check_mcp_process(
        endpoint,
        expected_secret=os.environ[fixture.MCP_SECRET_ENV],
        expected_build_id=expected_build,
        cache_root=cache_root,
    )
    return endpoint, cache_root, expected_build, serving_process


def _new_output_paths() -> tuple[Path, Path]:
    nonce = uuid.uuid4().hex
    return (
        RESULT_DIR / f"novelty-result-conditioned-pilot-v1-{nonce[:12]}.json",
        Path("/tmp") / f"cosci-m11-nov-01a3b3-v1-blind-{nonce}.json",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


async def _main() -> int:
    _parse_args()
    protocol = _load_pilot_protocol()
    fixture_prereg = fixture._load_preregistration(1)
    cache_root = Path(os.environ.get("COSCIENTIST_LIT_REVIEW_DIR", ""))
    endpoint, cache_root, expected_build, _ = _check_runtime(
        protocol, fixture_prereg, cache_root=cache_root
    )
    model_api_key = os.environ.get("OPENROUTER_API_KEY")
    if not model_api_key:
        raise ValueError("Pass the OpenRouter model key to the runner explicitly")
    result_path, blind_path = _new_output_paths()
    registry = ToolRegistry(config_path=str(ROOT / TOOL_CONFIG), skip_user_config=True)
    client = MCPToolClient(server_url=endpoint)
    report = await run_pilot(
        fixture_prereg,
        registry,
        client,
        cache_root,
        result_path,
        blind_path,
        expected_build_id=expected_build,
        model_name=protocol["model_name"],
        model_api_key=model_api_key,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "model_call_count": report["model_call_count"],
                "provider_call_count": report["provider_call_count"],
                "outer_mcp_call_count": report["outer_mcp_call_count"],
                "result": str(result_path),
                "blind_packet": str(blind_path),
            }
        )
    )
    return 0 if report["status"] == "PILOT_COMPLETE_LABELS_PENDING" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
