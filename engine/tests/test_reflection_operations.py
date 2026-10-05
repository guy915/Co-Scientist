from __future__ import annotations

import asyncio
import json
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import co_scientist.agents.reflection.deep_verification as leaf
from co_scientist.agents.reflection import (
    ReviewRun,
    ReviewType,
    apply_initial_review_gate,
    deep_verification_evidence,
    has_valid_verification,
    observe_hypothesis,
    review_hypothesis,
    select_hypotheses_to_verify,
    verify_hypothesis,
)
from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import (
    comprehensive_reflection as review_prompt_context,
)
from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.agents.reflection import reflection as observation
from co_scientist.agents.reflection.deep_verification import (
    mark_verification_issued,
    verification_fingerprint,
)
from co_scientist.agents.reflection.reflection_helpers import (
    _agent_name,
    _fetch_evidence_result,
    _format_evidence,
    _pick_available_tool,
    fetch_indra_evidence,
)
from co_scientist.agents.reflection.review_evidence import _ReviewEvidence
from co_scientist.config import ToolRegistry
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from tests._llm_fake import mock_call_llm_json
from tests._mcp import WorkflowToolRegistry
from tests._state import make_article, make_hypothesis, make_review, make_state


def _fake_registry() -> ToolRegistry:
    """Knowledge-graph source typing is required because literature tools
    reject INDRA arguments."""
    return cast(
        ToolRegistry,
        WorkflowToolRegistry(
            ["indra_relations"],
            ["get_relations"],
            tool_mcp_names={"indra_relations": "get_relations"},
        ),
    )


class _FakeMcpClient:
    def __init__(
        self,
        available_tools: set[str],
        responses: dict[str, Any] | None = None,
    ) -> None:
        self._available_tools = available_tools
        self._responses = responses or {}

    def has_tool(self, name: str) -> bool:
        return name in self._available_tools

    async def call_tool(self, _tool_name: str, **kwargs: Any) -> Any:
        entity = kwargs["agent"]
        if entity not in self._responses:
            return {"statements": []}
        response = self._responses[entity]
        if response is None:
            raise RuntimeError(f"simulated query failure for {entity}")
        return response


_ACTIVATION_STATEMENT = {
    "type": "Activation",
    "belief": 0.9,
    "evidence": [1, 2],
    "subj": {"name": "KRAS"},
    "obj": {"name": "BRAF"},
}


def test_pick_available_tool_returns_first_match() -> None:
    client = _FakeMcpClient(available_tools={"get_relations"})
    assert (
        _pick_available_tool(client, ["get_complexes", "get_relations"])
        == "get_relations"
    )


def test_pick_available_tool_none_available_returns_empty_string() -> None:
    client = _FakeMcpClient(available_tools=set())
    assert _pick_available_tool(client, ["get_relations"]) == ""


async def test_fetch_evidence_result_no_tool_available_returns_none() -> None:
    client = _FakeMcpClient(available_tools=set())
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is None


async def test_fetch_evidence_result_no_statements_returns_none() -> None:
    client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={"KRAS": {"statements": []}, "TREM2": {"statements": []}},
    )
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is None


async def test_fetch_evidence_result_one_entity_fails_other_succeeds() -> None:
    client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={
            "KRAS": None,
            "TREM2": json.dumps({"statements": [_ACTIVATION_STATEMENT]}),
        },
    )
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is not None
    assert "KRAS --[Activation]--> BRAF" in result["prompt_text"]
    assert len(result["enrichment_items"]) == 1
    assert result["enrichment_items"][0]["relationship"] == "KRAS → BRAF"


async def test_fetch_indra_evidence_no_entities_returns_empty() -> None:
    result = await fetch_indra_evidence(
        "the quick brown fox jumps over the lazy dog",
        tool_registry=_fake_registry(),
    )
    assert result == {"prompt_text": "", "enrichment_items": []}


async def test_fetch_indra_evidence_returns_client_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={
            "KRAS": json.dumps({"statements": [_ACTIVATION_STATEMENT]}),
        },
    )

    async def fake_get_mcp_client(**_: Any) -> _FakeMcpClient:
        return fake_client

    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client", fake_get_mcp_client
    )

    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=_fake_registry()
    )

    assert "KRAS --[Activation]--> BRAF" in result["prompt_text"]
    assert result["enrichment_items"]


