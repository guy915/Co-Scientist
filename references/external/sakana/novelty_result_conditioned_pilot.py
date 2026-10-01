"""Run the offline-testable, preregistration-gated paired novelty pilot."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import email.utils
import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, NamedTuple, cast
from urllib.parse import urlsplit

import litellm
import novelty_fixture_bank_screen as fixture
import novelty_batch_trace as batch_trace_reader
from co_scientist.agents.generation.literature_tools.validate_search import (
    _find_search_tool,
)
from co_scientist.config.registry import ToolRegistry
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm, call_llm_json
from co_scientist.llm_free_policy import scoped_campaign_mode
from co_scientist.llm_telemetry import scoped_telemetry
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import ResponseParser

ROOT = fixture.ROOT
RESULT_DIR = ROOT / "references/external/sakana"
PILOT_PREREG = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v1.json"
PILOT_PREREG_V2 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v2.json"
PILOT_PREREG_V3 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v3.json"
PILOT_PREREG_V4 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v4.json"
PILOT_PREREG_V5 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v5.json"
PILOT_PREREG_V6 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v6.json"
PILOT_PREREG_V7 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v7.json"
PILOT_PREREG_V8 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v8.json"
PILOT_PREREG_V9 = RESULT_DIR / "novelty-result-conditioned-pilot-prereg-v9.json"
V2_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v3.json"
V2_FIXTURE_BANK_STATUS = "PREREGISTERED_BEFORE_ANY_V3_VALIDATOR_SCREEN"
V3_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v4.json"
V3_FIXTURE_BANK_STATUS = "PREREGISTERED_BEFORE_ANY_V4_VALIDATOR_SCREEN"
V4_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v5.json"
V4_FIXTURE_BANK_STATUS = "PREREGISTERED_FRESH_FOURTH_STUDY_INPUTS"
V5_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v6.json"
V5_FIXTURE_BANK_STATUS = "PREREGISTERED_FRESH_BATCH_AWARE_FIFTH_STUDY_INPUTS"
V6_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v7.json"
V6_FIXTURE_BANK_STATUS = "PREREGISTERED_FRESH_BATCH_AWARE_SIXTH_STUDY_INPUTS"
V7_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v8.json"
V7_FIXTURE_BANK_STATUS = "PREREGISTERED_FRESH_BATCH_AWARE_SEVENTH_STUDY_INPUTS"
V8_FIXTURE_BANK_PATH = "references/external/sakana/novelty-fixture-bank-prereg-v9.json"
V8_FIXTURE_BANK_STATUS = "PREREGISTERED_FRESH_BATCH_AWARE_EIGHTH_STUDY_INPUTS"
V9_FIXTURE_BANK_PATH = V8_FIXTURE_BANK_PATH
V9_FIXTURE_BANK_STATUS = V8_FIXTURE_BANK_STATUS
STUDY8_SEARCH_PARAMETERS = MappingProxyType({"include_fulltext": False})
STUDY9_SEARCH_PARAMETERS = STUDY8_SEARCH_PARAMETERS
OFFLINE_PREFLIGHT_BANK_STATUS = "OFFLINE_PREFLIGHT_ONLY_NOT_REGISTERED"
JSON_QUERY_OUTPUT_FORMAT = "json"
PLAIN_TEXT_QUERY_OUTPUT_FORMAT = "plain_text"
STUDY4_IDENTITY = "M12-04b4-study4-20260930"
STUDY4_RECOVERY_ENV = "COSCIENTIST_PUBMED_STUDY4_RECOVERY"
STUDY_ID_ENV = "COSCIENTIST_PUBMED_STUDY_ID"
BATCH_METADATA_ENV = "COSCIENTIST_PUBMED_METADATA_BATCH"
STUDY4_RECOVERY_POLICY = "study4-entrez-429-502-v1"
STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST = 1
STUDY4_MAX_RETRIES_PER_STUDY = 2
STUDY4_RETRYABLE_HTTP_STATUSES = (429, 502)
STUDY4_RETRY_AFTER_MAX_SECONDS = 60
STUDY4_RETRY_AFTER_DEFAULT_SECONDS = 15
STUDY4_PACER_INTERVAL_SECONDS = 0.4
STUDY4_MAX_TRACE_RECOVERY_ROWS = 256
STUDY4_RECOVERY_PROTOCOL = MappingProxyType(
    {
        "study_id": STUDY4_IDENTITY,
        "activation_env": STUDY4_RECOVERY_ENV,
        "activation_value": "1",
        "study_id_env": STUDY_ID_ENV,
        "study_id_env_value": STUDY4_IDENTITY,
        "trace_env": "COSCIENTIST_PUBMED_PILOT_TRACE",
        "trace_value": "1",
        "policy": STUDY4_RECOVERY_POLICY,
        "retryable_http_statuses": [429, 502],
        "max_retries_per_logical_request": STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST,
        "max_retries_per_study": STUDY4_MAX_RETRIES_PER_STUDY,
        "retry_after_max_seconds": STUDY4_RETRY_AFTER_MAX_SECONDS,
        "retry_after_default_seconds": STUDY4_RETRY_AFTER_DEFAULT_SECONDS,
        "pacer_interval_seconds": STUDY4_PACER_INTERVAL_SECONDS,
    }
)
_STUDY4_OPERATION_ORDER = ("esearch", "efetch", "elink")
_STUDY4_OPERATIONS = frozenset(_STUDY4_OPERATION_ORDER)
_STUDY4_RECOVERY_OUTCOMES = frozenset(
    {"recovered", "exhausted", "study_budget_exhausted", "retry_after_over_cap"}
)
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
PLAIN_TEXT_MODEL_BOUNDARY_FILES = (
    "engine/src/co_scientist/llm_text_retry.py",
)
BATCH_TRACE_SOURCE_FILES = (
    "references/external/sakana/novelty_batch_trace.py",
    "engine/mcp_server/entrez_rate_limit.py",
    "engine/mcp_server/pubmed_client.py",
    "engine/mcp_server/pubmed_metadata_batch.py",
    "engine/mcp_server/pubmed_pilot_trace.py",
    "engine/mcp_server/shared_pool.py",
    "engine/mcp_server/tools/lit_review/pubmed_search_with_fulltext.py",
)


class _StudyRegistration(NamedTuple):
    protocol_version: int
    fixture_bank_version: int | None
    fixture_bank_path: str | None
    fixture_bank_status: str | None
    requires_raw_trace: bool
    report_name: str
    result_prefix: str
    blind_prefix: str
    requires_batch_metadata: bool
    query_output_format: str = JSON_QUERY_OUTPUT_FORMAT


_STUDY_REGISTRATIONS: Mapping[int, _StudyRegistration] = MappingProxyType(
    {
        1: _StudyRegistration(
            1,
            None,
            None,
            None,
            False,
            "M11-NOV-01a3b3 result-conditioned exploratory paired pilot",
            "novelty-result-conditioned-pilot-v1",
            "cosci-m11-nov-01a3b3-v1-blind",
            False,
        ),
        2: _StudyRegistration(
            2,
            3,
            V2_FIXTURE_BANK_PATH,
            V2_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4c result-conditioned prospective paired study",
            "novelty-result-conditioned-pilot-v2",
            "cosci-m12-nov-04b4c-v2-blind",
            False,
        ),
        3: _StudyRegistration(
            3,
            4,
            V3_FIXTURE_BANK_PATH,
            V3_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4d2 result-conditioned prospective paired study",
            "novelty-result-conditioned-pilot-v3",
            "cosci-m12-nov-04b4d2-v3-blind",
            False,
        ),
        4: _StudyRegistration(
            4,
            5,
            V4_FIXTURE_BANK_PATH,
            V4_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4e3 result-conditioned prospective paired study",
            "novelty-result-conditioned-pilot-v4",
            "cosci-m12-nov-04b4e3-v4-blind",
            False,
        ),
        5: _StudyRegistration(
            5,
            6,
            V5_FIXTURE_BANK_PATH,
            V5_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4f4 batch-aware result-conditioned prospective study",
            "novelty-result-conditioned-pilot-v5",
            "cosci-m12-nov-04b4f4-v5-blind",
            True,
        ),
        6: _StudyRegistration(
            6,
            7,
            V6_FIXTURE_BANK_PATH,
            V6_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4g1 batch-aware result-conditioned prospective study",
            "novelty-result-conditioned-pilot-v6",
            "cosci-m12-nov-04b4g1-v6-blind",
            True,
        ),
        7: _StudyRegistration(
            7,
            8,
            V7_FIXTURE_BANK_PATH,
            V7_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4h1 batch-aware result-conditioned prospective study",
            "novelty-result-conditioned-pilot-v7",
            "cosci-m12-nov-04b4h1-v7-blind",
            True,
            PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        ),
        8: _StudyRegistration(
            8,
            9,
            V8_FIXTURE_BANK_PATH,
            V8_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4j3 batch-aware metadata-only result-conditioned prospective study",
            "novelty-result-conditioned-pilot-v8",
            "cosci-m12-nov-04b4j3-v8-blind",
            True,
            PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        ),
        9: _StudyRegistration(
            9,
            9,
            V9_FIXTURE_BANK_PATH,
            V9_FIXTURE_BANK_STATUS,
            True,
            "M12-NOV-04b4k2 batch-aware compact-query result-conditioned prospective study",
            "novelty-result-conditioned-pilot-v9",
            "cosci-m12-nov-04b4k2-v9-blind",
            True,
            PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        ),
    }
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
PLAIN_TEXT_OUTPUT_INSTRUCTION = (
    "Return only the PubMed query itself as one line of plain text, at most 200 "
    "characters. Do not wrap it in JSON, markdown fences, outer quotation marks, "
    "a label, or explanatory prose. Keep PubMed phrase quotes only where the "
    "query syntax needs them; do not JSON-escape those quotes."
)
PLAIN_TEXT_STATIC_PROMPT = (
    "Generate one concise PubMed search query for the scientific draft below. "
    "Use the draft alone. Do not add identifiers. "
    + PLAIN_TEXT_OUTPUT_INSTRUCTION
    + "\n\nDraft:\n{draft}"
)
PLAIN_TEXT_CONDITIONED_PROMPT = (
    "Generate one concise PubMed search query for the scientific draft below. "
    "Use only the draft and the supplied first-search titles and abstracts to "
    "choose useful terminology. Do not add or infer publication identifiers. "
    + PLAIN_TEXT_OUTPUT_INSTRUCTION
    + "\n\nDraft:\n{draft}\n\nFirst-search titles and abstracts:\n{evidence}"
)
COMPACT_QUERY_OUTPUT_GUIDANCE = (
    "Use 3-5 core search terms or short quoted phrases. Use AND/OR only where "
    "useful and keep Boolean structure compact. Do not add PubMed field tags "
    "or expand the query with synonyms."
)
COMPACT_PLAIN_TEXT_OUTPUT_INSTRUCTION = (
    PLAIN_TEXT_OUTPUT_INSTRUCTION + " " + COMPACT_QUERY_OUTPUT_GUIDANCE
)
COMPACT_PLAIN_TEXT_STATIC_PROMPT = (
    "Generate one concise PubMed search query for the scientific draft below. "
    "Use the draft alone. Do not add identifiers. "
    + COMPACT_PLAIN_TEXT_OUTPUT_INSTRUCTION
    + "\n\nDraft:\n{draft}"
)
COMPACT_PLAIN_TEXT_CONDITIONED_PROMPT = (
    "Generate one concise PubMed search query for the scientific draft below. "
    "Use only the draft and the supplied first-search titles and abstracts to "
    "choose useful terminology. Do not add or infer publication identifiers. "
    + COMPACT_PLAIN_TEXT_OUTPUT_INSTRUCTION
    + "\n\nDraft:\n{draft}\n\nFirst-search titles and abstracts:\n{evidence}"
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


def _pilot_pairs(prereg: dict[str, Any], study_version: int) -> list[dict[str, Any]]:
    pairs = prereg["cases_in_fixed_order"]
    if not isinstance(pairs, list) or len(pairs) != PAIR_COUNT:
        raise ValueError(
            "Pilot requires every pair from the frozen v1 bank"
            if study_version == 1
            else "Pilot requires every pair from the frozen bank"
        )
    return cast(list[dict[str, Any]], pairs)


def _validate_pilot_drafts(
    prereg: dict[str, Any], pairs: list[dict[str, Any]]
) -> set[str]:
    source_ids = _source_ids(prereg)
    for pair in pairs:
        for arm in ("positive", "distinct_control"):
            draft = pair[arm]["draft"]
            if len(draft) > MAX_QUERY_CHARS or _contains_source_id(draft, source_ids):
                raise ValueError("Frozen draft violates the PMID/query boundary")
    return source_ids


def _pilot_search_tool(registry: ToolRegistry) -> Any:
    tool_id, tool = _find_search_tool(registry)
    if tool_id != "pubmed_fulltext" or not tool:
        raise ValueError("Configured PubMed validation tool is unavailable")
    if tool.mcp_tool_name != "pubmed_search_with_fulltext":
        raise ValueError("Configured PubMed validation tool differs from the pilot")
    return tool


def _prompt(
    variant: str,
    draft: str,
    papers: list[dict[str, Any]] | None = None,
    *,
    output_format: str = JSON_QUERY_OUTPUT_FORMAT,
    study_version: int = 1,
) -> str:
    static_template, conditioned_template = _query_prompt_templates(
        output_format, study_version=study_version
    )
    if variant == "static":
        return static_template.format(draft=draft)
    evidence = "\n\n".join(
        "Title: "
        + str(paper["title"] or "")
        + "\nAbstract: "
        + str(paper["abstract"] or "")
        for paper in papers or []
    )
    return conditioned_template.format(draft=draft, evidence=evidence)


def _query_prompt_templates(
    output_format: str, *, study_version: int = 1
) -> tuple[str, str]:
    if output_format == JSON_QUERY_OUTPUT_FORMAT:
        return STATIC_PROMPT, CONDITIONED_PROMPT
    if output_format == PLAIN_TEXT_QUERY_OUTPUT_FORMAT:
        if study_version == 9:
            return (
                COMPACT_PLAIN_TEXT_STATIC_PROMPT,
                COMPACT_PLAIN_TEXT_CONDITIONED_PROMPT,
            )
        return PLAIN_TEXT_STATIC_PROMPT, PLAIN_TEXT_CONDITIONED_PROMPT
    raise ValueError(f"Unsupported query output format: {output_format}")


def _query_output_format(protocol: dict[str, Any], study_version: int) -> str:
    registration = _study_registration(study_version)
    if "query_output_format" not in protocol:
        if registration.query_output_format == PLAIN_TEXT_QUERY_OUTPUT_FORMAT:
            raise ValueError(
                f"Study {study_version} protocol must pin its query output format"
            )
        return registration.query_output_format
    output_format = protocol["query_output_format"]
    if not isinstance(output_format, str) or output_format not in {
        JSON_QUERY_OUTPUT_FORMAT,
        PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
    }:
        raise ValueError(f"Unsupported query output format: {output_format}")
    if output_format != registration.query_output_format:
        raise ValueError(
            f"Study {study_version} protocol selects the wrong query output format"
        )
    return output_format


def _validate_search_parameters(protocol: dict[str, Any], study_version: int) -> None:
    if study_version in (8, 9):
        parameters = protocol.get("search_parameters")
        if (
            not isinstance(parameters, dict)
            or set(parameters) != set(STUDY9_SEARCH_PARAMETERS)
            or parameters.get("include_fulltext") is not False
            or "include_fulltext" in protocol
        ):
            raise ValueError(
                f"Study {study_version} protocol must pin metadata-only search parameters"
            )
    elif "search_parameters" in protocol or "include_fulltext" in protocol:
        raise ValueError("Historical study protocols cannot override search parameters")


class _MetadataOnlySearchClient:
    """Pass a metadata-only study opt-out through the maintained MCP call."""

    def __init__(self, recorder: Any, study_version: int = 8) -> None:
        self.recorder = recorder
        self.study_version = study_version

    def __getattr__(self, name: str) -> Any:
        return getattr(self.recorder, name)

    async def call_tool(self, tool_name: str, **params: Any) -> Any:
        if tool_name != "pubmed_search_with_fulltext":
            raise ValueError(
                f"Study {self.study_version} requires the maintained PubMed search tool"
            )
        parameters = dict(params)
        parameters.update(STUDY9_SEARCH_PARAMETERS)
        return await self.recorder.call_tool(tool_name, **parameters)


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


@contextmanager
def _capture_completion_finish_reasons() -> Iterator[list[str | None]]:
    """Observe raw finish reasons around one serialized reference-runner call."""
    original_acompletion = litellm.acompletion
    finish_reasons: list[str | None] = []

    async def observed_acompletion(**kwargs: Any) -> Any:
        response = await original_acompletion(**kwargs)
        choices = getattr(response, "choices", None)
        finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
        finish_reasons.append(
            finish_reason if isinstance(finish_reason, str) else None
        )
        return response

    # call_llm returns text only; this temporary serial observer retains the
    # provider completion status without changing the shared engine boundary.
    litellm.acompletion = observed_acompletion
    try:
        yield finish_reasons
    finally:
        litellm.acompletion = original_acompletion


async def _generate_query(
    prompt: str,
    *,
    model_name: str,
    model_api_key: str,
    run_id: str,
    expected_source_ids: set[str],
    event: dict[str, Any],
    output_format: str = JSON_QUERY_OUTPUT_FORMAT,
) -> str:
    if output_format not in (
        JSON_QUERY_OUTPUT_FORMAT,
        PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
    ):
        raise ValueError(f"Unsupported query output format: {output_format}")
    event["started_at_utc"] = _now()
    event["request_config"] = MODEL_REQUEST_CONFIG
    event["query_output_format"] = output_format
    with scoped_telemetry("m11_nov_01a3b3_query") as telemetry:
        try:
            with scoped_campaign_mode(True):
                spec = CompletionSpec(
                    model_name=model_name,
                    max_tokens=MODEL_MAX_TOKENS,
                    temperature=MODEL_TEMPERATURE,
                    json_schema=(
                        QUERY_SCHEMA
                        if output_format == JSON_QUERY_OUTPUT_FORMAT
                        else None
                    ),
                    force_json=output_format == JSON_QUERY_OUTPUT_FORMAT,
                    api_key=model_api_key,
                )
                options = LLMCallOptions(
                    use_cache=False,
                    run_id=run_id,
                    enable_thinking=False,
                )
                if output_format == JSON_QUERY_OUTPUT_FORMAT:
                    result = await call_llm_json(
                        prompt,
                        spec,
                        max_attempts=MAX_ATTEMPTS,
                        options=options,
                    )
                    query = result.get("query")
                else:
                    finish_reasons: list[str | None] = []
                    try:
                        with _capture_completion_finish_reasons() as finish_reasons:
                            raw_query = await call_llm(
                                prompt,
                                spec,
                                options=options,
                                max_attempts=MAX_ATTEMPTS,
                            )
                    finally:
                        event["completion_finish_reasons"] = list(finish_reasons)
                        event["completion_response_count"] = len(finish_reasons)
                    event["raw_query_response"] = raw_query
                    if finish_reasons != ["stop"]:
                        raise ValueError(
                            "Plain-text completion did not end with finish_reason=stop"
                        )
                    query = raw_query.strip()
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
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ValueError("Generated query is empty or exceeds 200 characters")
    if output_format == PLAIN_TEXT_QUERY_OUTPUT_FORMAT:
        _validate_plain_text_query(query)
    if _contains_source_id(query, expected_source_ids):
        raise ValueError("Generated query contains a frozen target or anchor PMID")
    return query


_PLAIN_TEXT_WRAPPER_PREFIX = re.compile(
    r"(?i)^(?:here(?: is|'s)\s+(?:the\s+)?(?:pubmed\s+)?query\s*:|"
    r"(?:pubmed\s+)?query\s*:|the\s+query\s+is\s*:|search\s+query\s*:)"
)
_PLAIN_TEXT_WRAPPER_SUFFIX = re.compile(
    r"(?i)(?:\s+(?:hope this helps|let me know if you need anything else)[.!]?)$"
)
_PLAIN_TEXT_INCOMPLETE_BOOLEAN = re.compile(
    r"(?i)(?:^(?:AND|OR|NOT)\b|\b(?:AND|OR|NOT)\b(?=\s*(?:\)+|$)))"
)


def _validate_plain_text_query(query: str) -> None:
    if len(query.splitlines()) != 1:
        raise ValueError("Plain-text query must contain exactly one line")
    if "`" in query or query.startswith("{") or query.endswith("}"):
        raise ValueError("Plain-text query contains a markdown or JSON wrapper")
    if r"\"" in query:
        raise ValueError("Plain-text query contains JSON-escaped quote marks")
    if _PLAIN_TEXT_WRAPPER_PREFIX.search(query) or _PLAIN_TEXT_WRAPPER_SUFFIX.search(
        query
    ):
        raise ValueError("Plain-text query contains wrapper prose")
    quoted = False
    delimiters: list[str] = []
    unquoted_chars: list[str] = []
    closing = {")": "(", "]": "["}
    for char in query:
        if char == '"':
            if not quoted:
                unquoted_chars.append(" QUOTED_PHRASE ")
            quoted = not quoted
        elif not quoted:
            unquoted_chars.append(char)
            if char in "{}":
                raise ValueError("Plain-text query contains unquoted JSON braces")
            if char in "([":
                delimiters.append(char)
            elif char in ")]":
                if not delimiters or delimiters.pop() != closing[char]:
                    raise ValueError("Plain-text query contains an unbalanced delimiter")
    if quoted:
        raise ValueError("Plain-text query contains an unbalanced quote")
    if delimiters:
        raise ValueError("Plain-text query contains an unbalanced delimiter")
    if _PLAIN_TEXT_INCOMPLETE_BOOLEAN.search("".join(unquoted_chars)):
        raise ValueError("Plain-text query ends in an incomplete boolean expression")


def _validate_batch_returned_links(
    raw_trace: dict[str, Any],
    records: dict[str, Any],
    returned_ids: list[str],
) -> None:
    # _search_once strictly attests the empty trace before checking returned links.
    if not returned_ids:
        return
    batching = raw_trace.get("metadata_batching")
    batches = batching.get("batches") if isinstance(batching, dict) else None
    if not isinstance(batches, list):
        raise ValueError("PubMed batch trace has no per-ID ELink results")
    pmc_ids = {
        result["pmid"]: result["pmc_id"]
        for batch in batches
        if isinstance(batch, dict)
        for result in batch.get("elink_results", [])
        if isinstance(result, dict) and isinstance(result.get("pmid"), str)
    }
    for paper_id in returned_ids:
        record = records.get(paper_id)
        if (
            not isinstance(record, dict)
            or "pmc_full_text_id" not in record
            or record.get("pmc_full_text_id") != pmc_ids.get(paper_id)
        ):
            raise ValueError(
                "Returned PMC link identity differs from batch ELink proof"
            )


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
    study_version: int,
    blind_items: list[dict[str, Any]],
    event: dict[str, Any],
    study4_recovery_accounting: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    registration = _study_registration(study_version)
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
            endpoint,
            serving_process,
            cache_root,
            expected_build_id,
            expected_study_id=STUDY4_IDENTITY if study_version == 4 else None,
            expected_metadata_batch=registration.requires_batch_metadata,
        )
        papers = await fixture._search_papers_for_hypothesis(
            query, context, max_papers=MAX_PAPERS
        )
        _require_same_serving_process(
            endpoint,
            serving_process,
            cache_root,
            expected_build_id,
            expected_study_id=STUDY4_IDENTITY if study_version == 4 else None,
            expected_metadata_batch=registration.requires_batch_metadata,
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
    batch_raw_trace: dict[str, Any] | None = None
    batch_trace_attestation: dict[str, Any] | None = None
    batch_trace_error: Exception | None = None
    if registration.requires_batch_metadata and error is None:
        try:
            trace_path = fixture._trace_path(cache_root, slug, slug)
            batch_raw_trace = json.loads(trace_path.read_text(encoding="utf-8"))
            batch_returned_ids = (
                [str(pmid) for pmid in payload] if isinstance(payload, dict) else []
            )
            batch_trace_attestation = batch_trace_reader.validate_batch_trace(
                batch_raw_trace,
                run_id=slug,
                expected_build_id=expected_build_id,
                serving_process=serving_process,
                returned_ids=batch_returned_ids,
            )
            _validate_batch_returned_links(batch_raw_trace, records, batch_returned_ids)
        except Exception as exc:
            batch_trace_error = exc
            error = error or exc
    if registration.requires_batch_metadata and error is not None:
        papers = {}
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
        if _study_registration(study_version).requires_raw_trace:
            raw_trace = batch_raw_trace or json.loads(
                fixture._trace_path(cache_root, slug, slug).read_text(encoding="utf-8")
            )
            raw_fields = [
                "run_id",
                "server_build_id",
                "process_id",
                "source_file",
                "sort",
                "entrez_retry_policy",
                "entrez_calls",
                "incomplete_fetch_count",
                "fetch_errors",
                "metadata_origins",
                "attempts",
                "selected",
                "pre_search_shared_pool",
                "fetched",
                "final_ids",
                "shared_pool_supplements",
                "error",
                "outcome",
            ]
            if study_version == 4:
                raw_fields += (
                    "entrez_recovery",
                    "recovered_transient_attempts",
                    "entrez_recovery_call_outcomes",
                )
            if registration.requires_batch_metadata:
                raw_fields += ("metadata_batching",)
                if batch_trace_error is not None:
                    raise batch_trace_error
                if "metadata_batching" in raw_trace:
                    event["trace"]["metadata_batching"] = raw_trace["metadata_batching"]
            event["trace_attestation"] = {key: raw_trace.get(key) for key in raw_fields}
            returned_ids: list[str] | None = (
                [str(pmid) for pmid in payload] if isinstance(payload, dict) else None
            )
            if registration.requires_batch_metadata:
                if batch_trace_attestation is None:
                    raise ValueError(
                        f"Study {study_version} batch trace attestation is unavailable"
                    )
                event["trace_attestation"].update(batch_trace_attestation)
            else:
                event["trace_attestation"].update(
                    _validate_v2_trace(
                        raw_trace,
                        run_id=slug,
                        expected_build_id=expected_build_id,
                        serving_process=serving_process,
                        returned_ids=returned_ids,
                    )
                )
            if study_version == 4:
                if study4_recovery_accounting is None:
                    raise ValueError("Study 4 recovery accounting is unavailable")
                recovery_attestation = _validate_study4_recovery_trace(
                    raw_trace,
                    run_id=slug,
                    expected_build_id=expected_build_id,
                    serving_process=serving_process,
                    study_retries_used_so_far=study4_recovery_accounting[
                        "retries_used"
                    ],
                )
                event["trace_attestation"].update(recovery_attestation)
                _accumulate_study4_recovery(
                    study4_recovery_accounting, recovery_attestation
                )
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


def _validate_v2_trace(
    trace: dict[str, Any],
    *,
    run_id: str,
    expected_build_id: str,
    serving_process: dict[str, Any],
    returned_ids: list[str] | None,
) -> dict[str, Any]:
    """Check prospective raw fields omitted by the unchanged v1 reader."""

    def reject() -> None:
        raise ValueError(
            "Prospective PubMed trace attestation is incomplete or inconsistent"
        )

    if (
        trace.get("run_id") != run_id
        or trace.get("server_build_id") != expected_build_id
        or trace.get("process_id") != serving_process.get("pid")
        or trace.get("source_file")
        != str((ROOT / "engine/mcp_server/pubmed_client.py").resolve())
        or trace.get("sort") != "pub_date"
        or "error" not in trace
        or trace["error"] is not None
        or trace.get("outcome") not in {"nonempty", "empty"}
    ):
        reject()
    retry_policy = trace.get("entrez_retry_policy")
    if retry_policy != {"max_tries": 1, "sleep_between_tries": 0}:
        reject()
    calls = trace.get("entrez_calls")
    if not isinstance(calls, dict) or set(calls) != {"esearch", "efetch", "elink"}:
        reject()
    if any(type(value) is not int or value < 0 for value in calls.values()):
        reject()

    attempts = trace.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
        reject()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            reject()
        ids = attempt.get("first_ids")
        if (
            attempt.get("operation") != "esearch"
            or attempt.get("sort") != "pub_date"
            or "error_type" in attempt
            or type(attempt.get("count")) is not int
            or not isinstance(ids, list)
            or attempt["count"] != len(ids)
        ):
            reject()
    if calls["esearch"] != len(attempts):
        reject()

    selected = trace.get("selected")
    if selected is None:
        selected_ids: list[str] = []
        if any(attempt["count"] for attempt in attempts):
            reject()
    elif isinstance(selected, dict):
        selected_ids = selected.get("ids")
        if (
            not isinstance(selected_ids, list)
            or not selected_ids
            or len(selected_ids) > 9
            or any(
                not isinstance(pmid, str) or not pmid.isdecimal()
                for pmid in selected_ids
            )
            or len(set(selected_ids)) != len(selected_ids)
            or selected.get("sort") != "pub_date"
            or type(selected.get("count")) is not int
            or selected["count"] != len(selected_ids)
        ):
            reject()
        matches = [
            attempt
            for attempt in attempts
            if attempt.get("rung_index") == selected.get("rung_index")
            and attempt.get("rung_type") == selected.get("rung_type")
        ]
        if len(matches) != 1 or matches[0]["first_ids"] != selected_ids:
            reject()
    else:
        reject()

    pool = trace.get("pre_search_shared_pool")
    pool_ids = pool.get("first_ids") if isinstance(pool, dict) else None
    if (
        not isinstance(pool, dict)
        or type(pool.get("file_count")) is not int
        or type(pool.get("metadata_count")) is not int
        or pool["file_count"] < pool["metadata_count"]
        or pool["file_count"] != 0
        or pool["metadata_count"] != 0
        or not isinstance(pool_ids, list)
        or pool_ids
        or trace.get("shared_pool_supplements") != []
    ):
        reject()

    errors = trace.get("fetch_errors")
    incomplete = trace.get("incomplete_fetch_count")
    if (
        not isinstance(errors, list)
        or errors
        or type(incomplete) is not int
        or incomplete != 0
    ):
        reject()
    fetched = trace.get("fetched")
    origins = trace.get("metadata_origins")
    if (
        not isinstance(fetched, list)
        or len(fetched) != len(selected_ids)
        or not isinstance(origins, dict)
        or set(origins) != set(selected_ids)
        or [row.get("pmid") for row in fetched if isinstance(row, dict)] != selected_ids
    ):
        reject()
    fresh = 0
    for row in fetched:
        if (
            not isinstance(row, dict)
            or row.get("fetched") is not True
            or row.get("incomplete") is not False
            or row.get("metadata_origin") != origins.get(row.get("pmid"))
        ):
            reject()
        if row["metadata_origin"] == "entrez_fetch":
            fresh += 1
        else:
            reject()
    if fresh != len(selected_ids):
        reject()

    final_ids = trace.get("final_ids")
    if (
        not isinstance(final_ids, list)
        or len(final_ids) > MAX_PAPERS
        or any(not isinstance(pmid, str) or not pmid.isdecimal() for pmid in final_ids)
        or final_ids != (returned_ids if returned_ids is not None else [])
        or (trace["outcome"] == "nonempty") != bool(final_ids)
        or calls["elink"] != fresh
        or calls["efetch"] < fresh
    ):
        reject()
    return {
        "entrez_retry_policy": retry_policy,
        "entrez_calls": calls,
        "incomplete_fetch_count": incomplete,
        "fetch_errors": errors,
        "metadata_origins": origins,
        "count_semantics": {
            "attempts": "application-level ESearch rungs",
            "entrez_calls": "maintained Entrez entrypoint invocations; PMC fulltext EFetch may paginate; not physical HTTP requests",
        },
    }


def _validate_study4_recovery_trace(
    trace: dict[str, Any],
    *,
    run_id: str,
    expected_build_id: str,
    serving_process: dict[str, Any],
    study_retries_used_so_far: int,
) -> dict[str, Any]:
    """Validate and return one bounded v4 retry ledger delta."""

    def reject() -> None:
        raise ValueError("Study 4 Entrez recovery trace is incomplete or inconsistent")

    def parse_retry_after(value: str) -> tuple[str, float | None]:
        value = value.strip()
        if value.isascii() and value.isdecimal():
            try:
                seconds = int(value)
            except ValueError:
                return "invalid", None
            return "seconds", float(seconds)
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return "invalid", None
        return ("date", None) if parsed is not None else ("invalid", None)

    recovery = trace.get("entrez_recovery")
    if (
        trace.get("run_id") != run_id
        or trace.get("server_build_id") != expected_build_id
        or trace.get("process_id") != serving_process.get("pid")
        or not isinstance(recovery, dict)
        or recovery.get("study_id") != STUDY4_IDENTITY
        or recovery.get("policy") != STUDY4_RECOVERY_POLICY
        or recovery.get("max_retries_per_logical_request")
        != STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST
        or recovery.get("max_retries_per_study") != STUDY4_MAX_RETRIES_PER_STUDY
    ):
        reject()

    calls = trace.get("entrez_calls")
    client_attempts = recovery.get("client_entry_attempts")
    if (
        not isinstance(calls, dict)
        or set(calls) != _STUDY4_OPERATIONS
        or any(type(count) is not int or count < 0 for count in calls.values())
        or not isinstance(client_attempts, dict)
        or set(client_attempts) != _STUDY4_OPERATIONS
        or any(
            type(count) is not int or count < 0 for count in client_attempts.values()
        )
    ):
        reject()

    counters = {
        name: recovery.get(name)
        for name in ("retries_used", "recovered_calls", "exhausted_calls")
    }
    if any(type(value) is not int or value < 0 for value in counters.values()):
        reject()
    process_start = recovery.get("process_retries_used_at_start")
    process_end = recovery.get("process_retries_used_at_end")
    if (
        type(study_retries_used_so_far) is not int
        or not 0 <= study_retries_used_so_far <= STUDY4_MAX_RETRIES_PER_STUDY
        or type(process_start) is not int
        or type(process_end) is not int
        or not 0 <= process_start <= process_end
        or process_end > STUDY4_MAX_RETRIES_PER_STUDY
        or counters["retries_used"] > process_end - process_start
        or study_retries_used_so_far + counters["retries_used"]
        > STUDY4_MAX_RETRIES_PER_STUDY
    ):
        reject()

    attempts = trace.get("recovered_transient_attempts")
    outcomes = trace.get("entrez_recovery_call_outcomes")
    total_logical_calls = sum(calls.values())
    if (
        not isinstance(attempts, list)
        or len(attempts)
        > min(
            STUDY4_MAX_TRACE_RECOVERY_ROWS,
            total_logical_calls * (STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST + 1),
        )
        or not isinstance(outcomes, list)
        or len(outcomes) > min(STUDY4_MAX_TRACE_RECOVERY_ROWS, total_logical_calls)
    ):
        reject()

    outcome_by_request: dict[tuple[str, int], dict[str, Any]] = {}
    recovered_calls = 0
    exhausted_calls = 0
    retries_used = 0
    for row in outcomes:
        if not isinstance(row, dict):
            reject()
        operation = row.get("operation")
        ordinal = row.get("logical_request_ordinal")
        if (
            not isinstance(operation, str)
            or operation not in _STUDY4_OPERATIONS
            or type(ordinal) is not int
        ):
            reject()
        retry_count = row.get("retry_count")
        entry_count = row.get("client_entry_attempts")
        final_outcome = row.get("final_outcome")
        key = (operation, ordinal)
        if (
            row.get("study_id") != STUDY4_IDENTITY
            or row.get("run_id") != run_id
            or not 1 <= ordinal <= calls[operation]
            or key in outcome_by_request
            or type(retry_count) is not int
            or retry_count not in {0, STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST}
            or type(entry_count) is not int
            or entry_count != 1 + retry_count
            or not isinstance(final_outcome, str)
            or final_outcome not in _STUDY4_RECOVERY_OUTCOMES
        ):
            reject()
        if final_outcome in {"recovered", "exhausted"} and retry_count != 1:
            reject()
        if final_outcome == "recovered":
            recovered_calls += 1
        else:
            exhausted_calls += 1
        retries_used += retry_count
        outcome_by_request[key] = row

    if (
        counters["retries_used"] != retries_used
        or counters["recovered_calls"] != recovered_calls
        or counters["exhausted_calls"] != exhausted_calls
        or recovered_calls + exhausted_calls != len(outcomes)
    ):
        reject()

    attempts_by_request: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in attempts:
        if not isinstance(row, dict):
            reject()
        operation = row.get("operation")
        ordinal = row.get("logical_request_ordinal")
        attempt_ordinal = row.get("attempt_ordinal")
        status = row.get("http_status")
        wait_seconds = row.get("wait_seconds")
        retry_after = row.get("retry_after_value")
        retry_after_raw_prefix = row.get("retry_after_raw_prefix")
        retry_after_raw_truncated = row.get("retry_after_raw_truncated")
        if (
            not isinstance(operation, str)
            or operation not in _STUDY4_OPERATIONS
            or type(ordinal) is not int
        ):
            reject()
        key = (operation, ordinal)
        if (
            row.get("study_id") != STUDY4_IDENTITY
            or row.get("run_id") != run_id
            or row.get("server_build_id") != expected_build_id
            or row.get("process_id") != serving_process.get("pid")
            or not 1 <= ordinal <= calls[operation]
            or type(attempt_ordinal) is not int
            or attempt_ordinal not in {1, 2}
            or type(status) is not int
            or status not in STUDY4_RETRYABLE_HTTP_STATUSES
            or isinstance(wait_seconds, bool)
            or not isinstance(wait_seconds, (int, float))
            or not 0 <= wait_seconds <= STUDY4_RETRY_AFTER_MAX_SECONDS
            or (
                retry_after is not None
                and (
                    not isinstance(retry_after, str)
                    or len(retry_after) > 128
                    or any(
                        ord(char) != 9 and not 32 <= ord(char) <= 126
                        for char in retry_after
                    )
                )
            )
            or type(retry_after_raw_truncated) is not bool
            or (
                retry_after_raw_prefix is not None
                and (
                    not isinstance(retry_after_raw_prefix, str)
                    or len(retry_after_raw_prefix) > 128
                )
            )
            or (retry_after is None) != (retry_after_raw_prefix is None)
        ):
            reject()
        attempts_by_request.setdefault(key, []).append(row)

    for operation in _STUDY4_OPERATION_ORDER:
        expected_entries = calls[operation] + sum(
            row["retry_count"]
            for (row_operation, _), row in outcome_by_request.items()
            if row_operation == operation
        )
        if client_attempts[operation] != expected_entries:
            reject()

    for key, row in outcome_by_request.items():
        request_attempts = attempts_by_request.pop(key, [])
        ordinals = [attempt.get("attempt_ordinal") for attempt in request_attempts]
        final_outcome = row["final_outcome"]
        if (
            not request_attempts
            or ordinals != list(range(1, len(ordinals) + 1))
            or len(ordinals) > row["client_entry_attempts"]
            or row["client_entry_attempts"] != 1 + row["retry_count"]
            or any(
                attempt.get("outcome") != final_outcome for attempt in request_attempts
            )
        ):
            reject()
        if final_outcome == "recovered" and ordinals != [1]:
            reject()
        retry_count = row["retry_count"]
        for index, attempt in enumerate(request_attempts):
            retry_was_issued = index < retry_count
            retry_after = attempt.get("retry_after_value")
            wait_seconds = attempt.get("wait_seconds")
            if not retry_was_issued:
                if wait_seconds != 0:
                    reject()
                continue
            if retry_after is None:
                if wait_seconds != STUDY4_RETRY_AFTER_DEFAULT_SECONDS:
                    reject()
                continue
            retry_after_kind, requested_wait = parse_retry_after(retry_after)
            if retry_after_kind == "seconds":
                if (
                    requested_wait is None
                    or requested_wait > STUDY4_RETRY_AFTER_MAX_SECONDS
                ):
                    reject()
                if wait_seconds != requested_wait:
                    reject()
            elif retry_after_kind == "date":
                if wait_seconds > STUDY4_RETRY_AFTER_MAX_SECONDS:
                    reject()
            elif wait_seconds != STUDY4_RETRY_AFTER_DEFAULT_SECONDS:
                reject()
        final_attempt = request_attempts[-1]
        final_retry_after = final_attempt.get("retry_after_value")
        final_kind, final_delay = (
            parse_retry_after(final_retry_after)
            if isinstance(final_retry_after, str)
            else ("missing", None)
        )
        if final_kind == "seconds":
            if final_delay is not None and final_delay > STUDY4_RETRY_AFTER_MAX_SECONDS:
                if final_outcome != "retry_after_over_cap":
                    reject()
            elif final_outcome == "retry_after_over_cap":
                reject()
        if final_kind == "invalid" and final_outcome == "retry_after_over_cap":
            reject()

    if attempts_by_request:
        reject()
    if any(row["final_outcome"] != "recovered" for row in outcomes):
        reject()
    return {
        "entrez_recovery": recovery,
        "recovered_transient_attempts": attempts,
        "entrez_recovery_call_outcomes": outcomes,
    }


def _accumulate_study4_recovery(
    accounting: dict[str, Any], attestation: dict[str, Any]
) -> None:
    recovery = attestation["entrez_recovery"]
    if (
        recovery["process_retries_used_at_start"]
        != accounting["process_retries_used_at_end"]
        or recovery["process_retries_used_at_end"]
        != recovery["process_retries_used_at_start"] + recovery["retries_used"]
        or accounting["retries_used"] + recovery["retries_used"]
        > STUDY4_MAX_RETRIES_PER_STUDY
    ):
        raise ValueError("Study 4 Entrez process budget changed between pilot traces")
    accounting["retries_used"] += recovery["retries_used"]
    accounting["recovered_calls"] += recovery["recovered_calls"]
    accounting["exhausted_calls"] += recovery["exhausted_calls"]
    for operation in _STUDY4_OPERATION_ORDER:
        accounting["client_entry_attempts"][operation] += recovery[
            "client_entry_attempts"
        ][operation]
    accounting["process_retries_used_at_end"] = recovery["process_retries_used_at_end"]
    accounting["recovered_transient_attempts"].extend(
        attestation["recovered_transient_attempts"]
    )
    accounting["entrez_recovery_call_outcomes"].extend(
        attestation["entrez_recovery_call_outcomes"]
    )


def _validate_complete_study4_recovery(accounting: dict[str, Any]) -> None:
    attempts = accounting["recovered_transient_attempts"]
    outcomes = accounting["entrez_recovery_call_outcomes"]
    recovered = sum(row.get("final_outcome") == "recovered" for row in outcomes)
    exhausted = sum(row.get("final_outcome") != "recovered" for row in outcomes)
    retries = sum(row.get("retry_count", 0) for row in outcomes)
    if (
        accounting["study_id"] != STUDY4_IDENTITY
        or accounting["policy"] != STUDY4_RECOVERY_POLICY
        or accounting["process_retries_used_at_start"] != 0
        or accounting["process_retries_used_at_end"] != accounting["retries_used"]
        or accounting["retries_used"] > STUDY4_MAX_RETRIES_PER_STUDY
        or retries != accounting["retries_used"]
        or accounting["process_retries_used_at_end"] != retries
        or recovered != accounting["recovered_calls"]
        or exhausted != accounting["exhausted_calls"]
        or len(attempts) < len(outcomes)
        or len(attempts) > 2 * len(outcomes)
        or any(row.get("final_outcome") != "recovered" for row in outcomes)
        or not isinstance(accounting.get("client_entry_attempts"), dict)
        or set(accounting["client_entry_attempts"]) != _STUDY4_OPERATIONS
        or any(
            type(value) is not int or value < 0
            for value in accounting["client_entry_attempts"].values()
        )
    ):
        raise ValueError("Study 4 Entrez recovery accounting is incomplete")


def _require_empty_pilot_cache(cache_root: Path) -> None:
    if cache_root.is_symlink() or not cache_root.is_absolute():
        raise ValueError("Pilot cache must be absolute and not a symlink")
    if not cache_root.is_dir() or any(cache_root.iterdir()):
        raise ValueError("Pilot cache must exist and start empty")


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
    study_version: int = 1,
) -> dict[str, Any]:
    """Run all six frozen pairs using the maintained search and LLM seams."""
    registration = _study_registration(study_version)
    protocol = (
        _load_pilot_protocol()
        if study_version == 1
        else _load_pilot_protocol(study_version)
    )
    query_output_format = _query_output_format(protocol, study_version)
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
    _require_empty_pilot_cache(cache_root)
    if fixture_prereg != _load_fixture_bank(protocol, study_version):
        raise ValueError(
            "Pilot must use the complete frozen v1 fixture bank"
            if study_version == 1
            else "Pilot must use the complete committed fixture bank"
        )
    pairs = _pilot_pairs(fixture_prereg, study_version)
    if not model_name or not model_api_key:
        raise ValueError("A selected model and explicit model API key are required")
    tool = _pilot_search_tool(registry)
    source_ids = _validate_pilot_drafts(fixture_prereg, pairs)

    admission_path = _claim_campaign_admission(protocol, study_version)
    recorder = (
        client
        if isinstance(client, fixture._RecordingClient)
        else fixture._RecordingClient(client)
    )
    if study_version in (8, 9):
        recorder = _MetadataOnlySearchClient(recorder, study_version)
    parser = ResponseParser(tool)
    nonce = uuid.uuid4().hex[:12]
    bank_hash = (
        protocol["fixture_bank_sha256"]
        if registration.fixture_bank_version is not None
        else fixture._bank_config(1)["sha256"]
    )
    report: dict[str, Any] = {
        "name": registration.report_name,
        "status": "RUNNING",
        "fixture_bank_sha256": bank_hash,
        "selected_model": model_name,
        "model_call_count": 0,
        "provider_call_count": 0,
        "outer_mcp_call_count": 0,
        "paid_calls": 0,
        "max_model_calls": MODEL_CALL_LIMIT,
        "max_outer_mcp_calls": OUTER_MCP_CALL_LIMIT,
        "max_papers_per_search": MAX_PAPERS,
        "model_request_config": MODEL_REQUEST_CONFIG,
        "query_output_format": query_output_format,
        "campaign_admission": str(admission_path),
        "mcp_serving_process": serving_process,
        "events": [],
    }
    if registration.fixture_bank_version is not None:
        report.update(
            {
                "study_version": study_version,
                "fixture_bank_version": registration.fixture_bank_version,
                "protocol_version": registration.protocol_version,
            }
        )
    study4_recovery_accounting: dict[str, Any] | None = None
    if study_version == 4:
        study4_recovery_accounting = {
            "study_id": STUDY4_IDENTITY,
            "policy": STUDY4_RECOVERY_POLICY,
            "max_retries_per_logical_request": STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST,
            "max_retries_per_study": STUDY4_MAX_RETRIES_PER_STUDY,
            "retries_used": 0,
            "recovered_calls": 0,
            "exhausted_calls": 0,
            "client_entry_attempts": {
                operation: 0 for operation in _STUDY4_OPERATION_ORDER
            },
            "process_retries_used_at_start": 0,
            "process_retries_used_at_end": 0,
            "recovered_transient_attempts": [],
            "entrez_recovery_call_outcomes": [],
        }
        report["entrez_recovery_accounting"] = study4_recovery_accounting
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
            prompt = _prompt(
                variant,
                draft,
                papers,
                output_format=query_output_format,
                study_version=study_version,
            )
            if _contains_source_id(prompt, source_ids):
                raise ValueError("Model prompt contains a frozen target or anchor PMID")
            if registration.requires_batch_metadata:
                _require_same_serving_process(
                    endpoint,
                    serving_process,
                    cache_root,
                    expected_build_id,
                    expected_metadata_batch=True,
                )
            query = await _generate_query(
                prompt,
                model_name=model_name,
                model_api_key=model_api_key,
                run_id=(
                    f"m11_nov_01a3b3_{nonce}_{report['model_call_count']:02d}"
                    if study_version == 1
                    else f"m12_nov_v{study_version}_{nonce}_{report['model_call_count']:02d}"
                ),
                expected_source_ids=source_ids,
                event=event,
                output_format=query_output_format,
            )
            if registration.requires_batch_metadata:
                _require_same_serving_process(
                    endpoint,
                    serving_process,
                    cache_root,
                    expected_build_id,
                    expected_metadata_batch=True,
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
            study_version=study_version,
            blind_items=blind_packet["items"],
            event=event,
            study4_recovery_accounting=study4_recovery_accounting,
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
        if registration.requires_batch_metadata:
            _require_same_serving_process(
                endpoint,
                serving_process,
                cache_root,
                expected_build_id,
                expected_metadata_batch=True,
            )
        await client.initialize()
        if registration.requires_batch_metadata:
            _require_same_serving_process(
                endpoint,
                serving_process,
                cache_root,
                expected_build_id,
                expected_metadata_batch=True,
            )
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
        if study4_recovery_accounting is not None:
            _validate_complete_study4_recovery(study4_recovery_accounting)
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


def _claim_campaign_admission(protocol: dict[str, Any], study_version: int = 1) -> Path:
    """Persist the campaign's one-shot claim before its first external call."""
    _study_registration(study_version)
    path = _protocol_path(study_version).with_suffix(".admission.json")
    receipt = {
        "status": "CLAIMED",
        "claimed_at_utc": _now(),
        "protocol_sha256": hashlib.sha256(
            _protocol_path(study_version).read_bytes()
        ).hexdigest(),
        "model_name": protocol["model_name"],
        "max_model_calls": MODEL_CALL_LIMIT,
        "max_outer_mcp_calls": OUTER_MCP_CALL_LIMIT,
    }
    if study_version != 1:
        receipt["study_version"] = study_version
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


