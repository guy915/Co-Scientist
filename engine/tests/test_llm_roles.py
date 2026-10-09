from __future__ import annotations

from typing import Any

import pytest

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_json,
    call_llm_with_tools,
)
from co_scientist.platform.llm.profile import model_profile
from co_scientist.platform.llm.roles import CallRole, current_call_policy, scoped_call_policy
from tests._azure_ledger import record_azure_allowance
from tests._llm_fake import (
    SEARCH_TOOL,
    echo_executor,
    install_fake_backend,
    make_completion,
    make_message,
    make_tool_call,
)

LUNA = "azure/gpt-6-luna-2026-09-22"
NANO = "azure/gpt-5-nano-2025-08-07"


@pytest.mark.parametrize(
    ("role", "effort"),
    [
        ("evidence_queries", "low"),
        ("grounding_queries", "low"),
        ("research_extract", "low"),
        ("reflection", "medium"),
        ("generation", "medium"),
        ("overview_outline", "low"),
    ],
)
async def test_free_route_receives_role_effort_without_changing_price_cap(
    monkeypatch: pytest.MonkeyPatch, role: CallRole, effort: str
) -> None:
    captured: list[dict[str, Any]] = []

    async def respond(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return make_completion(make_message('{"ok":1}'))

    install_fake_backend(monkeypatch, respond)
    assert await call_llm_json(
        "Answer",
        CompletionSpec(model_name="openrouter/inclusionai/ling-3.1-flash", role=role),
        max_attempts=1,
    ) == {"ok": 1}
    body = captured[0]["extra_body"]
    assert body["reasoning"] == {"enabled": True, "effort": effort}
    assert body["provider"]["max_price"] == {
        "prompt": 0.0,
        "completion": 0.0,
        "request": 0.0,
    }
    assert "reasoning_effort" not in captured[0]


@pytest.fixture(autouse=True)
def funded_fake_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_AZURE_ENABLED", "true")
    monkeypatch.setenv("LLM_TOTAL_BUDGET_EUR", "1")
    monkeypatch.setenv("LLM_AZURE_EXPIRES_AT", "2099-01-04T00:00:00+00:00")
    monkeypatch.setenv("LLM_USD_TO_EUR", "0.88")
    record_azure_allowance()


async def test_options_role_and_effort_survive_json_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = []

    async def respond(**kwargs: Any) -> Any:
        captured.append((current_call_policy(), kwargs))
        return make_completion(make_message('{"ok":"wrong"}' if len(captured) == 1 else '{"ok":1}'))

    install_fake_backend(monkeypatch, respond)
    result = await call_llm_json(
        "Answer",
        CompletionSpec(
            model_name=LUNA,
            role="worker",
            json_schema={
                "type": "object",
                "properties": {"ok": {"type": "integer"}},
                "required": ["ok"],
            },
        ),
        max_attempts=2,
        options=LLMCallOptions(role="overview_review", effort="low"),
    )
    assert result == {"ok": 1}
    assert len(captured) == 2
    assert all(
        policy.role == "overview_review" and policy.tier == "supervisor" for policy, _ in captured
    )
    assert all(args["reasoning_effort"] == "low" for _, args in captured)
    assert current_call_policy().role == "worker"


async def test_tool_turn_and_closing_harvest_keep_role_and_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    async def respond(**kwargs: Any) -> Any:
        captured.append((current_call_policy(), kwargs))
        if len(captured) == 1:
            return make_completion(
                make_message(None, tool_calls=[make_tool_call("one", "search", "{}")])
            )
        return make_completion(make_message("Observed result"))

    install_fake_backend(monkeypatch, respond)
    answer, _ = await call_llm_with_tools(
        "Answer",
        CompletionSpec(model_name=NANO, role="drafting"),
        ToolLoop(SEARCH_TOOL, echo_executor, max_iterations=1),
        LLMCallOptions(effort="low", enable_thinking=False),
    )
    assert answer == "Observed result"
    assert len(captured) == 2
    assert all(policy.role == "drafting" and not policy.enable_thinking for policy, _ in captured)
    assert all(args["reasoning_effort"] == "low" for _, args in captured)
    assert "tools" in captured[0][1] and "tools" not in captured[1][1]


def test_role_effort_env_is_read_per_physical_request(monkeypatch: pytest.MonkeyPatch) -> None:
    with scoped_call_policy("overview_outline"):
        assert current_call_policy().effort == "none"
        monkeypatch.setenv("LLM_EFFORT_OVERVIEW_OUTLINE", "low")
        assert current_call_policy().effort == "low"
        monkeypatch.setenv("LLM_EFFORT_OVERVIEW_OUTLINE", "high")
        with pytest.raises(ProviderAdmissionError):
            current_call_policy()
    monkeypatch.setenv("LLM_WORKER_EFFORT", "none")
    with scoped_call_policy("claims"), pytest.raises(ProviderAdmissionError):
        current_call_policy()


def test_azure_prices_include_cache_write_and_long_context_without_guessing_deployment() -> None:
    luna, nano = model_profile(LUNA), model_profile(NANO)
    assert luna.version == "2026-09-22" and nano.version == "2025-08-07"
    assert luna.price is not None and luna.price.long_context is not None and nano.price is not None
    assert luna.price.cache_write_usd_per_million == 0.125
    assert luna.price.long_context.cache_write_usd_per_million == 0.25
    assert nano.price.cache_write_usd_per_million == 0
    assert nano.price.cached_prompt_usd_per_million == 0.01
    assert "none" not in (nano.supported_efforts or ())
    assert model_profile("azure/unmapped-deployment").price is None
