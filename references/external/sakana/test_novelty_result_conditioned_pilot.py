"""Offline behavior tests for the matched result-conditioned search pilot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import novelty_fixture_bank_screen as screen
import novelty_result_conditioned_pilot as pilot
from co_scientist import llm_free_policy
from co_scientist.config.registry import ToolRegistry

MODEL = "openrouter/campaign/zero:free"
SERVED_MODEL = "campaign/zero:free"
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


class FakeMCPClient:
    def __init__(
        self,
        cache_root: Path,
        events: list[tuple[str, str]],
        *,
        fail_on_call: int | None = None,
        abstract_suffix: str = "",
        response_override: str | None = None,
        include_v2_trace: bool = False,
        incomplete_fetch: bool = False,
    ) -> None:
        self.cache_root = cache_root
        self.events = events
        self.server_url = "http://127.0.0.1:8123/mcp"
        self.fail_on_call = fail_on_call
        self.abstract_suffix = abstract_suffix
        self.response_override = response_override
        self.include_v2_trace = include_v2_trace
        self.incomplete_fetch = incomplete_fetch
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.last_response: str | None = None
        self.initialize_calls = 0
        self.admission_present_at_initialize: list[bool] = []

    async def initialize(self) -> None:
        self.initialize_calls += 1
        admission_path = pilot.PILOT_PREREG.with_suffix(".admission.json")
        self.admission_present_at_initialize.append(admission_path.is_file())

    async def call_tool(self, tool_name: str, **params: Any) -> str:
        self.calls.append((tool_name, params))
        self.events.append(("mcp", str(params["query"])))
        if len(self.calls) == self.fail_on_call:
            raise RuntimeError("offline MCP failure")
        paper_id = str(99000 + len(self.calls))
        self.last_response = self.response_override or json.dumps(
            {
                paper_id: {
                    "title": f"Offline title {len(self.calls)}",
                    "authors": ["Offline Author"],
                    "date_revised": "2024/1/1",
                    "abstract": f"Offline abstract {len(self.calls)}. {self.abstract_suffix}",
                    "fulltext": None,
                    "doi": None,
                    "pmc_full_text_id": None,
                }
            }
        )
        trace = screen._trace_path(
            self.cache_root, str(params["slug"]), str(params["run_id"])
        )
        response_data = json.loads(self.last_response)
        trace.parent.mkdir(parents=True)
        trace.write_text(
            json.dumps(
                {
                    "run_id": params["run_id"],
                    "server_build_id": "offline-build",
                    "sort": "pub_date",
                    "attempts": [],
                    "selected": None,
                    "fetched": [],
                    "final_ids": list(response_data)
                    if isinstance(response_data, dict)
                    else [],
                    "shared_pool_supplements": [],
                }
            ),
            encoding="utf-8",
        )
        if self.include_v2_trace:
            ids = list(response_data) if isinstance(response_data, dict) else []
            metadata = response_data.get(ids[0], {}) if ids else {}
            raw_trace = {
                "run_id": params["run_id"],
                "server_build_id": "offline-build",
                "process_id": 123,
                "source_file": str(pilot.ROOT / "engine/mcp_server/pubmed_client.py"),
                "sort": "pub_date",
                "entrez_retry_policy": {
                    "max_tries": 1,
                    "sleep_between_tries": 0,
                },
                "entrez_calls": {
                    "esearch": 1,
                    "efetch": len(ids) + int(self.incomplete_fetch),
                    "elink": len(ids),
                },
                "incomplete_fetch_count": int(self.incomplete_fetch),
                "fetch_errors": (
                    [{"stage": "fulltext", "pmid": ids[0], "type": "RuntimeError"}]
                    if self.incomplete_fetch and ids
                    else []
                ),
                "metadata_origins": {paper_id: "entrez_fetch" for paper_id in ids},
                "attempts": [
                    {
                        "rung_index": 1,
                        "rung_type": "original",
                        "operation": "esearch",
                        "count": len(ids),
                        "first_ids": ids,
                        "sort": "pub_date",
                    }
                ],
                "selected": {
                    "rung_index": 1,
                    "rung_type": "original",
                    "count": len(ids),
                    "ids": ids,
                    "sort": "pub_date",
                }
                if ids
                else None,
                "pre_search_shared_pool": {
                    "file_count": 0,
                    "metadata_count": 0,
                    "first_ids": [],
                },
                "fetched": [
                    {
                        "pmid": paper_id,
                        "fetched": True,
                        "metadata_origin": "entrez_fetch",
                        "pmc_available": False,
                        "abstract_available": bool(
                            str(metadata.get("abstract", "")).strip()
                        ),
                        "incomplete": self.incomplete_fetch and paper_id == ids[0],
                    }
                    for paper_id in ids
                ],
                "final_ids": ids,
                "shared_pool_supplements": [],
                "error": None,
                "outcome": "nonempty" if ids else "empty",
            }
            trace.write_text(json.dumps(raw_trace), encoding="utf-8")
        return self.last_response


@pytest.fixture
def offline_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    protocol = {
        "model_name": MODEL,
        "mcp_tree": "offline-build",
        "mcp_build_id": "offline-build",
    }
    protocol_path = tmp_path / "pilot-protocol.json"
    protocol_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG", protocol_path)
    monkeypatch.setattr(pilot, "_load_pilot_protocol", lambda: protocol)
    monkeypatch.setenv(pilot.fixture.MCP_SECRET_ENV, "offline-loopback-secret" * 2)
    serving_process = {
        "pid": 123,
        "listener_address": "127.0.0.1:8123",
        "source_path": str(pilot.ROOT / "engine/mcp_server/server.py"),
        "mcp_tree": "offline-build",
    }
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda _protocol, _prereg, *, cache_root: (
            "http://127.0.0.1:8123/mcp",
            cache_root,
            "offline-build",
            serving_process,
        ),
    )
    monkeypatch.setattr(
        pilot, "_check_mcp_process", lambda *_args, **_kwargs: serving_process
    )
    return {"protocol": protocol, "serving_process": serving_process}


def _registry() -> ToolRegistry:
    return ToolRegistry(
        config_path=str(screen.ROOT / screen.TOOL_CONFIG),
        skip_user_config=True,
    )


def _run_pilot(
    client: FakeMCPClient,
    cache_root: Path,
    result_path: Path,
    blind_path: Path,
    *,
    expected_build_id: str = "offline-build",
    model_name: str = MODEL,
    study_version: int = 1,
) -> dict[str, Any]:
    return asyncio.run(
        pilot.run_pilot(
            screen._load_preregistration(1),
            _registry(),
            client,
            cache_root,
            result_path,
            blind_path,
            expected_build_id=expected_build_id,
            model_name=model_name,
            model_api_key="offline-test-key",
            study_version=study_version,
        )
    )


def _select_v2_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> dict[str, Any]:
    return _select_prospective_protocol(2, tmp_path, monkeypatch, offline_runtime)


def _select_prospective_protocol(
    study_version: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> dict[str, Any]:
    registration = pilot._study_registration(study_version)
    protocol_constants = {
        1: "PILOT_PREREG",
        2: "PILOT_PREREG_V2",
        3: "PILOT_PREREG_V3",
    }
    protocol = offline_runtime["protocol"]
    protocol.update(
        {
            "study_version": study_version,
            "protocol_version": registration.protocol_version,
            "fixture_bank_version": registration.fixture_bank_version,
            "fixture_bank_path": registration.fixture_bank_path,
            "fixture_bank_sha256": f"v{registration.fixture_bank_version}-test-bank-hash",
        }
    )
    protocol_path = tmp_path / f"pilot-protocol-v{study_version}.json"
    protocol_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pilot, protocol_constants[study_version], protocol_path)
    monkeypatch.setattr(
        pilot,
        "_load_pilot_protocol",
        lambda study_version=1: protocol,
    )
    monkeypatch.setattr(
        pilot,
        "_load_fixture_bank",
        lambda _protocol, _study_version: screen._load_preregistration(1),
    )
    return protocol


def _model_completion(content: str, model: str = SERVED_MODEL) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=50,
            completion_tokens=10,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        model=model,
    )


def _qualified_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_free_policy,
        "current_catalog",
        lambda: {
            "campaign/zero:free": {
                "id": "campaign/zero:free",
                "pricing": {"prompt": "0", "completion": "0"},
                "expiration_date": "9999-12-31",
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )


def test_pilot_pairs_one_shared_first_search_with_two_blind_followups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    events: list[tuple[str, str]] = []
    response_text = json.dumps({"query": "offline follow-up query"})
    llm_responses = [_model_completion(response_text) for _ in range(24)]
    llm_requests: list[dict[str, Any]] = []
    import litellm

    queue = iter(llm_responses)

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        llm_requests.append(kwargs)
        prompt = " ".join(
            str(message.get("content", "")) for message in kwargs["messages"]
        )
        events.append(("llm", prompt))
        return next(queue)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    result_path = tmp_path / "result.json"
    blind_path = tmp_path / "blind.json"
    client = FakeMCPClient(cache_root, events)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    monkeypatch.setattr("sys.argv", ["novelty_result_conditioned_pilot"])
    monkeypatch.setattr(pilot, "_new_output_paths", lambda: (result_path, blind_path))
    monkeypatch.setattr(pilot, "MCPToolClient", lambda *, server_url: client)

    exit_code = asyncio.run(pilot._main())
    report = json.loads(result_path.read_text(encoding="utf-8"))
    prereg = screen._load_preregistration(1)

    assert exit_code == 0
    assert report["status"] == "PILOT_COMPLETE_LABELS_PENDING"
    assert report["model_call_count"] == 24
    assert report["outer_mcp_call_count"] == 36
    assert len(llm_requests) == 24
    assert len(client.calls) == 36
    assert [name for name, _ in client.calls] == ["pubmed_search_with_fulltext"] * 36
    assert len({params["slug"] for _, params in client.calls}) == 36
    assert len({params["run_id"] for _, params in client.calls}) == 36
    assert all(params["max_papers"] == 3 for _, params in client.calls)
    assert all(
        request["extra_body"]["provider"]["max_price"]
        == {"prompt": 0, "completion": 0, "request": 0}
        for request in llm_requests
    )
    assert all(
        request["api_base"] == "https://openrouter.ai/api/v1"
        for request in llm_requests
    )
    assert all(request["model"] == MODEL for request in llm_requests)
    assert all(request["api_key"] == "offline-test-key" for request in llm_requests)
    assert all(
        request["max_tokens"] == pilot.MODEL_MAX_TOKENS for request in llm_requests
    )
    assert all(
        request["temperature"] == pilot.MODEL_TEMPERATURE for request in llm_requests
    )
    source_ids = [
        str(pair[arm].get("target_pmid", pair[arm].get("anchor_pmid")))
        for pair in prereg["cases_in_fixed_order"]
        for arm in ("positive", "distinct_control")
    ]
    prompts = [
        " ".join(str(message.get("content", "")) for message in request["messages"])
        for request in llm_requests
    ]
    assert all(
        source_id not in prompt for source_id in source_ids for prompt in prompts
    )
    assert "Offline title 1" not in prompts[0]
    assert "Offline abstract 1" not in prompts[0]
    assert "Offline title 1" in prompts[1]
    assert "Offline abstract 1" in prompts[1]
    assert "99001" not in prompts[1]
    assert [kind for kind, _ in events[:5]] == [
        "llm",
        "mcp",
        "llm",
        "mcp",
        "mcp",
    ]
    assert all(
        event["served_model"] == MODEL
        and event["observed_model_calls"] == 1
        and event["retries"] == 0
        and event["cache_hits"] == 0
        for event in report["events"]
        if event["kind"] == "model"
    )
    assert (
        report["events"][2]["first_search_event_id"] == report["events"][1]["event_id"]
    )
    assert (
        report["events"][3]["first_search_event_id"] == report["events"][1]["event_id"]
    )
    assert (
        report["events"][4]["first_search_event_id"] == report["events"][1]["event_id"]
    )
    assert all(
        source_id not in str(params["query"])
        for source_id in source_ids
        for _, params in client.calls
    )
    assert "trace" in report["events"][1]
    assert report["events"][1]["trace"]["server_build_id"] == "offline-build"
    assert report["mcp_serving_process"] == offline_runtime["serving_process"]
    assert client.initialize_calls == 1
    assert client.admission_present_at_initialize == [True]
    assert all(
        "query" in event["wire_parameters"]
        and "trace" in event
        and event["trace"]["serving_process"] == offline_runtime["serving_process"]
        for event in report["events"]
        if event["kind"] == "mcp"
    )
    result_text = result_path.read_text(encoding="utf-8")
    assert "offline-test-key" not in result_text
    assert "Offline abstract" not in result_text
    assert result_path.exists() and blind_path.exists()
    assert result_path.stat().st_mode & 0o777 == 0o600
    blind_text = blind_path.read_text(encoding="utf-8")
    assert "Offline abstract" in blind_text
    assert "pmid" not in blind_text
    assert "target_pmid" not in blind_text
    assert "anchor_pmid" not in blind_text


def test_target_or_anchor_identifier_in_generated_query_stops_before_pubmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    # An async fake keeps the test at the public provider request seam.
    async def fake_acompletion(**_: Any) -> SimpleNamespace:
        return _model_completion('{"query":"find 24226770"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events)
    result_path = tmp_path / "result.json"
    blind_path = tmp_path / "blind.json"

    report = asyncio.run(
        pilot.run_pilot(
            screen._load_preregistration(1),
            _registry(),
            client,
            cache_root,
            result_path,
            blind_path,
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
        )
    )

    assert report["status"] == "INCOMPLETE_ERROR"
    assert report["model_call_count"] == 1
    assert report["provider_call_count"] == 1
    assert report["outer_mcp_call_count"] == 0
    assert client.calls == []


def test_nonzero_catalog_price_stops_before_provider_or_pubmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        llm_free_policy,
        "current_catalog",
        lambda: {
            "campaign/zero:free": {
                "pricing": {"prompt": "0", "completion": "0.01"},
                "expiration_date": "9999-12-31",
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )
    import litellm

    async def unexpected_provider_call(**_: Any) -> SimpleNamespace:
        pytest.fail("zero-price admission must run before provider transport")

    monkeypatch.setattr(litellm, "acompletion", unexpected_provider_call)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events)

    report = asyncio.run(
        pilot.run_pilot(
            screen._load_preregistration(1),
            _registry(),
            client,
            cache_root,
            tmp_path / "result.json",
            tmp_path / "blind.json",
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
        )
    )

    assert report["status"] == "INCOMPLETE_ERROR"
    assert report["model_call_count"] == 1
    assert report["provider_call_count"] == 0
    assert report["outer_mcp_call_count"] == 0
    assert client.calls == []


def test_nonempty_cache_stops_before_provider_or_pubmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    import litellm

    async def unexpected_provider_call(**_: Any) -> SimpleNamespace:
        pytest.fail("nonempty cache admission must run before provider transport")

    monkeypatch.setattr(litellm, "acompletion", unexpected_provider_call)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "prior-result.json").write_text("{}", encoding="utf-8")
    client = FakeMCPClient(cache_root, events)

    with pytest.raises(ValueError, match="cache must exist and start empty"):
        asyncio.run(
            pilot.run_pilot(
                screen._load_preregistration(1),
                _registry(),
                client,
                cache_root,
                tmp_path / "result.json",
                tmp_path / "blind.json",
                expected_build_id="offline-build",
                model_name=MODEL,
                model_api_key="offline-test-key",
            )
        )

    assert client.calls == []


def test_served_model_mismatch_stops_after_one_uncached_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    async def wrong_model(**_: Any) -> SimpleNamespace:
        return _model_completion('{"query":"offline query"}', "campaign/other:free")

    monkeypatch.setattr(litellm, "acompletion", wrong_model)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events)

    report = asyncio.run(
        pilot.run_pilot(
            screen._load_preregistration(1),
            _registry(),
            client,
            cache_root,
            tmp_path / "result.json",
            tmp_path / "blind.json",
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
        )
    )

    assert report["status"] == "INCOMPLETE_ERROR"
    assert report["model_call_count"] == 1
    assert report["provider_call_count"] == 1
    assert report["outer_mcp_call_count"] == 0
    assert report["events"][0]["served_model"] == "openrouter/campaign/other:free"
    assert client.calls == []


def test_first_mcp_error_stops_without_retry_or_second_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    async def one_model_call(**_: Any) -> SimpleNamespace:
        events.append(("llm", "static query"))
        return _model_completion('{"query":"offline query"}')

    monkeypatch.setattr(litellm, "acompletion", one_model_call)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events, fail_on_call=1)

    report = asyncio.run(
        pilot.run_pilot(
            screen._load_preregistration(1),
            _registry(),
            client,
            cache_root,
            tmp_path / "result.json",
            tmp_path / "blind.json",
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
        )
    )

    assert report["status"] == "INCOMPLETE_ERROR"
    assert report["model_call_count"] == 1
    assert report["provider_call_count"] == 1
    assert report["outer_mcp_call_count"] == 1
    assert len(client.calls) == 1
    assert [kind for kind, _ in events] == ["llm", "mcp"]


def test_source_pmids_in_returned_abstracts_do_not_enter_the_blind_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    async def one_model_call(**_: Any) -> SimpleNamespace:
        return _model_completion('{"query":"offline query"}')

    monkeypatch.setattr(litellm, "acompletion", one_model_call)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events, abstract_suffix="target 24226770")
    blind_path = tmp_path / "blind.json"

    report = asyncio.run(
        pilot.run_pilot(
            screen._load_preregistration(1),
            _registry(),
            client,
            cache_root,
            tmp_path / "result.json",
            blind_path,
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
        )
    )

    assert report["status"] == "INCOMPLETE_ERROR"
    assert report["outer_mcp_call_count"] == 1
    assert report["provider_call_count"] == 1
    assert "24226770" not in blind_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("model_name", "build_id", "message"),
    [
        ("openrouter/campaign/other:free", "offline-build", "Selected model"),
        (MODEL, "another-build", "build ID"),
    ],
)
def test_direct_runner_rejects_uncommitted_model_or_build_before_any_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
    model_name: str,
    build_id: str,
    message: str,
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    async def fake_acompletion(**_: Any) -> SimpleNamespace:
        pytest.fail("protocol mismatch must stop before provider transport")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / f"cache-{build_id}"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events)

    with pytest.raises(ValueError, match=message):
        _run_pilot(
            client,
            cache_root,
            tmp_path / f"result-{build_id}.json",
            tmp_path / f"blind-{build_id}.json",
            expected_build_id=build_id,
            model_name=model_name,
        )

    assert client.calls == []


def test_direct_runner_rejects_client_outside_the_attested_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, [])
    client.server_url = "http://127.0.0.1:8124/mcp"

    with pytest.raises(ValueError, match="attested endpoint"):
        _run_pilot(
            client,
            cache_root,
            tmp_path / "result.json",
            tmp_path / "blind.json",
        )
    assert client.calls == []


def test_failed_campaign_admission_blocks_rerun_with_fresh_output_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    provider_calls = 0

    async def fake_acompletion(**_: Any) -> SimpleNamespace:
        nonlocal provider_calls
        provider_calls += 1
        return _model_completion('{"query":"offline query"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "first-cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events, fail_on_call=1)
    first = _run_pilot(
        client,
        cache_root,
        tmp_path / "first-result.json",
        tmp_path / "first-blind.json",
    )
    assert first["status"] == "INCOMPLETE_ERROR"
    assert len(client.calls) == 1
    calls_after_failure = provider_calls

    second_cache = tmp_path / "second-cache"
    second_cache.mkdir()
    with pytest.raises(ValueError, match="campaign admission already exists"):
        _run_pilot(
            client,
            second_cache,
            tmp_path / "fresh-result.json",
            tmp_path / "fresh-blind.json",
        )
    assert len(client.calls) == 1
    assert provider_calls == calls_after_failure


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_calls", "classification"),
    [
        ('{"unexpected":"malformed"}', "INCOMPLETE_ERROR", 1, "retrieval_error"),
        ("{}", "PILOT_COMPLETE_LABELS_PENDING", 36, "success_empty"),
    ],
)
def test_mcp_payload_malformed_fails_closed_but_empty_is_a_valid_empty_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
    payload: str,
    expected_status: str,
    expected_calls: int,
    classification: str,
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    async def fake_acompletion(**_: Any) -> SimpleNamespace:
        return _model_completion('{"query":"offline query"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    events: list[tuple[str, str]] = []
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, events, response_override=payload)

    report = _run_pilot(
        client,
        cache_root,
        tmp_path / "result.json",
        tmp_path / "blind.json",
    )

    assert report["status"] == expected_status
    assert report["outer_mcp_call_count"] == expected_calls
    assert report["events"][-1]["classification"] == classification
    assert len(client.calls) == expected_calls


def test_existing_admission_marker_blocks_a_crash_recovery_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    marker = pilot.PILOT_PREREG.with_suffix(".admission.json")
    marker.write_text('{"status":"CLAIMED"}\n', encoding="utf-8")
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    events: list[tuple[str, str]] = []
    client = FakeMCPClient(cache_root, events)

    with pytest.raises(ValueError, match="campaign admission already exists"):
        _run_pilot(
            client,
            cache_root,
            tmp_path / "new-result.json",
            tmp_path / "new-blind.json",
        )
    assert client.calls == []
    assert client.initialize_calls == 0


def test_main_existing_admission_blocks_before_mcp_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    monkeypatch.setattr("sys.argv", ["novelty_result_conditioned_pilot"])
    result_path = tmp_path / "result.json"
    blind_path = tmp_path / "blind.json"
    monkeypatch.setattr(pilot, "_new_output_paths", lambda: (result_path, blind_path))
    client = FakeMCPClient(cache_root, [])
    monkeypatch.setattr(pilot, "MCPToolClient", lambda *, server_url: client)
    pilot.PILOT_PREREG.with_suffix(".admission.json").write_text(
        '{"status":"CLAIMED"}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="campaign admission already exists"):
        asyncio.run(pilot._main())

    assert client.initialize_calls == 0
    assert client.calls == []


def test_server_restart_during_search_stops_before_followup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    async def fake_acompletion(**_: Any) -> SimpleNamespace:
        return _model_completion('{"query":"offline query"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    expected = offline_runtime["serving_process"]
    attestations = iter([expected, {**expected, "pid": 124}])
    monkeypatch.setattr(
        pilot, "_check_mcp_process", lambda *_args, **_kwargs: next(attestations)
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = FakeMCPClient(cache_root, [])

    report = _run_pilot(
        client,
        cache_root,
        tmp_path / "result.json",
        tmp_path / "blind.json",
    )

    assert report["status"] == "INCOMPLETE_ERROR"
    assert report["outer_mcp_call_count"] == 1
    assert len(client.calls) == 1


def test_main_is_disabled_until_a_preregistered_protocol_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pilot, "PILOT_PREREG", tmp_path / "missing.json")
    monkeypatch.setattr("sys.argv", ["novelty_result_conditioned_pilot"])
    with pytest.raises(
        ValueError, match="disabled until its protocol is preregistered"
    ):
        asyncio.run(pilot._main())


def test_study_version_is_explicit_and_uses_separate_output_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert pilot._parse_args([]).study_version == 1
    assert pilot._parse_args(["--study-version", "2"]).study_version == 2
    assert pilot._parse_args(["--study-version", "3"]).study_version == 3
    with pytest.raises(SystemExit):
        pilot._parse_args(["--study-version", "4"])
    with pytest.raises(
        ValueError, match="Unsupported result-conditioned pilot study version: 4"
    ):
        pilot._new_output_paths(4)

    monkeypatch.setattr(pilot, "RESULT_DIR", tmp_path)
    v1_result, v1_blind = pilot._new_output_paths(1)
    v2_result, v2_blind = pilot._new_output_paths(2)
    v3_result, v3_blind = pilot._new_output_paths(3)

    assert v1_result.name.startswith("novelty-result-conditioned-pilot-v1-")
    assert v2_result.name.startswith("novelty-result-conditioned-pilot-v2-")
    assert v3_result.name.startswith("novelty-result-conditioned-pilot-v3-")
    assert "-v1-blind-" in v1_blind.name
    assert "-v2-blind-" in v2_blind.name
    assert "-v3-blind-" in v3_blind.name
    assert len({v1_result, v1_blind, v2_result, v2_blind, v3_result, v3_blind}) == 6


def test_v3_admission_uses_a_distinct_exclusive_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol_path = tmp_path / "novelty-result-conditioned-pilot-prereg-v3.json"
    protocol_bytes = b"committed prospective study v3 protocol\n"
    protocol_path.write_bytes(protocol_bytes)
    monkeypatch.setattr(pilot, "PILOT_PREREG_V3", protocol_path)

    admission_path = pilot._claim_campaign_admission({"model_name": MODEL}, 3)

    assert admission_path == protocol_path.with_suffix(".admission.json")
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    assert admission["study_version"] == 3
    assert admission["protocol_sha256"] == hashlib.sha256(protocol_bytes).hexdigest()
    assert admission_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="campaign admission already exists"):
        pilot._claim_campaign_admission({"model_name": MODEL}, 3)


@pytest.mark.parametrize("study_version", [2, 3])
def test_prospective_partial_fulltext_fetch_is_rejected_and_admission_cannot_be_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
    study_version: int,
) -> None:
    _select_prospective_protocol(study_version, tmp_path, monkeypatch, offline_runtime)
    _qualified_model(monkeypatch)
    import litellm

    provider_calls = 0

    async def fake_acompletion(**_: Any) -> SimpleNamespace:
        nonlocal provider_calls
        provider_calls += 1
        return _model_completion('{"query":"offline query"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    cache_root = tmp_path / f"cache-v{study_version}"
    cache_root.mkdir()
    client = FakeMCPClient(
        cache_root,
        [],
        include_v2_trace=True,
        incomplete_fetch=True,
    )
    first = _run_pilot(
        client,
        cache_root,
        tmp_path / f"result-v{study_version}.json",
        tmp_path / f"blind-v{study_version}.json",
        study_version=study_version,
    )

    assert first["status"] == "INCOMPLETE_ERROR"
    assert first["study_version"] == study_version
    assert first["model_call_count"] == 1
    assert first["provider_call_count"] == 1
    assert first["outer_mcp_call_count"] == 1
    assert first["events"][-1]["trace_error"] == "ValueError"
    assert (
        first["events"][-1]["trace_attestation"]["fetch_errors"][0]["stage"]
        == "fulltext"
    )
    assert first["events"][-1]["trace_attestation"]["incomplete_fetch_count"] == 1
    assert provider_calls == 1
    assert len(client.calls) == 1
    admission_path = pilot._protocol_path(study_version).with_suffix(".admission.json")
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    assert admission["study_version"] == study_version
    assert (
        admission["protocol_sha256"]
        == hashlib.sha256(pilot._protocol_path(study_version).read_bytes()).hexdigest()
    )

    next_cache = tmp_path / f"next-cache-v{study_version}"
    next_cache.mkdir()
    with pytest.raises(ValueError, match="campaign admission already exists"):
        _run_pilot(
            client,
            next_cache,
            tmp_path / f"fresh-result-v{study_version}.json",
            tmp_path / f"fresh-blind-v{study_version}.json",
            study_version=study_version,
        )
    assert provider_calls == 1
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    (
        "study_version",
        "protocol_constant",
        "protocol_filename",
        "protocol_version",
        "bank_version",
        "bank_path_relative",
        "bank_status",
    ),
    [
        (
            2,
            "PILOT_PREREG_V2",
            "novelty-result-conditioned-pilot-prereg-v2.json",
            2,
            3,
            "references/external/sakana/novelty-fixture-bank-prereg-v3.json",
            "PREREGISTERED_BEFORE_ANY_V3_VALIDATOR_SCREEN",
        ),
        (
            3,
            "PILOT_PREREG_V3",
            "novelty-result-conditioned-pilot-prereg-v3.json",
            3,
            4,
            "references/external/sakana/novelty-fixture-bank-prereg-v4.json",
            "PREREGISTERED_BEFORE_ANY_V4_VALIDATOR_SCREEN",
        ),
    ],
)
def test_versioned_protocol_binds_committed_bank_path_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    study_version: int,
    protocol_constant: str,
    protocol_filename: str,
    protocol_version: int,
    bank_version: int,
    bank_path_relative: str,
    bank_status: str,
) -> None:
    repository = tmp_path / "repository"
    bank_path = repository / bank_path_relative
    protocol_path = repository / "references/external/sakana" / protocol_filename
    bank_path.parent.mkdir(parents=True)
    bank = {
        "version": bank_version,
        "status": bank_status,
        "cases_in_fixed_order": [],
        "validation_boundary": {},
    }
    bank_bytes = (json.dumps(bank, indent=2) + "\n").encode()
    bank_path.write_bytes(bank_bytes)
    protocol = {
        "status": "PREREGISTERED_BEFORE_ANY_PILOT_CALL",
        "study_version": study_version,
        "protocol_version": protocol_version,
        "fixture_bank_version": bank_version,
        "fixture_bank_path": bank_path_relative,
        "fixture_bank_sha256": hashlib.sha256(bank_bytes).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(pilot.__file__).read_bytes()).hexdigest(),
        "static_prompt_sha256": hashlib.sha256(
            pilot.STATIC_PROMPT.encode()
        ).hexdigest(),
        "conditioned_prompt_sha256": hashlib.sha256(
            pilot.CONDITIONED_PROMPT.encode()
        ).hexdigest(),
        "request_config": pilot.MODEL_REQUEST_CONFIG,
        "max_outer_mcp_calls": pilot.OUTER_MCP_CALL_LIMIT,
        "max_model_calls": pilot.MODEL_CALL_LIMIT,
        "model_name": MODEL,
        "model_boundary_sha256": {"offline": "source-hash"},
        "mcp_tree": "offline-build",
        "mcp_build_id": "offline-build",
    }
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Pilot Test",
            "-c",
            "user.email=pilot@example.invalid",
            "add",
            str(bank_path.relative_to(repository)),
            str(protocol_path.relative_to(repository)),
        ],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Pilot Test",
            "-c",
            "user.email=pilot@example.invalid",
            "commit",
            "-qm",
            "register offline prospective protocol",
        ],
        cwd=repository,
        check=True,
    )
    monkeypatch.setattr(pilot, "ROOT", repository)
    monkeypatch.setattr(pilot, protocol_constant, protocol_path)
    monkeypatch.setattr(
        pilot, "_model_boundary_hashes", lambda: {"offline": "source-hash"}
    )

    loaded = pilot._load_pilot_protocol(study_version)
    assert loaded == protocol
    assert pilot._load_fixture_bank(loaded, study_version) == bank

    loaded["fixture_bank_path"] = "references/external/sakana/other-bank.json"
    with pytest.raises(ValueError, match=f"bind fixture bank version {bank_version}"):
        pilot._load_fixture_bank(loaded, study_version)

    loaded["fixture_bank_path"] = bank_path_relative
    bank_path.write_text(json.dumps({**bank, "name": "changed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Fixture bank must be committed unchanged"):
        pilot._load_fixture_bank(loaded, study_version)


@pytest.mark.parametrize("study_version", [2, 3])
def test_main_cli_selects_prospective_protocol_and_passes_it_to_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_runtime: dict[str, Any],
    study_version: int,
) -> None:
    protocol = _select_prospective_protocol(
        study_version, tmp_path, monkeypatch, offline_runtime
    )
    cache_root = tmp_path / f"cache-v{study_version}-main"
    cache_root.mkdir()
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    monkeypatch.setattr(
        "sys.argv",
        ["novelty_result_conditioned_pilot", "--study-version", str(study_version)],
    )
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda _protocol, _bank, *, cache_root: (
            "http://127.0.0.1:8123/mcp",
            cache_root,
            "offline-build",
            offline_runtime["serving_process"],
        ),
    )
    monkeypatch.setattr(pilot, "ToolRegistry", lambda **_kwargs: object())
    monkeypatch.setattr(pilot, "MCPToolClient", lambda **_kwargs: object())
    calls: dict[str, Any] = {}

    async def fake_run_pilot(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["result_path"] = args[4]
        calls.update(kwargs)
        return {
            "status": "PILOT_COMPLETE_LABELS_PENDING",
            "model_call_count": 24,
            "provider_call_count": 24,
            "outer_mcp_call_count": 36,
        }

    monkeypatch.setattr(pilot, "run_pilot", fake_run_pilot)

    assert asyncio.run(pilot._main()) == 0
    assert protocol["study_version"] == calls["study_version"] == study_version
    assert calls["result_path"].name.startswith(
        f"novelty-result-conditioned-pilot-v{study_version}-"
    )


def test_v2_trace_reconciles_entrez_entrypoints_and_rejects_count_mismatch() -> None:
    source_file = str((pilot.ROOT / "engine/mcp_server/pubmed_client.py").resolve())
    trace = {
        "run_id": "run-1",
        "server_build_id": "build-1",
        "process_id": 123,
        "source_file": source_file,
        "sort": "pub_date",
        "entrez_retry_policy": {"max_tries": 1, "sleep_between_tries": 0},
        "entrez_calls": {"esearch": 1, "efetch": 1, "elink": 1},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "metadata_origins": {"12345": "entrez_fetch"},
        "attempts": [
            {
                "rung_index": 1,
                "rung_type": "original",
                "operation": "esearch",
                "count": 1,
                "first_ids": ["12345"],
                "sort": "pub_date",
            }
        ],
        "selected": {
            "rung_index": 1,
            "rung_type": "original",
            "count": 1,
            "ids": ["12345"],
            "sort": "pub_date",
        },
        "pre_search_shared_pool": {
            "file_count": 0,
            "metadata_count": 0,
            "first_ids": [],
        },
        "fetched": [
            {
                "pmid": "12345",
                "fetched": True,
                "metadata_origin": "entrez_fetch",
                "pmc_available": False,
                "abstract_available": True,
                "incomplete": False,
            }
        ],
        "final_ids": ["12345"],
        "shared_pool_supplements": [],
        "error": None,
        "outcome": "nonempty",
    }
    serving_process = {"pid": 123}

    attestation = pilot._validate_v2_trace(
        trace,
        run_id="run-1",
        expected_build_id="build-1",
        serving_process=serving_process,
        returned_ids=["12345"],
    )
    assert (
        "not physical HTTP requests" in attestation["count_semantics"]["entrez_calls"]
    )
    trace["entrez_calls"]["efetch"] = 3
    trace["fetched"][0]["pmc_available"] = True
    paginated_attestation = pilot._validate_v2_trace(
        trace,
        run_id="run-1",
        expected_build_id="build-1",
        serving_process=serving_process,
        returned_ids=["12345"],
    )
    assert paginated_attestation["entrez_calls"]["efetch"] == 3
    assert "may paginate" in paginated_attestation["count_semantics"]["entrez_calls"]
    trace["entrez_calls"]["efetch"] = 0
    with pytest.raises(ValueError, match="attestation is incomplete or inconsistent"):
        pilot._validate_v2_trace(
            trace,
            run_id="run-1",
            expected_build_id="build-1",
            serving_process=serving_process,
            returned_ids=["12345"],
        )
    trace["entrez_calls"]["efetch"] = 3
    trace["entrez_calls"]["esearch"] = 2
    with pytest.raises(ValueError, match="attestation is incomplete or inconsistent"):
        pilot._validate_v2_trace(
            trace,
            run_id="run-1",
            expected_build_id="build-1",
            serving_process=serving_process,
            returned_ids=["12345"],
        )
    trace["entrez_calls"]["esearch"] = 1
    trace["pre_search_shared_pool"] = {
        "file_count": 1,
        "metadata_count": 1,
        "first_ids": ["12345"],
    }
    with pytest.raises(ValueError, match="attestation is incomplete or inconsistent"):
        pilot._validate_v2_trace(
            trace,
            run_id="run-1",
            expected_build_id="build-1",
            serving_process=serving_process,
            returned_ids=["12345"],
        )


def _runtime_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    endpoint = "http://127.0.0.1:8123/mcp"
    monkeypatch.setenv("COSCIENTIST_CAMPAIGN_MCP_URL", endpoint)
    monkeypatch.setenv("MCP_SERVER_URL", endpoint)
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "offline-loopback-secret" * 2)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "server-tree")
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    prereg = {
        "validation_boundary": {
            "validator": "validator.py",
            "validator_sha256": "digest",
            "parser": "parser.py",
            "parser_sha256": "digest",
            "tool_config": "tool.json",
            "tool_config_sha256": "digest",
        }
    }
    protocol = {"mcp_tree": "server-tree", "mcp_build_id": "server-tree"}
    repository = tmp_path / "repository"
    engine_root = repository / "engine"
    server_module = engine_root / "mcp_server/server.py"
    server_module.parent.mkdir(parents=True)
    server_module.touch()
    monkeypatch.setattr(pilot, "ROOT", repository)
    monkeypatch.setattr(pilot.fixture, "_sha256", lambda _: "digest")
    monkeypatch.setattr(pilot.fixture, "_check_server_tree_clean", lambda: None)
    monkeypatch.setattr(pilot.fixture, "_git", lambda *_: "server-tree")
    return protocol, prereg, cache_root


def _study3_runtime_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    original_root = pilot.ROOT
    protocol_path = pilot.PILOT_PREREG_V3
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["runner_sha256"] = hashlib.sha256(
        Path(pilot.__file__).read_bytes()
    ).hexdigest()
    test_protocol_path = tmp_path / "study3-protocol.json"
    test_protocol_path.write_text(
        json.dumps(protocol, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    test_root = tmp_path / "repository"
    test_root.mkdir()
    (test_root / "engine").symlink_to(
        original_root / "engine", target_is_directory=True
    )
    bank_relative = pilot._study_registration(3).fixture_bank_path
    assert bank_relative is not None
    bank_path = test_root / bank_relative
    bank_path.parent.mkdir(parents=True)
    bank_path.write_bytes((original_root / bank_relative).read_bytes())

    monkeypatch.setattr(pilot, "ROOT", test_root)
    monkeypatch.setattr(pilot, "PILOT_PREREG_V3", test_protocol_path)
    committed_file_bytes = pilot._committed_file_bytes

    def read_test_registration(path: Path, label: str) -> bytes:
        if path in {test_protocol_path, bank_path}:
            return path.read_bytes()
        return committed_file_bytes(path, label)

    monkeypatch.setattr(pilot, "_committed_file_bytes", read_test_registration)
    monkeypatch.setattr(pilot.fixture, "_check_server_tree_clean", lambda: None)
    monkeypatch.setattr(pilot.fixture, "_git", lambda *_: protocol["mcp_tree"])
    serving_process = {
        "pid": 123,
        "listener_address": "127.0.0.1:8123",
        "source_path": str(test_root / "engine/mcp_server/server.py"),
        "mcp_tree": protocol["mcp_tree"],
    }
    monkeypatch.setattr(
        pilot, "_check_mcp_process", lambda *_args, **_kwargs: serving_process
    )
    endpoint = "http://127.0.0.1:8123/mcp"
    monkeypatch.setenv("COSCIENTIST_CAMPAIGN_MCP_URL", endpoint)
    monkeypatch.setenv("MCP_SERVER_URL", endpoint)
    monkeypatch.setenv(pilot.fixture.MCP_SECRET_ENV, "offline-loopback-secret" * 2)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", protocol["mcp_build_id"])
    cache_root = tmp_path / "study3-cache"
    cache_root.mkdir()
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")

    return (
        pilot._load_pilot_protocol(3),
        pilot._load_fixture_bank(protocol, 3),
        cache_root,
    )


def test_study3_cli_reaches_science_boundary_with_current_v4_bank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, bank, _ = _study3_runtime_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv", ["novelty_result_conditioned_pilot", "--study-version", "3"]
    )

    class RuntimeGateReached(Exception):
        pass

    async def stop_before_science(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeGateReached

    monkeypatch.setattr(pilot, "run_pilot", stop_before_science)
    with pytest.raises(RuntimeGateReached):
        asyncio.run(pilot._main())

    assert protocol["study_version"] == 3
    assert bank["version"] == 4


@pytest.mark.parametrize(
    ("bank_path_key"), ["maintained_validator", "parser", "tool_config"]
)
def test_study3_runtime_rejects_a_fixture_source_path_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bank_path_key: str,
) -> None:
    protocol, bank, cache_root = _study3_runtime_inputs(tmp_path, monkeypatch)
    bank["validation_boundary"][bank_path_key] = "engine/unexpected.py"

    with pytest.raises(ValueError, match="validation source path differs"):
        pilot._check_runtime(protocol, bank, cache_root=cache_root)


@pytest.mark.parametrize(
    ("protocol_hash_key"),
    [
        "validator_sha256",
        "response_parser_sha256",
        "tool_config_sha256",
    ],
)
def test_study3_runtime_rejects_a_current_source_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protocol_hash_key: str,
) -> None:
    protocol, bank, cache_root = _study3_runtime_inputs(tmp_path, monkeypatch)
    protocol["validation_boundary"][protocol_hash_key] = "0" * 64

    with pytest.raises(ValueError, match="Frozen validation source changed"):
        pilot._check_runtime(protocol, bank, cache_root=cache_root)


def test_study3_runtime_uses_current_protocol_hashes_not_historical_bank_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, bank, cache_root = _study3_runtime_inputs(tmp_path, monkeypatch)
    for hash_key in ("validator_sha256", "parser_sha256", "tool_config_sha256"):
        bank["validation_boundary"]["v3_reference_hashes"][hash_key] = "0" * 64

    endpoint, checked_cache, build_id, _ = pilot._check_runtime(
        protocol, bank, cache_root=cache_root
    )

    assert (endpoint, checked_cache, build_id) == (
        "http://127.0.0.1:8123/mcp",
        cache_root,
        protocol["mcp_build_id"],
    )


def test_runtime_requires_the_protocol_to_pin_the_current_mcp_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, prereg, cache_root = _runtime_inputs(tmp_path, monkeypatch)
    protocol["mcp_tree"] = "older-server-tree"
    protocol["mcp_build_id"] = "older-server-tree"

    with pytest.raises(ValueError, match="differs from the pilot protocol"):
        pilot._check_runtime(protocol, prereg, cache_root=cache_root)


def test_runtime_rejects_repository_env_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, prereg, cache_root = _runtime_inputs(tmp_path, monkeypatch)
    repository = tmp_path / "repository"
    (repository / ".env").touch()

    with pytest.raises(ValueError, match=r"Remove repository \.env files"):
        pilot._check_runtime(protocol, prereg, cache_root=cache_root)


def test_runtime_rejects_credentials_in_the_loopback_mcp_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, prereg, cache_root = _runtime_inputs(tmp_path, monkeypatch)
    outputs = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout="p123\nn127.0.0.1:8123\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=f"n{pilot.ROOT / 'engine'}\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    "python -m uvicorn mcp_server.server:app "
                    "COSCIENTIST_MCP_SHARED_SECRET=offline-loopback-secretoffline-loopback-secret "
                    "COSCIENTIST_REQUIRE_FREE_MODELS=1 "
                    "COSCIENTIST_PUBMED_PILOT_BUILD_ID=server-tree "
                    f"COSCIENTIST_LIT_REVIEW_DIR={cache_root} "
                    "PYTHONPATH=. "
                    "OPENROUTER_API_KEY=must-not-be-accepted"
                ),
                stderr="",
            ),
        ]
    )

    monkeypatch.setattr(
        pilot.subprocess, "run", lambda *_args, **_kwargs: next(outputs)
    )
    with pytest.raises(ValueError, match="credential-free") as error:
        pilot._check_runtime(protocol, prereg, cache_root=cache_root)
    assert "must-not-be-accepted" not in str(error.value)


def test_runtime_accepts_the_pinned_credential_free_loopback_mcp_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, prereg, cache_root = _runtime_inputs(tmp_path, monkeypatch)
    outputs = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout="p123\nn127.0.0.1:8123\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=f"n{pilot.ROOT / 'engine'}\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    "python -m uvicorn mcp_server.server:app "
                    "COSCIENTIST_MCP_SHARED_SECRET=offline-loopback-secretoffline-loopback-secret "
                    "COSCIENTIST_REQUIRE_FREE_MODELS=1 "
                    "COSCIENTIST_PUBMED_PILOT_TRACE=1 "
                    "COSCIENTIST_PUBMED_PILOT_BUILD_ID=server-tree "
                    f"COSCIENTIST_LIT_REVIEW_DIR={cache_root} "
                    "PYTHONPATH=."
                ),
                stderr="",
            ),
        ]
    )
    monkeypatch.setattr(
        pilot.subprocess, "run", lambda *_args, **_kwargs: next(outputs)
    )

    endpoint, checked_cache, build_id, serving_process = pilot._check_runtime(
        protocol, prereg, cache_root=cache_root
    )
    assert (endpoint, checked_cache, build_id) == (
        "http://127.0.0.1:8123/mcp",
        cache_root,
        "server-tree",
    )
    assert serving_process == {
        "pid": 123,
        "listener_address": "127.0.0.1:8123",
        "source_path": str(pilot.ROOT / "engine/mcp_server/server.py"),
        "mcp_tree": "server-tree",
    }


def test_process_attestation_checks_the_pinned_source_tree_not_just_env_build_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, prereg, cache_root = _runtime_inputs(tmp_path, monkeypatch)
    del protocol, prereg
    monkeypatch.setattr(pilot.fixture, "_git", lambda *_: "different-source-tree")
    outputs = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout="p123\nn127.0.0.1:8123\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=f"n{pilot.ROOT / 'engine'}\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    "python -m uvicorn mcp_server.server:app "
                    "COSCIENTIST_MCP_SHARED_SECRET=offline-loopback-secretoffline-loopback-secret "
                    "COSCIENTIST_REQUIRE_FREE_MODELS=1 "
                    "COSCIENTIST_PUBMED_PILOT_TRACE=1 "
                    "COSCIENTIST_PUBMED_PILOT_BUILD_ID=server-tree "
                    f"COSCIENTIST_LIT_REVIEW_DIR={cache_root} "
                    "PYTHONPATH=."
                ),
                stderr="",
            ),
        ]
    )
    monkeypatch.setattr(
        pilot.subprocess, "run", lambda *_args, **_kwargs: next(outputs)
    )

    with pytest.raises(ValueError, match="source tree differs from the pinned tree"):
        pilot._check_mcp_process(
            "http://127.0.0.1:8123/mcp",
            expected_secret="offline-loopback-secret" * 2,
            expected_build_id="server-tree",
            cache_root=cache_root,
        )


def _valid_protocol_document() -> dict[str, Any]:
    tree = pilot.fixture._git("rev-parse", "HEAD:engine/mcp_server")
    return {
        "status": "PREREGISTERED_BEFORE_ANY_PILOT_CALL",
        "fixture_bank_sha256": screen._bank_config(1)["sha256"],
        "runner_sha256": hashlib.sha256(Path(pilot.__file__).read_bytes()).hexdigest(),
        "static_prompt_sha256": hashlib.sha256(
            pilot.STATIC_PROMPT.encode()
        ).hexdigest(),
        "conditioned_prompt_sha256": hashlib.sha256(
            pilot.CONDITIONED_PROMPT.encode()
        ).hexdigest(),
        "request_config": pilot.MODEL_REQUEST_CONFIG,
        "max_outer_mcp_calls": pilot.OUTER_MCP_CALL_LIMIT,
        "max_model_calls": pilot.MODEL_CALL_LIMIT,
        "model_name": MODEL,
        "model_boundary_sha256": {
            relative: screen._sha256(pilot.ROOT / relative)
            for relative in MODEL_BOUNDARY_FILES
        },
        "mcp_tree": tree,
        "mcp_build_id": tree,
    }


def test_protocol_pins_the_free_model_admission_and_dispatch_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol = _valid_protocol_document()
    protocol["model_boundary_sha256"][MODEL_BOUNDARY_FILES[1]] = "0" * 64
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG", path)
    monkeypatch.setattr(
        pilot,
        "_committed_protocol_bytes",
        lambda _: path.read_bytes(),
        raising=False,
    )

    with pytest.raises(ValueError, match="model admission/dispatch sources"):
        pilot._load_pilot_protocol()


def test_protocol_file_must_match_a_committed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(_valid_protocol_document()), encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG", path)
    monkeypatch.setattr(
        pilot,
        "_committed_protocol_bytes",
        lambda _: b"different committed bytes",
        raising=False,
    )

    with pytest.raises(ValueError, match="must be committed unchanged"):
        pilot._load_pilot_protocol()


def test_unresolved_model_protocol_is_not_authorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol = {
        "status": "PREPARED_MODEL_UNRESOLVED_NOT_AUTHORIZED",
        "model_name": None,
    }
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG", path)
    monkeypatch.setattr(
        pilot,
        "_committed_protocol_bytes",
        lambda _: path.read_bytes(),
        raising=False,
    )

    with pytest.raises(ValueError, match="Pilot protocol is not preregistered"):
        pilot._load_pilot_protocol()
