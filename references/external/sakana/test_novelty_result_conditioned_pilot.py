"""Offline behavior tests for the matched result-conditioned search pilot."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
    ) -> None:
        self.cache_root = cache_root
        self.events = events
        self.server_url = "http://127.0.0.1:8123/mcp"
        self.fail_on_call = fail_on_call
        self.abstract_suffix = abstract_suffix
        self.response_override = response_override
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
        )
    )


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
