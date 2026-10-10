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


@pytest.mark.parametrize(
    ("role", "effort"),
    [
        ("evidence_queries", "max"),
        ("grounding_queries", "max"),
        ("research_extract", "max"),
        ("reflection", "max"),
        ("generation", "max"),
        ("supervisor", "max"),
        ("overview_outline", "max"),
        ("chat", "medium"),
        ("interview", "medium"),
    ],
)
async def test_free_route_reasons_at_maximum_effort_except_conversation(
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
        CompletionSpec(model_name=LUNA, role="drafting"),
        ToolLoop(SEARCH_TOOL, echo_executor, max_iterations=1),
        LLMCallOptions(effort="low", enable_thinking=False),
    )
    assert answer == "Observed result"
    assert len(captured) == 2
    assert all(policy.role == "drafting" and not policy.enable_thinking for policy, _ in captured)
    assert all(args["reasoning_effort"] == "none" for _, args in captured)
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
    with scoped_call_policy("claims"):
        assert current_call_policy().effort == current_call_policy().azure_effort == "none"


@pytest.mark.parametrize(
    ("role", "effort", "azure_effort"),
    [
        ("generation", "medium", "low"),
        ("review", "medium", "low"),
        ("ranking", "low", "low"),
        ("safety", "low", "low"),
        ("claims", "low", "low"),
        ("literature_queries", "low", "none"),
        ("relevance", "low", "none"),
        ("goal_text", "low", "none"),
        ("supervisor", "medium", "low"),
        ("meta_review", "medium", "low"),
        ("overview_review", "low", "low"),
        ("overview_outline", "none", "none"),
    ],
)
async def test_azure_runs_every_role_on_luna_at_lowest_effort_or_none(
    monkeypatch: pytest.MonkeyPatch, role: CallRole, effort: str, azure_effort: str
) -> None:
    captured: list[dict[str, Any]] = []

    async def respond(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return make_completion(make_message('{"ok":1}'))

    install_fake_backend(monkeypatch, respond)
    with scoped_call_policy(role):
        assert current_call_policy().effort == effort
    assert await call_llm_json(
        "Answer", CompletionSpec(model_name=LUNA, role=role), max_attempts=1
    ) == {"ok": 1}
    assert captured[0]["reasoning_effort"] == azure_effort


def test_azure_prices_include_cache_write_and_long_context_without_guessing_deployment() -> None:
    luna = model_profile(LUNA)
    assert luna.version == "2026-09-22"
    assert luna.price is not None and luna.price.long_context is not None
    assert luna.price.cache_write_usd_per_million == 0.125
    assert luna.price.long_context.cache_write_usd_per_million == 0.25
    assert model_profile("azure/gpt-5-nano-2025-08-07").price is None
    assert model_profile("azure/unmapped-deployment").price is None


def test_luna_charges_short_rates_up_to_its_published_boundary() -> None:
    from co_scientist.platform.llm.admission.spend import _model_rates, price_cost

    rates = {**_model_rates(LUNA), "fx": "1"}
    assert price_cost(rates, 272_000, 0, cached=0, written=0) == 27_200
    assert price_cost(rates, 272_001, 0, cached=0, written=0) == 54_401
    legacy = {name: value for name, value in rates.items() if not name.startswith("short_")}
    assert price_cost(legacy, 272_000, 0, cached=0, written=0) == 54_400


def test_express_estimate_uses_luna_short_rates_for_bounded_inputs() -> None:
    from decimal import Decimal

    from co_scientist.platform.llm.admission.spend import SpendConfig
    from co_scientist.platform.llm.routing import express_estimate

    azure = SpendConfig(10_000_000, Decimal("1"), float("inf"))
    config = {"max_llm_calls": 1200}
    assert express_estimate("g", config, azure) == 57 * 101_025 * 6 // 10 + 360_000
    long_goal = "g" * 200_000
    assert express_estimate(long_goal, config, azure) == -(-57 * 301_024 * 12 // 10) + 540_000