async def test_fetch_indra_evidence_swallows_client_construction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def raising_get_mcp_client(**_: Any) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client", raising_get_mcp_client
    )

    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=_fake_registry()
    )

    assert result == {"prompt_text": "", "enrichment_items": []}


def test_format_evidence_renders_header_and_valid_statement_lines() -> None:
    malformed = {"type": "Unknown"}
    text = _format_evidence(
        [_ACTIVATION_STATEMENT, malformed], ["KRAS", "BRAF"]
    )
    assert text.startswith(
        "Structured knowledge from the INDRA biomedical knowledge graph "
        "(queried for: KRAS, BRAF):"
    )
    assert "KRAS --[Activation]--> BRAF" in text
    assert text.count("\n") == 1


def test_format_evidence_no_renderable_statements_returns_empty() -> None:
    assert _format_evidence([{"type": "Unknown"}], ["KRAS"]) == ""
    assert _format_evidence([], ["KRAS"]) == ""


def test_agent_name_extracts_dict_name() -> None:
    assert _agent_name({"subj": {"name": "KRAS"}}, "subj") == "KRAS"


def test_agent_name_non_dict_agent_returns_empty_string() -> None:
    assert _agent_name({"subj": "KRAS"}, "subj") == ""


def test_agent_name_missing_role_returns_empty_string() -> None:
    assert _agent_name({}, "obj") == ""


def test_verification_context_excludes_retracted_evidence() -> None:
    state = make_state(
        articles=[
            make_article(
                "Retracted paper",
                abstract="Withdrawn mechanistic claim.",
                used_in_analysis=True,
                is_retracted=True,
            ),
            make_article(
                "Standing paper",
                abstract="Replicated mechanistic finding.",
                used_in_analysis=True,
            ),
        ]
    )

    context = dv._verification_evidence_context(state)

    assert "Standing paper" in context
    assert "Retracted paper" not in context
    assert "Withdrawn mechanistic claim" not in context


def test_review_context_excludes_retracted_evidence() -> None:
    state = make_state(
        articles=[
            make_article(
                "Retracted paper",
                abstract="Withdrawn mechanistic claim.",
                used_in_analysis=True,
                is_retracted=True,
            )
        ]
    )

    assert review_prompt_context._build_domain_context(state, None) == ""


def test_probe_context_excludes_retracted_evidence() -> None:
    """Retraction checks belong at formatting boundaries too, not only
    retrieval."""
    retracted = make_article(
        "Retracted probe hit",
        abstract="Withdrawn mechanistic claim.",
        is_retracted=True,
    )

    assert (
        deep_verification_evidence._retrieved_evidence_context([retracted])
        == ""
    )


def test_verification_context_falls_back_to_article_fulltext() -> None:
    state = make_state(
        articles=[
            make_article(
                "Fulltext-only paper",
                abstract="",
                content="Measured a three-fold increase in flux.",
                used_in_analysis=True,
            )
        ]
    )

    context = dv._verification_evidence_context(state)

    assert "Measured a three-fold increase in flux." in context


def test_review_context_falls_back_to_article_fulltext() -> None:
    state = make_state(
        articles=[
            make_article(
                "Fulltext-only paper",
                abstract="",
                content="Measured a three-fold increase in flux.",
                used_in_analysis=True,
            )
        ]
    )

    context = review_prompt_context._build_domain_context(state, None)

    assert "Measured a three-fold increase in flux." in context


def test_one_source_truncates_the_same_way_on_every_path() -> None:
    abstract = "mechanism " * 500
    state = make_state(
        articles=[
            make_article("Long paper", abstract=abstract, used_in_analysis=True)
        ]
    )

    review = review_prompt_context._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    assert abstract[:2000] in review
    assert abstract[:2000] in verification


def test_private_sources_get_a_wider_slice_than_public_ones() -> None:
    display = "private finding " * 300
    state = make_state(context_enrichment_sources=[{"display": display}])

    review = review_prompt_context._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    assert display[:2500] in review
    assert display[:2500] in verification


def test_public_article_citation_markers_are_stripped() -> None:
    """Copied source citations can misattribute generated claims to real
    papers."""
    abstract = "This confirms prior work (Smith et al. 2019) [12]."
    state = make_state(
        articles=[
            make_article(
                "Cited paper", abstract=abstract, used_in_analysis=True
            )
        ]
    )

    review = review_prompt_context._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    for context in (review, verification):
        assert "(Smith et al. 2019)" not in context
        assert "[12]" not in context


