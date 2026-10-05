from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from co_scientist import config as config_mod
from co_scientist.agents.generation import literature_tools
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.generation.literature_tools import draft, validate
from co_scientist.config import ToolConfig, ToolRegistry, WorkflowConfig
from co_scientist.config.schema import ResponseFormat
from co_scientist.constants import corpus_slug
from co_scientist.exceptions import ResponseParseError
from co_scientist.models import GenerationMethod
from tests._mcp import make_tool_results_client
from tests._state import make_article, make_generation_response, make_state


@pytest.fixture
def tools_node(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    def no_registry() -> Any:
        raise RuntimeError("no global registry")

    monkeypatch.setattr(config_mod, "get_tool_registry", no_registry)

    async def run(
        *,
        draft_response: str = '{"drafts": [{"text": "draft"}]}',
        synthesis_response: str | None = None,
        client: Any = None,
        state_overrides: dict[str, Any] | None = None,
        draft_capture: list[dict[str, Any]] | None = None,
        synthesis_call: Any = None,
        novelty_call: Any = None,
    ) -> dict[str, Any]:
        if client is None:
            client = make_tool_results_client()

        async def get_client(**_: Any) -> Any:
            return client

        async def draft_call(**kwargs: Any) -> tuple[str, list[Any]]:
            if draft_capture is not None:
                draft_capture.append(kwargs)
            return draft_response, [
                {"role": "user"},
                {"role": "assistant", "tool_calls": [{"id": "lookup"}]},
                {"role": "tool", "content": "evidence"},
                {"role": "assistant", "content": "closing draft"},
            ]

        async def synthesize(**_: Any) -> tuple[str, list[Any]]:
            return synthesis_response or json.dumps(
                make_generation_response("validated")
            ), []

        monkeypatch.setattr(literature_tools, "get_mcp_client", get_client)
        monkeypatch.setattr(draft, "call_llm_with_tools", draft_call)
        monkeypatch.setattr(
            validate, "call_llm_with_tools", synthesis_call or synthesize
        )
        if novelty_call is not None:
            monkeypatch.setattr(validate, "call_llm_json", novelty_call)
        return await generate_node(
            make_state(
                generation_strategy="dev_isolation",
                initial_hypotheses_count=2,
                enable_tool_calling_generation=True,
                **{
                    "supervisor_guidance": {"key_areas": ["mechanism"]},
                    **(state_overrides or {}),
                },
            )
        )

    return run


@pytest.mark.parametrize(
    "draft_response",
    [
        (
            '{"drafts": [{"text": "alpha", "gap_reasoning": "gap", '
            '"literature_sources": "Smith 2020"}, {"text": "beta"}]}'
        ),
        '```json\n{"drafts": [{"text": "alpha"}]}\n```',
        '{"drafts": [{"text": "alpha"},]}',
        '{"drafts": {"text": "alpha", "gap_reasoning": "gap"}}',
    ],
    ids=["plain", "fenced", "trailing-comma", "unwrapped"],
)
async def test_tool_generation_recovers_drafts_and_counts_closing_turns(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
    draft_response: str,
) -> None:
    result = await tools_node(draft_response=draft_response)
    assert [hypothesis.text for hypothesis in result["hypotheses"].items] == [
        "validated"
    ]
    assert (
        result["hypotheses"].items[0].generation_method
        is GenerationMethod.LITERATURE_TOOLS
    )
    assert result["metrics"].hypothesis_count == 1
    assert result["metrics"].llm_calls == 3


@pytest.mark.parametrize(
    "draft_response", ['{"notes": "no drafts"}', '{"drafts": []}']
)
async def test_tool_generation_with_no_drafts_finishes_with_an_empty_pool(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
    draft_response: str,
) -> None:
    result = await tools_node(draft_response=draft_response)
    assert result["hypotheses"].items == []
    assert result["hypothesis_count"] == 0
    assert result["metrics"].llm_calls == 2


async def test_unparseable_drafting_fails_generation(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
) -> None:
    with pytest.raises(ResponseParseError):
        await tools_node(draft_response="the agent emitted no JSON")


async def test_unparseable_synthesis_drops_failed_generated_items(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
) -> None:
    result = await tools_node(synthesis_response="no JSON from synthesis")
    assert result["hypotheses"].items == []
    assert result["hypothesis_count"] == 0


@pytest.mark.parametrize(
    ("payload", "texts"),
    [
        (
            {
                "hypotheses": [
                    {
                        "hypothesis": "alpha",
                        "explanation": "fits",
                        "experiment": "assay",
                        "novelty_validation": "novel",
                    },
                    {"hypothesis": "beta", "literature_grounding": None},
                ]
            },
            ["alpha", "beta"],
        ),
        (
            {"hypotheses": {"hypothesis": "alpha", "explanation": "fits"}},
            ["alpha"],
        ),
        ({"hypotheses": [{"text": "alpha", "explanation": "fits"}]}, ["alpha"]),
        ('{"hypotheses": [{"hypothesis": "alpha"}', ["alpha"]),
    ],
    ids=["batch", "unwrapped", "text-key", "truncated"],
)
async def test_tool_generation_publishes_repaired_synthesis(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
    payload: Any,
    texts: list[str],
) -> None:
    result = await tools_node(
        synthesis_response=payload
        if isinstance(payload, str)
        else json.dumps(payload)
    )
    hypotheses = result["hypotheses"].items
    assert [hypothesis.text for hypothesis in hypotheses] == texts
    assert all(
        hypothesis.generation_method is GenerationMethod.LITERATURE_TOOLS
        for hypothesis in hypotheses
    )
    assert hypotheses[0].citation_map == {}
    if len(texts) == 2:
        assert hypotheses[0].experiment == "assay"
        assert hypotheses[0].novelty_validation == "novel"
        assert hypotheses[1].literature_grounding is None
    else:
        assert hypotheses[0].experiment is None


async def test_tool_generation_resolves_its_warm_literature_citations(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
) -> None:
    result = await tools_node(
        synthesis_response=json.dumps(
            make_generation_response(
                "cited", literature_grounding="As shown in [C1]."
            )
        ),
        state_overrides={
            "articles": [
                make_article(title="Smith 2020", used_in_analysis=True)
            ]
        },
    )
    source = result["hypotheses"].items[0].citation_map["C1"]
    assert source["title"] == "Smith 2020"
    assert source["type"] == "paper"


@pytest.mark.parametrize("run_id", [None, "run-1"])
@pytest.mark.parametrize(
    "mode", ["legacy", "configured", "utility-only", "global"]
)
async def test_tool_generation_searches_the_configured_novelty_source(
    monkeypatch: pytest.MonkeyPatch,
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
    run_id: str | None,
    mode: str,
) -> None:
    original = "This confirms an earlier result (Smith et al. 2019) [12]."
    records = {
        "p1": {
            "title": "Prior work",
            "authors": ["Doe"],
            "year": 2020,
            "fulltext": original,
        }
    }
    client = make_tool_results_client(
        {"pubmed_search_with_fulltext": records, "search_papers": records}
    )
    overrides: dict[str, Any] = {"run_id": run_id}
    if mode != "legacy":
        registry = ToolRegistry(skip_user_config=True)
        registry.config.tools = {
            "tools": {
                "search": ToolConfig(
                    server="s",
                    mcp_tool_name="search_papers",
                    category="utility" if mode == "utility-only" else "search",
                    response_format=ResponseFormat(
                        is_dict=True,
                        field_mapping={
                            "title": "title",
                            "authors": "authors",
                            "year": "year",
                            "content": "fulltext",
                            "source_id": "@key",
                        },
                    ),
                )
            }
        }
        registry.config.workflows = {
            name: WorkflowConfig(search_tools=["search"])
            for name in ("validation", "draft_generation")
        }
        if mode == "global":
            monkeypatch.setattr(
                config_mod, "get_tool_registry", lambda: registry
            )
        else:
            overrides["tool_registry"] = registry
    prompts: list[str] = []

    async def novelty(*, prompt: str, **_: Any) -> dict[str, Any]:
        prompts.append(prompt)
        return {
            "novelty_assessment": "novel",
            "key_findings": "alpha lacks prior tests",
        }

    synthesis_prompts: list[str] = []

    async def synthesize(*, prompt: str, **_: Any) -> tuple[str, list[Any]]:
        synthesis_prompts.append(prompt)
        return json.dumps(make_generation_response("validated")), []

    result = await tools_node(
        client=client,
        state_overrides=overrides,
        novelty_call=novelty,
        synthesis_call=synthesize,
    )
    assert result["hypotheses"].items[0].text == "validated"
    if mode == "utility-only":
        assert prompts == []
        assert client.calls == []
    else:
        assert "Prior work" in prompts[0]
        assert "(Smith et al. 2019)" not in prompts[0]
        assert "[12]" not in prompts[0]
        assert records["p1"]["fulltext"] == original
        assert "alpha lacks prior tests" in synthesis_prompts[0]
        name, params = client.calls[0]
        # Global fallback resolves for tool loops; novelty still uses the run's
        # explicit registry and preserves its direct-PubMed fallback.
        assert name == (
            "search_papers"
            if mode == "configured"
            else "pubmed_search_with_fulltext"
        )
        assert params["slug"] == corpus_slug(make_state()["research_goal"])
        if mode == "configured" and run_id is None:
            assert "run_id" not in params
        else:
            assert params["run_id"] == run_id


@pytest.mark.parametrize("retry_result", ["recovered", "empty", "failed"])
async def test_synthesis_retries_failed_items_without_discarding_siblings(
    monkeypatch: pytest.MonkeyPatch,
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
    retry_result: str,
) -> None:
    monkeypatch.setattr(validate, "VALIDATION_SYNTHESIS_BATCH_SIZE", 2)
    retry_prompts: dict[str, str] = {}

    async def synthesize(
        *, prompt: str, options: Any, **_: Any
    ) -> tuple[str, list[Any]]:
        label = options.prompt_name
        if label == "validation_synthesis_batch_1":
            raise RuntimeError("batch failed")
        if label == "validation_synthesis_batch_2":
            return json.dumps(
                {"hypotheses": [{"hypothesis": "successful sibling"}]}
            ), []
        retry_prompts[label] = prompt
        if label.endswith("retry_2") or retry_result == "failed":
            raise RuntimeError("item failed")
        payload = (
            {"hypothesis": "recovered item"}
            if retry_result == "recovered"
            else {"text": "text-key item"}
        )
        return json.dumps({"hypotheses": [payload]}), []

    result = await tools_node(
        draft_response=json.dumps(
            {
                "drafts": [
                    {"text": name} for name in ("first", "second", "third")
                ]
            }
        ),
        synthesis_call=synthesize,
    )
    expected = ["successful sibling"]
    if retry_result != "failed":
        expected.append(
            "recovered item" if retry_result == "recovered" else "text-key item"
        )
    assert [
        hypothesis.text for hypothesis in result["hypotheses"].items
    ] == expected
    assert (
        "successful sibling"
        in retry_prompts["validation_synthesis_batch_1_retry_1"]
    )
    second_prompt = retry_prompts["validation_synthesis_batch_1_retry_2"]
    assert (
        "recovered item" in second_prompt
        if retry_result == "recovered"
        else "recovered item" not in second_prompt
    )


async def test_unavailable_mcp_client_fails_tool_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(**_: Any) -> Any:
        raise RuntimeError("mcp unreachable")

    monkeypatch.setattr(literature_tools, "get_mcp_client", unavailable)
    with pytest.raises(RuntimeError, match="mcp unreachable"):
        await generate_node(
            make_state(
                generation_strategy="dev_isolation",
                supervisor_guidance={"key_areas": ["mechanism"]},
            )
        )


@pytest.mark.parametrize(
    ("guidance", "expected"),
    [
        (
            {
                "workflow_plan": {
                    "generation_phase": {"focus_areas": ["biomarkers"]}
                },
                "config_synthesis": {
                    "preferences": ["testable within two years"],
                    "draft_instructions": [
                        "anchor each idea in a reported result"
                    ],
                    "debate_instructions": ["attack the weakest causal link"],
                    "review_instructions": [
                        "penalize restatements of known biology"
                    ],
                },
            },
            [
                "**Focus on:** biomarkers",
                "- testable within two years",
                "anchor each idea in a reported result",
            ],
        ),
        (
            {"config_synthesis": {"preferences": "must be falsifiable"}},
            ["- must be falsifiable\n"],
        ),
        ({"workflow_plan": "draft broadly", "config_synthesis": "be bold"}, []),
        ({"workflow_plan": {"generation_phase": "focus on kinases"}}, []),
        ({"unrelated": 1}, []),
    ],
    ids=[
        "plan",
        "string-preference",
        "scalar-plan",
        "scalar-phase",
        "unrelated",
    ],
)
async def test_generation_drafting_receives_only_its_supervisor_guidance(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
    guidance: dict[str, Any],
    expected: list[str],
) -> None:
    calls: list[dict[str, Any]] = []
    result = await tools_node(
        state_overrides={"supervisor_guidance": guidance}, draft_capture=calls
    )
    prompt = calls[0]["prompt"]
    assert ("## Supervisor Guidance for Generation" in prompt) == bool(expected)
    assert all(text in prompt for text in expected)
    assert "attack the weakest causal link" not in prompt
    assert "penalize restatements of known biology" not in prompt
    assert "- m\n" not in prompt
    assert "{{MISSING" not in prompt
    assert result["hypotheses"].items[0].text == "validated"
