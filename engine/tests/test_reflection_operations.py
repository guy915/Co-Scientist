"""Offline contracts for reflection operations."""

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
from co_scientist.config.schema import ToolConfig
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from tests._state import make_article, make_hypothesis, make_review, make_state


class _FakeRegistry:
    """Minimal duck-typed ToolRegistry stand-in listing one KG tool.

    ``get_tool`` answers with a knowledge-graph-typed config because that
    declaration is what makes a tool reachable from this path: entity
    queries are sent with INDRA's own arguments, which a literature tool
    rejects outright.
    """

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        """Return a single configured tool id for any workflow name."""
        del workflow_name
        return ["indra_relations"]

    def get_tool(self, tool_id: str) -> ToolConfig:
        """Resolve the configured tool id to its knowledge-graph config."""
        del tool_id
        return ToolConfig(
            server="default_pubmed",
            mcp_tool_name="get_relations",
            source_type="knowledge_graph",
        )

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        """Resolve the configured tool id to its MCP server tool name."""
        del tool_ids
        return ["get_relations"]


def _fake_registry() -> ToolRegistry:
    """Build a fake registry typed as ToolRegistry for the helper signatures."""
    return cast(ToolRegistry, _FakeRegistry())


class _FakeMcpClient:
    """Fake MCP client for ``_fetch_evidence_result``/``fetch_indra_evidence``.

    ``has_tool`` reports availability from a fixed set of names; ``call_tool``
    dispatches per-entity via ``responses``, where a value of ``None`` means
    "raise instead of returning" (simulating a failed per-entity query).
    """

    def __init__(
        self,
        available_tools: set[str],
        responses: dict[str, Any] | None = None,
    ) -> None:
        self._available_tools = available_tools
        self._responses = responses or {}

    def has_tool(self, name: str) -> bool:
        """Report whether ``name`` is available on this fake server."""
        return name in self._available_tools

    async def call_tool(self, _tool_name: str, **kwargs: Any) -> Any:
        """Return (or raise) the canned response for the queried entity."""
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


# --- _pick_available_tool ---------------------------------------------------


def test_pick_available_tool_returns_first_match() -> None:
    """The first mcp_name present on the client is returned."""
    client = _FakeMcpClient(available_tools={"get_relations"})
    assert (
        _pick_available_tool(client, ["get_complexes", "get_relations"])
        == "get_relations"
    )


def test_pick_available_tool_none_available_returns_empty_string() -> None:
    """No candidate tool present on the server yields an empty string."""
    client = _FakeMcpClient(available_tools=set())
    assert _pick_available_tool(client, ["get_relations"]) == ""


# --- _fetch_evidence_result ---------------------------------------------


async def test_fetch_evidence_result_no_tool_available_returns_none() -> None:
    """With no candidate tool on the server, the result is None."""
    client = _FakeMcpClient(available_tools=set())
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is None


async def test_fetch_evidence_result_no_statements_returns_none() -> None:
    """A tool that resolves but yields no statements for any entity is None."""
    client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={"KRAS": {"statements": []}, "TREM2": {"statements": []}},
    )
    result = await _fetch_evidence_result(
        client, ["get_relations"], ["KRAS", "TREM2"], max_statements=5
    )
    assert result is None