def test_private_source_citation_markers_are_kept() -> None:
    """Scientist-supplied markers are intentional input rather than retrieved
    contamination."""
    display = "See our finding (Doe et al. 2020) for the full protocol."
    state = make_state(context_enrichment_sources=[{"display": display}])

    verification = dv._verification_evidence_context(state)

    assert "(Doe et al. 2020)" in verification


def test_building_context_leaves_the_article_abstract_unchanged() -> None:
    original = "This confirms prior work (Smith et al. 2019) [12]."
    article = make_article(
        "Cited paper", abstract=original, used_in_analysis=True
    )
    state = make_state(articles=[article])

    dv._verification_evidence_context(state)

    assert article.abstract == original


def test_gate_honors_scientist_criteria_and_safety() -> None:
    ideas = [make_hypothesis(), make_hypothesis()]
    reviews = [
        make_review(scores={"novelty": 1, "testability": 8, "safety": 8}),
        make_review(scores={"testability": 8, "safety": 1}),
    ]
    apply_initial_review_gate(ideas, reviews, ["Experimental feasibility"])
    assert [idea.review_disposition for idea in ideas] == ["viable", "unsafe"]


def test_selection_preserves_pool_order_and_once_ever_markers() -> None:
    pending = make_hypothesis()
    blocked = make_hypothesis(review_disposition="unsafe")
    issued = make_hypothesis()
    mark_verification_issued(issued)
    current = make_hypothesis()
    current.deep_verification_fingerprint = verification_fingerprint(
        current, "m"
    )
    next_pending = make_hypothesis()
    assert select_hypotheses_to_verify(
        [pending, blocked, issued, current, next_pending], "m"
    ) == [pending, next_pending]
    assert not pending.enrichments


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"verdict": None},
        {"verdict": "unverified"},
        {"verdict": "unknown"},
        {"verdict": []},
        {"verdict": {}},
    ],
)
def test_invalid_verification(result: dict[str, Any] | None) -> None:
    assert not has_valid_verification(result)


@pytest.mark.parametrize("verdict", ["holds", "weakened", "undermined"])
def test_valid_verification(verdict: str) -> None:
    assert has_valid_verification({"verdict": verdict})


@pytest.mark.asyncio
async def test_single_verification_assembles_bounded_context_and_local_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphores: list[asyncio.Semaphore] = []
    contexts: list[str] = []

    async def capture(
        semaphore: asyncio.Semaphore,
        hypothesis: Any,
        context: Any,
        evidence: str,
    ) -> dict[str, Any]:
        assert context.state is state
        semaphores.append(semaphore)
        contexts.append(evidence)
        return {"verdict": "holds"}

    state = make_state(
        articles=[
            make_article(
                "Long evidence", abstract="x" * 100000, used_in_analysis=True
            )
        ],
        context_enrichment_sources=[{"display": "y" * 100000}],
        meta_review={"common_weaknesses": ["Recurring assumption error"]},
    )
    monkeypatch.setattr(leaf, "_verify_within_semaphore", capture)
    for _ in range(2):
        assert await verify_hypothesis(state, make_hypothesis()) == {
            "verdict": "holds"
        }
    assert semaphores[0] is not semaphores[1]
    assert all(semaphore._value == 1 for semaphore in semaphores)
    assert all(len(context) < 20000 for context in contexts)
    assert "Long evidence" in contexts[0]
    assert "Recurring assumption error" in contexts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,owner",
    [
        (verify_hypothesis, leaf),
        (observe_hypothesis, observation),
        (review_hypothesis, cr),
    ],
)
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("ordinary"),
        LLMRateLimitParkError(9999, "cap"),
        LLMCallBudgetExceededError(2, 1),
    ],
)
async def test_failures_degrade_but_task_control_propagates(
    monkeypatch: pytest.MonkeyPatch,
    operation: Any,
    owner: Any,
    error: Exception,
) -> None:
    mock_call_llm_json(monkeypatch, owner, side_effect=error)
    state = make_state(articles_with_reasoning="Retrieved literature")
    args = (
        (state, make_hypothesis(), ReviewType.FULL)
        if operation is review_hypothesis
        else (state, make_hypothesis())
    )
    if isinstance(error, RuntimeError):
        result = await operation(*args)
        assert (
            result.result if isinstance(result, ReviewRun) else result
        ) is None
    else:
        with pytest.raises(type(error)) as caught:
            await operation(*args)
        assert caught.value is error