def _committed_file_bytes(path: Path, label: str) -> bytes:
    try:
        relative_path = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must be committed unchanged") from exc
    committed = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if committed.returncode:
        raise ValueError(f"{label} must be committed unchanged")
    return committed.stdout


def _committed_protocol_bytes(path: Path) -> bytes:
    return _committed_file_bytes(path, "Pilot protocol")


def _protocol_path(study_version: int) -> Path:
    _study_registration(study_version)
    return {
        1: PILOT_PREREG,
        2: PILOT_PREREG_V2,
        3: PILOT_PREREG_V3,
        4: PILOT_PREREG_V4,
        5: PILOT_PREREG_V5,
        6: PILOT_PREREG_V6,
        7: PILOT_PREREG_V7,
        8: PILOT_PREREG_V8,
        9: PILOT_PREREG_V9,
    }[study_version]


def _study_registration(study_version: int) -> _StudyRegistration:
    try:
        return _STUDY_REGISTRATIONS[study_version]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported result-conditioned pilot study version: {study_version}"
        ) from exc


def _load_fixture_bank(
    protocol: dict[str, Any],
    study_version: int,
    *,
    preflight_bank_path: Path | None = None,
) -> dict[str, Any]:
    registration = _study_registration(study_version)
    if registration.fixture_bank_version is None:
        return fixture._load_preregistration(1)
    if (
        protocol.get("study_version") != study_version
        or protocol.get("protocol_version") != registration.protocol_version
        or protocol.get("fixture_bank_version") != registration.fixture_bank_version
        or protocol.get("fixture_bank_path") != registration.fixture_bank_path
    ):
        raise ValueError(
            f"Prospective protocol must bind fixture bank version {registration.fixture_bank_version}"
        )
    assert registration.fixture_bank_path is not None
    assert registration.fixture_bank_status is not None
    if preflight_bank_path is not None:
        if not registration.requires_batch_metadata:
            raise ValueError(
                "Temporary fixture preflight is available only for batch-aware studies"
            )
        path = preflight_bank_path.expanduser().resolve()
        if path.is_relative_to(ROOT.resolve()):
            raise ValueError(
                "Temporary preflight fixture must stay outside the repository"
            )
    else:
        path = ROOT / registration.fixture_bank_path
    bank_bytes = path.read_bytes()
    if (
        preflight_bank_path is None
        and _committed_file_bytes(path, "Fixture bank") != bank_bytes
    ):
        raise ValueError("Fixture bank must be committed unchanged")
    bank_hash = hashlib.sha256(bank_bytes).hexdigest()
    if protocol.get("fixture_bank_sha256") != bank_hash:
        raise ValueError("Prospective protocol names a different fixture bank")
    bank = json.loads(bank_bytes)
    expected_status = (
        OFFLINE_PREFLIGHT_BANK_STATUS
        if preflight_bank_path is not None
        else registration.fixture_bank_status
    )
    if (
        bank.get("version") != registration.fixture_bank_version
        or bank.get("status") != expected_status
    ):
        raise ValueError(
            f"Fixture bank version {registration.fixture_bank_version} is not preregistered"
        )
    return bank


