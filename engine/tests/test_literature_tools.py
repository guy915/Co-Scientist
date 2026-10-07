from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from co_scientist import config as config_mod
from co_scientist.agents.generation import literature_tools
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.generation.literature_tools import draft, validate
from co_scientist.core.exceptions import ResponseParseError
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
            return synthesis_response or json.dumps(make_generation_response("validated")), []

        monkeypatch.setattr(literature_tools, "get_mcp_client", get_client)
        monkeypatch.setattr(draft, "call_llm_with_tools", draft_call)
        monkeypatch.setattr(validate, "call_llm_with_tools", synthesis_call or synthesize)
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


async def test_unparseable_drafting_fails_generation(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
) -> None:
    with pytest.raises(ResponseParseError):
        await tools_node(draft_response="the agent emitted no JSON")


async def test_tool_generation_resolves_its_warm_literature_citations(
    tools_node: Callable[..., Awaitable[dict[str, Any]]],
) -> None:
    result = await tools_node(
        synthesis_response=json.dumps(
            make_generation_response("cited", literature_grounding="As shown in [C1].")
        ),
        state_overrides={"articles": [make_article(title="Smith 2020", used_in_analysis=True)]},
    )
    source = result["hypotheses"].items[0].citation_map["C1"]
    assert source["title"] == "Smith 2020"
    assert source["type"] == "paper"
