"""Campaign results and user credentials must not share node-cache output."""

from pathlib import Path

import pytest

from co_scientist.cache import NodeCache
from co_scientist.llm_credentials import scoped_api_key


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("scope", ["campaign", "byok"])
def test_isolated_execution_cannot_read_or_replace_shared_node_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force: bool, scope: str
) -> None:
    cache = NodeCache(cache_dir=str(tmp_path))
    params = {"research_goal": "public goal", "model_name": "same-model"}
    cache.set("literature_review", {"text": "previous run"}, **params)
    with monkeypatch.context() as patch:
        if scope == "campaign":
            patch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        with scoped_api_key("user-key" if scope == "byok" else None):
            assert cache.get("literature_review", force=force, **params) is None
            cache.set(
                "literature_review",
                {"text": "isolated run"},
                force=force,
                **params,
            )
    assert cache.get("literature_review", **params) == {"text": "previous run"}


async def test_campaign_literature_node_does_not_replay_previous_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist.agents.generation.literature_review import node as lr
    from co_scientist.constants import LITERATURE_REVIEW_FAILED
    from tests._literature_node import _stub_node
    from tests._state import make_state

    _stub_node(monkeypatch, server_available=False)
    cache = NodeCache(cache_dir=str(tmp_path))
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    state = make_state(research_goal="public research")
    state["dev_test_lit_tools_isolation"] = True
    cache.set(
        "literature_review",
        {"articles_with_reasoning": "previous paid review"},
        **lr._literature_cache_params(state, lr._get_search_config(state)),
    )
    previous = await lr.literature_review_node(state)
    assert previous["articles_with_reasoning"] == "previous paid review"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    fresh = await lr.literature_review_node(state)
    assert fresh["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert fresh["retrieval_degradation"]["reason"] == "mcp_unreachable"