@pytest.mark.asyncio
async def test_observation_indices_default_to_one_and_support_graph_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = mock_call_llm_json(
        monkeypatch, observation, {"classification": "supports"}
    )
    state = make_state(articles_with_reasoning="Literature")
    default = await observe_hypothesis(state, make_hypothesis())
    indexed = await observe_hypothesis(
        state, make_hypothesis(), hypothesis_index=3, total_count=7
    )
    assert default is not None and indexed is not None
    assert (
        calls.await_args_list[0].kwargs["options"].prompt_name == "reflection_1"
    )
    assert (
        calls.await_args_list[1].kwargs["options"].prompt_name == "reflection_3"
    )


@pytest.mark.asyncio
async def test_mature_review_keeps_ledger_separate_even_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = {"funded_threads": 4}
    monkeypatch.setattr(
        cr,
        "_review_evidence_for",
        AsyncMock(return_value=_ReviewEvidence([], [], [], ledger)),
    )
    mock_call_llm_json(monkeypatch, cr, {"verdict": "sound"})
    run = await review_hypothesis(
        make_state(), make_hypothesis(), ReviewType.FULL
    )
    assert isinstance(run, ReviewRun)
    assert tuple(run) == (ReviewType.FULL, run.result, ledger)
    assert run.result is not None and "research_ledger" not in run.result
    mock_call_llm_json(monkeypatch, cr, side_effect=RuntimeError("bad"))
    failed = await review_hypothesis(
        make_state(), make_hypothesis(), ReviewType.FULL
    )
    assert failed == ReviewRun(ReviewType.FULL, None, ledger)


@pytest.mark.asyncio
async def test_graph_batch_limiter_and_issued_markers_are_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = peak = 0
    semaphores: list[asyncio.Semaphore] = []

    async def verify(
        hypothesis: Any, context: Any, evidence: str
    ) -> dict[str, Any]:
        nonlocal active, peak
        assert hypothesis.enrichments["deep_verification_issued"] is True
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return {}

    original = dv._verify_one

    async def capture_leaf(
        hypothesis: Any,
        context: Any,
        semaphore: asyncio.Semaphore,
        evidence: str,
    ) -> dict[str, Any] | None:
        semaphores.append(semaphore)
        return await original(hypothesis, context, semaphore, evidence)

    monkeypatch.setattr(dv, "MAX_CONCURRENT_LLM_CALLS", 2)
    monkeypatch.setattr(leaf, "_verify_with_probes", verify)
    monkeypatch.setattr(dv, "_verify_one", capture_leaf)
    ideas = [make_hypothesis() for _ in range(5)]
    counts = await dv._run_verification_batch(
        make_state(hypotheses=ideas), ideas
    )
    assert counts == (0, 5, 5)
    assert peak == 2
    assert len({id(semaphore) for semaphore in semaphores}) == 1
    assert all(idea.deep_verification_verdict == "unverified" for idea in ideas)


@pytest.mark.asyncio
async def test_public_verification_reuses_funded_review_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.reflection import review_evidence

    idea = make_hypothesis()
    state = make_state()
    funded = make_article("Already funded research", source_id="funded")
    evidence = _ReviewEvidence([], [funded], [], {"threads": 4})
    loop = asyncio.get_running_loop()
    completed = loop.create_task(AsyncMock(return_value=evidence)())
    await completed
    review_evidence._review_evidence_flights.setdefault(loop, {})[
        review_evidence._evidence_key(state, idea)
    ] = completed
    calls = mock_call_llm_json(monkeypatch, leaf, {"verdict": "holds"})
    monkeypatch.setattr(
        leaf, "_retrieve_probe_evidence", AsyncMock(return_value=([], []))
    )
    result = await verify_hypothesis(state, idea)
    assert result is not None
    assert result["verification_llm_calls"] == 2
    assert [item["source_id"] for item in result["retrieved_articles"]] == [
        "funded"
    ]
    assert (
        "Already funded research" in calls.await_args_list[1].kwargs["prompt"]
    )
    assert "deep_verification_issued" not in idea.enrichments


def test_public_verification_does_not_import_graph_orchestration() -> None:
    import ast
    import inspect

    import co_scientist.agents.reflection.deep_verification as operations

    imports = [
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(operations)))
        if isinstance(node, ast.ImportFrom)
    ]
    assert "co_scientist.agents.reflection.deep_verification" not in imports