async def test_fetch_evidence_result_one_entity_fails_other_succeeds() -> None:
    """A per-entity query failure does not block a sibling entity's result.

    KRAS's query raises (exercising the per-entity exception-swallow path)
    while TREM2's query succeeds, so the pooled statement list is non-empty
    and the formatted result is built from it.
    """
    client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={
            "KRAS": None,  # Simulated failure.
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


# --- fetch_indra_evidence: past the tool_registry=None short-circuit -------


async def test_fetch_indra_evidence_no_entities_returns_empty() -> None:
    """A configured registry but entity-free hypothesis text yields empty."""
    result = await fetch_indra_evidence(
        "the quick brown fox jumps over the lazy dog",
        tool_registry=_fake_registry(),
    )
    assert result == {"prompt_text": "", "enrichment_items": []}


async def test_fetch_indra_evidence_returns_client_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful MCP round-trip returns the formatted evidence result."""
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
    """A failure obtaining the MCP client degrades to the empty result."""

    async def raising_get_mcp_client(**_: Any) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client", raising_get_mcp_client
    )

    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=_fake_registry()
    )

    assert result == {"prompt_text": "", "enrichment_items": []}


# --- _format_evidence ---------------------------------------------------


def test_format_evidence_renders_header_and_valid_statement_lines() -> None:
    """Renderable statements follow a header naming the queried entities."""
    malformed = {"type": "Unknown"}  # Neither subj/obj nor members.
    text = _format_evidence(
        [_ACTIVATION_STATEMENT, malformed], ["KRAS", "BRAF"]
    )
    assert text.startswith(
        "Structured knowledge from the INDRA biomedical knowledge graph "
        "(queried for: KRAS, BRAF):"
    )
    assert "KRAS --[Activation]--> BRAF" in text
    # The malformed statement contributes no line.
    assert text.count("\n") == 1


def test_format_evidence_no_renderable_statements_returns_empty() -> None:
    """No renderable statements yields "" rather than a bare header."""
    assert _format_evidence([{"type": "Unknown"}], ["KRAS"]) == ""
    assert _format_evidence([], ["KRAS"]) == ""


# --- _agent_name --------------------------------------------------------


def test_agent_name_extracts_dict_name() -> None:
    """A dict-shaped agent's name field is returned."""
    assert _agent_name({"subj": {"name": "KRAS"}}, "subj") == "KRAS"


def test_agent_name_non_dict_agent_returns_empty_string() -> None:
    """A non-dict agent value (malformed statement) falls back to ""."""
    assert _agent_name({"subj": "KRAS"}, "subj") == ""


def test_agent_name_missing_role_returns_empty_string() -> None:
    """A statement missing the requested role key falls back to ""."""
    assert _agent_name({}, "obj") == ""


def test_verification_context_excludes_retracted_evidence() -> None:
    """A retracted paper never reaches the deep-verification gate.

    The review cascade already refuses retracted evidence, so a paper the
    reviews would not read must not be what the gate that exists to
    challenge a hypothesis's evidence weighs it against.
    """
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
    """The review cascade refuses retracted evidence too."""
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
    """Targeted probe evidence is filtered by the formatter, not only above.

    Retrieval already drops retracted papers, but the rule belongs
    wherever evidence is handed to a model so a future caller cannot
    reintroduce one by formatting its own list.
    """
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
    """An abstract-less source contributes its fulltext, not nothing.

    Retrieval marks an article analyzed on either field, so an abstract-less
    one with real fulltext used to be an empty section in the verification
    prompt while contributing its text to every other reflection prompt.
    """
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
    """The review cascade reads fulltext when the abstract is empty."""
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
    """A source's excerpt does not depend on which prompt is asking."""
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
    """Private, scientist-supplied context is quoted at greater length."""
    display = "private finding " * 300
    state = make_state(context_enrichment_sources=[{"display": display}])

    review = review_prompt_context._build_domain_context(state, None)
    verification = dv._verification_evidence_context(state)

    assert display[:2500] in review
    assert display[:2500] in verification


def test_public_article_citation_markers_are_stripped() -> None:
    """A source's own citations do not reach either reflection prompt.

    Left in, a review or verification model can copy one into its own
    prose -- a real-looking reference attached to a claim the cited
    source never made.
    """
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
    """A scientist-supplied source's own citations are not contamination.

    Unlike a retrieved paper's markers, these are the scientist's
    intentional content, not text a model could mistake for its own.
    """
    display = "See our finding (Doe et al. 2020) for the full protocol."
    state = make_state(context_enrichment_sources=[{"display": display}])

    verification = dv._verification_evidence_context(state)

    assert "(Doe et al. 2020)" in verification


def test_building_context_leaves_the_article_abstract_unchanged() -> None:
    """Stripping is for the prompt copy only, never for storage."""
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
    monkeypatch.setattr(owner, "call_llm_json", AsyncMock(side_effect=error))
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
    calls = AsyncMock(return_value={"classification": "supports"})
    monkeypatch.setattr(observation, "call_llm_json", calls)
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
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    run = await review_hypothesis(
        make_state(), make_hypothesis(), ReviewType.FULL
    )
    assert isinstance(run, ReviewRun)
    assert tuple(run) == (ReviewType.FULL, run.result, ledger)
    assert run.result is not None and "research_ledger" not in run.result
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(side_effect=RuntimeError("bad"))
    )
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
    calls = AsyncMock(return_value={"verdict": "holds"})
    monkeypatch.setattr(leaf, "call_llm_json", calls)
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