def _model_boundary_hashes(study_version: int | None = None) -> dict[str, str]:
    files = MODEL_BOUNDARY_FILES
    if (
        study_version is not None
        and _study_registration(study_version).query_output_format
        == PLAIN_TEXT_QUERY_OUTPUT_FORMAT
    ):
        files += PLAIN_TEXT_MODEL_BOUNDARY_FILES
    return {
        relative: fixture._sha256(ROOT / relative) for relative in files
    }


def _batch_trace_source_hashes() -> dict[str, str]:
    return {
        relative: fixture._sha256(ROOT / relative)
        for relative in BATCH_TRACE_SOURCE_FILES
    }


def _load_pilot_protocol(
    study_version: int = 1,
    *,
    preflight_protocol_path: Path | None = None,
    preflight_bank_path: Path | None = None,
) -> dict[str, Any]:
    registration = _study_registration(study_version)
    if (preflight_protocol_path is None) != (preflight_bank_path is None):
        raise ValueError("Temporary preflight requires both protocol and fixture paths")
    if preflight_protocol_path is not None:
        if not registration.requires_batch_metadata:
            raise ValueError(
                "Temporary protocol preflight is available only for batch-aware studies"
            )
        prereg_path = preflight_protocol_path.expanduser().resolve()
        if prereg_path.is_relative_to(ROOT.resolve()):
            raise ValueError(
                "Temporary preflight protocol must stay outside the repository"
            )
    else:
        prereg_path = _protocol_path(study_version)
    if not prereg_path.is_file():
        raise ValueError("Pilot is disabled until its protocol is preregistered")
    protocol_bytes = prereg_path.read_bytes()
    if (
        preflight_protocol_path is None
        and _committed_protocol_bytes(prereg_path) != protocol_bytes
    ):
        raise ValueError("Pilot protocol must be committed unchanged")
    protocol = json.loads(protocol_bytes)
    if preflight_protocol_path is not None:
        if protocol.get("status") != OFFLINE_PREFLIGHT_BANK_STATUS:
            raise ValueError(
                "Temporary preflight protocol is not explicitly unregistered"
            )
    elif protocol.get("status") != "PREREGISTERED_BEFORE_ANY_PILOT_CALL":
        raise ValueError("Pilot protocol is not preregistered")
    if registration.fixture_bank_version is None:
        if protocol.get("fixture_bank_sha256") != fixture._bank_config(1)["sha256"]:
            raise ValueError("Pilot protocol names a different frozen fixture bank")
    elif (
        protocol.get("study_version") != study_version
        or protocol.get("protocol_version") != registration.protocol_version
        or protocol.get("fixture_bank_version") != registration.fixture_bank_version
    ):
        raise ValueError("Pilot protocol does not select the prospective study version")
    _validate_search_parameters(protocol, study_version)
    output_format = _query_output_format(protocol, study_version)
    if study_version == 4 and protocol.get("entrez_recovery_policy") != dict(
        STUDY4_RECOVERY_PROTOCOL
    ):
        raise ValueError("Study 4 protocol does not pin the Entrez recovery policy")
    if (
        protocol.get("runner_sha256")
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("Pilot runner changed after preregistration")
    static_prompt, conditioned_prompt = _query_prompt_templates(
        output_format, study_version=study_version
    )
    if (
        protocol.get("static_prompt_sha256")
        != hashlib.sha256(static_prompt.encode()).hexdigest()
    ):
        raise ValueError("Static prompt changed after preregistration")
    if (
        protocol.get("conditioned_prompt_sha256")
        != hashlib.sha256(conditioned_prompt.encode()).hexdigest()
    ):
        raise ValueError("Conditioned prompt changed after preregistration")
    if protocol.get("request_config") != MODEL_REQUEST_CONFIG:
        raise ValueError("Pilot request settings differ from preregistration")
    if protocol.get("model_boundary_sha256") != _model_boundary_hashes(study_version):
        raise ValueError(
            "Pilot model admission/dispatch sources changed or are unpinned"
        )
    if (
        registration.requires_batch_metadata
        and protocol.get("batch_trace_source_sha256") != _batch_trace_source_hashes()
    ):
        raise ValueError(
            f"Study {study_version} batch reader or producer sources changed or are unpinned"
        )
    if (
        protocol.get("max_outer_mcp_calls") != OUTER_MCP_CALL_LIMIT
        or protocol.get("max_model_calls") != MODEL_CALL_LIMIT
    ):
        raise ValueError("Pilot call bounds differ from preregistration")
    if not isinstance(protocol.get("model_name"), str) or not protocol["model_name"]:
        raise ValueError("Pilot protocol does not select a model")
    if registration.fixture_bank_version is not None:
        _load_fixture_bank(
            protocol,
            study_version,
            preflight_bank_path=preflight_bank_path,
        )
    return protocol


def _study5_batch_environment_matches(environment: Mapping[str, str]) -> bool:
    return (
        environment.get(BATCH_METADATA_ENV) == "1"
        and environment.get(STUDY4_RECOVERY_ENV) in {None, "0"}
        and STUDY_ID_ENV not in environment
    )


_batch_metadata_environment_matches = _study5_batch_environment_matches


def _check_mcp_process(
    endpoint: str,
    *,
    expected_secret: str,
    expected_build_id: str,
    cache_root: Path,
    expected_study_id: str | None = None,
    expected_metadata_batch: bool = False,
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
    process_snapshot = subprocess.run(
        ["ps", "eww", "-p", pid],
        capture_output=True,
        text=True,
        check=False,
    )
    if process_snapshot.returncode != 0:
        raise ValueError("MCP process environment could not be attested")
    environment = dict(
        re.findall(
            r"(?<!\S)([A-Za-z_][A-Za-z0-9_]*)=([^\s]*)",
            process_snapshot.stdout,
        )
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
        "mcp_server.server:app" not in process_snapshot.stdout
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
    if expected_metadata_batch and not _batch_metadata_environment_matches(environment):
        raise ValueError(
            "MCP process batching or recovery settings differ from the study protocol"
        )
    process = {
        "pid": int(pid),
        "listener_address": addresses[0],
        "source_path": str(source_path),
        "mcp_tree": source_tree,
    }
    if expected_metadata_batch:
        process["metadata_batching"] = {"enabled": True}
        process["study4_recovery_enabled"] = False
        process["study_id"] = None
    if expected_study_id is not None:
        if (
            expected_study_id != STUDY4_IDENTITY
            or environment.get(STUDY4_RECOVERY_ENV) != "1"
            or environment.get(STUDY_ID_ENV) != expected_study_id
        ):
            raise ValueError(
                "MCP process study recovery binding differs from the protocol"
            )
        process["study4_recovery"] = {
            "enabled": True,
            "study_id": expected_study_id,
        }
    return process


def _require_same_serving_process(
    endpoint: str,
    expected: dict[str, Any],
    cache_root: Path,
    expected_build_id: str,
    expected_study_id: str | None = None,
    expected_metadata_batch: bool = False,
) -> None:
    actual = _check_mcp_process(
        endpoint,
        expected_secret=os.environ[fixture.MCP_SECRET_ENV],
        expected_build_id=expected_build_id,
        cache_root=cache_root,
        expected_study_id=expected_study_id,
        expected_metadata_batch=expected_metadata_batch,
    )
    if actual != expected:
        raise ValueError("MCP serving process changed during the pilot")


def _check_runtime(
    protocol: dict[str, Any],
    fixture_prereg: dict[str, Any],
    *,
    cache_root: Path,
) -> tuple[str, Path, str, dict[str, Any]]:
    study_version = protocol.get("study_version", 1)
    registration = _study_registration(study_version)
    expected_study_id: str | None = None
    if study_version == 4:
        if protocol.get("entrez_recovery_policy") != dict(STUDY4_RECOVERY_PROTOCOL):
            raise ValueError(
                "Study 4 recovery policy differs from the committed protocol"
            )
        if (
            os.environ.get(STUDY4_RECOVERY_ENV) != "1"
            or os.environ.get(STUDY_ID_ENV) != STUDY4_IDENTITY
            or os.environ.get("COSCIENTIST_PUBMED_PILOT_TRACE") != "1"
        ):
            raise ValueError(
                "Study 4 recovery activation differs from the committed protocol"
            )
        expected_study_id = STUDY4_IDENTITY
    expected_metadata_batch = registration.requires_batch_metadata
    if expected_metadata_batch and not _batch_metadata_environment_matches(os.environ):
        raise ValueError(
            f"Study {study_version} requires batching and disables Study 4 recovery"
        )
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
    boundary = fixture_prereg.get("validation_boundary")
    bank_version = fixture_prereg.get("version")
    uses_current_boundary = (
        registration.fixture_bank_version is not None
        and registration.fixture_bank_version >= 4
    ) or (isinstance(bank_version, int) and bank_version >= 4)
    if uses_current_boundary:
        protocol_boundary = protocol.get("validation_boundary")
        if (
            registration.fixture_bank_version is None
            or protocol.get("study_version") != study_version
            or protocol.get("fixture_bank_version") != registration.fixture_bank_version
            or bank_version != registration.fixture_bank_version
            or not isinstance(protocol_boundary, dict)
            or not isinstance(boundary, dict)
        ):
            raise ValueError(
                f"Study {study_version} must bind the current v{registration.fixture_bank_version} validation boundary"
            )
        for path_key, hash_key, bank_path_key in (
            ("validator_path", "validator_sha256", "maintained_validator"),
            ("response_parser_path", "response_parser_sha256", "parser"),
            ("tool_config_path", "tool_config_sha256", "tool_config"),
        ):
            relative_path = protocol_boundary.get(path_key)
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or boundary.get(bank_path_key) != relative_path
            ):
                raise ValueError(
                    f"Study {study_version} validation source path differs from fixture bank: {path_key}"
                )
            expected_hash = protocol_boundary.get(hash_key)
            if not isinstance(expected_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_hash
            ):
                raise ValueError(
                    f"Study {study_version} validation source hash is missing or malformed: {path_key}"
                )
            if fixture._sha256(ROOT / relative_path) != expected_hash:
                raise ValueError(f"Frozen validation source changed: {relative_path}")
    else:
        # v1/v2 preregistrations carry these hashes on the fixture bank itself.
        for path_key, hash_key in (
            ("validator", "validator_sha256"),
            ("parser", "parser_sha256"),
            ("tool_config", "tool_config_sha256"),
        ):
            if fixture._sha256(ROOT / boundary[path_key]) != boundary[hash_key]:
                raise ValueError(
                    f"Frozen validator source changed: {boundary[path_key]}"
                )
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
        expected_study_id=expected_study_id,
        expected_metadata_batch=expected_metadata_batch,
    )
    return endpoint, cache_root, expected_build, serving_process


def _new_output_paths(study_version: int = 1) -> tuple[Path, Path]:
    registration = _study_registration(study_version)
    nonce = uuid.uuid4().hex
    return (
        RESULT_DIR / f"{registration.result_prefix}-{nonce[:12]}.json",
        Path("/tmp") / f"{registration.blind_prefix}-{nonce}.json",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study-version", type=int, choices=tuple(_STUDY_REGISTRATIONS), default=1
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--preflight-protocol", type=Path)
    parser.add_argument("--preflight-bank", type=Path)
    args = parser.parse_args(argv)
    has_temporary_input = (
        args.preflight_protocol is not None or args.preflight_bank is not None
    )
    if has_temporary_input and not args.preflight_only:
        parser.error("temporary protocol and fixture inputs require --preflight-only")
    if (
        args.preflight_only
        and not _study_registration(args.study_version).requires_batch_metadata
    ):
        parser.error("--preflight-only is available only for batch-aware studies")
    if args.preflight_only and (
        args.preflight_protocol is None or args.preflight_bank is None
    ):
        parser.error(
            "batch-aware study preflight requires --preflight-protocol and --preflight-bank"
        )
    return args


async def _main(
    study_version: int | None = None,
    *,
    preflight_only: bool = False,
    preflight_protocol: Path | None = None,
    preflight_bank: Path | None = None,
) -> int:
    if study_version is None:
        args = _parse_args()
        study_version = args.study_version
        preflight_only = args.preflight_only
        preflight_protocol = args.preflight_protocol
        preflight_bank = args.preflight_bank
    has_temporary_input = preflight_protocol is not None or preflight_bank is not None
    if has_temporary_input and not preflight_only:
        raise ValueError(
            "Temporary inputs are permitted only for batch-aware preflight"
        )
    if preflight_only and (preflight_protocol is None or preflight_bank is None):
        raise ValueError(
            "Temporary inputs are permitted only for batch-aware preflight"
        )
    if (
        preflight_only
        and not _study_registration(study_version).requires_batch_metadata
    ):
        raise ValueError(
            "Temporary protocol preflight is available only for batch-aware studies"
        )
    _study_registration(study_version)
    if preflight_only:
        protocol = _load_pilot_protocol(
            study_version,
            preflight_protocol_path=preflight_protocol,
            preflight_bank_path=preflight_bank,
        )
    else:
        protocol = (
            _load_pilot_protocol()
            if study_version == 1
            else _load_pilot_protocol(study_version)
        )
    fixture_prereg = (
        _load_fixture_bank(protocol, study_version, preflight_bank_path=preflight_bank)
        if preflight_only
        else _load_fixture_bank(protocol, study_version)
    )
    cache_root = Path(os.environ.get("COSCIENTIST_LIT_REVIEW_DIR", ""))
    if preflight_only:
        pairs = _pilot_pairs(fixture_prereg, study_version)
        registry = ToolRegistry(
            config_path=str(ROOT / TOOL_CONFIG), skip_user_config=True
        )
        _pilot_search_tool(registry)
        _validate_pilot_drafts(fixture_prereg, pairs)
        _require_empty_pilot_cache(cache_root)
        endpoint, checked_cache, expected_build, serving_process = _check_runtime(
            protocol, fixture_prereg, cache_root=cache_root
        )
        if checked_cache.resolve() != cache_root.resolve():
            raise ValueError("Pilot runtime changed the isolated cache root")
        print(
            json.dumps(
                {
                    "status": "OFFLINE_PREFLIGHT_ONLY_NOT_REGISTERED",
                    "study_version": study_version,
                    "endpoint": endpoint,
                    "mcp_build_id": expected_build,
                    "model_name": protocol["model_name"],
                    "serving_process": serving_process,
                    "cache_empty": True,
                    "admission_claimed": False,
                    "scientific_calls": 0,
                }
            )
        )
        return 0
    endpoint, cache_root, expected_build, _ = _check_runtime(
        protocol, fixture_prereg, cache_root=cache_root
    )
    model_api_key = os.environ.get("OPENROUTER_API_KEY")
    if not model_api_key:
        raise ValueError("Pass the OpenRouter model key to the runner explicitly")
    result_path, blind_path = (
        _new_output_paths() if study_version == 1 else _new_output_paths(study_version)
    )
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
        study_version=study_version,
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(
        _main(
            args.study_version,
            preflight_only=args.preflight_only,
            preflight_protocol=args.preflight_protocol,
            preflight_bank=args.preflight_bank,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
