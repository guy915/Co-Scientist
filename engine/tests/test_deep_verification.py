"""Offline contracts for deep verification."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest

import co_scientist.agents.reflection.deep_verification as leaf
from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.agents.reflection import (
    deep_verification_evidence,
    review_evidence,
)
from co_scientist.agents.reflection import deep_verification_evidence as dve
from co_scientist.agents.reflection import review_evidence as ev
from co_scientist.agents.reflection.deep_verification_evidence import (
    with_researched,
)
from co_scientist.agents.reflection.review_evidence import (
    _evidence_key,
    _ReviewEvidence,
    researched_articles_for,
)
from co_scientist.models import Article, Hypothesis
from co_scientist.state import WorkflowState
from tests._state import make_article, make_hypothesis, make_state


def _deep_verification_probe_response_mock() -> AsyncMock:
    """A verifier stub returning one non-fundamental probe and a verdict.

    Non-fundamental so ``_probe_queries`` still yields a search query but
    the run stays on the single-call path with no probe retrieval.
    """
    return AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": False,
                }
            ],
            "verdict": "holds",
            "overall_assessment": "ok",
        }
    )


async def test_deep_verification_prompt_includes_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meta-review feedback reaches deep verification too (audit E28).

    The disclosed all-agent feedback loop appends the meta-review critique to
    every agent's next prompt; deep verification previously omitted it. The
    critique's recurring-error text must now appear in the verifier prompt so
    probing questions can target those patterns.
    """
    prompts: list[str] = []

    async def capture(**kwargs: object) -> dict[str, object]:
        prompts.append(str(kwargs.get("prompt", "")))
        return {"probes": [], "verdict": "confirmed", "overall_assessment": ""}

    monkeypatch.setattr(leaf, "call_llm_json", capture)

    state = make_state(
        hypotheses=[make_hypothesis(text="h", elo_rating=1400)],
        research_goal="goal",
        model_name="test/model",
        run_id="r1",
    )
    state["meta_review"] = {
        "common_weaknesses": ["MARKER_recurring_overclaim"],
    }
    await dv.deep_verification_node(state)

    assert prompts, "expected at least one verification call"
    assert any("MARKER_recurring_overclaim" in p for p in prompts)


def test_verification_context_includes_public_and_private_evidence() -> None:
    """Verification sees only bounded analyzed and private source content."""
    state = make_state(
        articles=[
            make_article(
                "Analyzed paper",
                abstract="Direct mechanistic finding.",
                used_in_analysis=True,
            ),
            make_article(
                "Search-only paper",
                abstract="Must not be treated as analyzed.",
                used_in_analysis=False,
            ),
        ],
        context_enrichment_sources=[
            {"display": "Private scientist result with matched controls."}
        ],
    )

    context = dv._verification_evidence_context(state)

    assert "Analyzed paper" in context
    assert "Direct mechanistic finding" in context
    assert "Search-only paper" not in context
    assert "Private scientist result" in context


def _probe_retrieval_mocks() -> tuple[AsyncMock, AsyncMock]:
    """Build the call_llm_json and _retrieve_probe_evidence probe-run mocks.

    The first adjudication is ``weakened`` with a probe carrying a
    ``search_query``; targeted retrieval then supplies evidence and the second
    adjudication ``holds``.
    """
    first = {
        "probes": [
            {
                "question": "Does intervention X alter pathway Y?",
                "answer": "Unknown.",
                "reasoning": "The initial corpus does not resolve it.",
                "assumption_is_fundamental": True,
                "search_query": "intervention X pathway Y",
            }
        ],
        "verdict": "weakened",
        "overall_assessment": "Evidence is missing.",
    }
    final = {
        "probes": first["probes"],
        "verdict": "holds",
        "overall_assessment": "Targeted evidence supports the assumption.",
    }
    call = AsyncMock(side_effect=[first, final])
    retrieve = AsyncMock(
        return_value=(
            [
                Article(
                    title="Direct pathway test",
                    source_id="PMID-1",
                    abstract="Intervention X altered pathway Y.",
                    used_in_analysis=True,
                )
            ],
            [],
        )
    )
    return call, retrieve


@pytest.mark.asyncio
async def test_probe_questions_trigger_retrieval_and_second_adjudication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep verification searches its probes before the final verdict.

    The search uses each probe's ``search_query``, not its question: the
    literature back end ANDs every term, so the question form would match
    nothing.
    """
    call, retrieve = _probe_retrieval_mocks()
    monkeypatch.setattr(leaf, "call_llm_json", call)
    monkeypatch.setattr(leaf, "_retrieve_probe_evidence", retrieve)
    hypothesis = make_hypothesis(text="X controls Y", elo_rating=1800)
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Test X and Y",
        model_name="test/model",
        run_id="probe-run",
        mcp_available=True,
    )

    output = await dv.deep_verification_node(state)

    retrieve.assert_awaited_once_with(state, ["intervention X pathway Y"])
    assert call.await_count == 2
    assert output["hypotheses"][0].deep_verification_verdict == "holds"
    assert output["articles"][-1].source_id == "PMID-1"
    assert output["metrics"].llm_calls == 2
    second_prompt = call.await_args_list[1].kwargs["prompt"]
    assert "Targeted probe evidence" in second_prompt
    assert "Direct pathway test" in second_prompt


def test_retrieved_articles_are_deduplicated_by_source_identity() -> None:
    """Repeated probe results do not duplicate evidence in shared state."""
    article = Article(title="Paper", source_id="123", source="pubmed")
    payload = article.to_dict()

    merged = dv.merge_retrieved_articles(
        [article],
        [
            {"retrieved_articles": [payload]},
            {"retrieved_articles": [payload]},
        ],
    )

    assert len(merged) == 1


def test_probe_queries_prefer_keywords_and_rank_fundamental_first() -> None:
    """Searches use each probe's keywords, fundamental assumptions first."""
    queries = deep_verification_evidence._probe_queries(
        {
            "probes": [
                {
                    "question": "Is the assay sensitive enough?",
                    "assumption_is_fundamental": False,
                    "search_query": "CellTiter-Glo assay sensitivity",
                },
                {
                    "question": "Does tamoxifen reduce acrB by >=50%?",
                    "assumption_is_fundamental": True,
                    "search_query": "tamoxifen acrB expression Klebsiella",
                },
            ]
        }
    )

    assert queries == [
        "tamoxifen acrB expression Klebsiella",
        "CellTiter-Glo assay sensitivity",
    ]


def test_probe_queries_fall_back_to_the_question() -> None:
    """A probe with no keywords still searches rather than dropping out.

    Worse than keywords, but a search_query is only ever absent if the model
    omitted an optional-in-practice field, and losing the probe entirely would
    be a bigger regression than an over-long query.
    """
    queries = deep_verification_evidence._probe_queries(
        {
            "probes": [
                {
                    "question": "Does X alter Y?",
                    "assumption_is_fundamental": True,
                }
            ]
        }
    )

    assert queries == ["Does X alter Y?"]


def _verification_response(**overrides: object) -> dict[str, object]:
    """A complete verifier response with the E4 decomposition fields."""
    response: dict[str, object] = {
        "probes": [
            {
                "question": "q",
                "answer": "a",
                "reasoning": "r",
                "assumption_is_fundamental": False,
            }
        ],
        "sub_assumptions": [
            {
                "assumption": "the target is druggable",
                "verification": "two sources show binding",
                "status": "supported",
            }
        ],
        "decontextualizations": [
            {
                "context_bound_claim": "works in HEK293 cells",
                "general_claim": "works in mammalian cells",
                "assessment": "the general claim weakens",
            }
        ],
        "verdict": "holds",
        "overall_assessment": "ok",
    }
    response.update(overrides)
    return response


async def test_failed_verification_records_explicit_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure fails closed: explicit verdict, no silent pass."""

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(leaf, "call_llm_json", _boom)

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []
    # Stale fingerprint: the next pass re-attempts instead of trusting it.
    assert h.deep_verification_fingerprint is None


async def test_degraded_verification_records_explicit_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output that never survived validation is not a pass either.

    The degradation fallback for the node answers ``{}``; applying it as a
    verdict-less verification would leave the idea implicitly passed.
    """
    monkeypatch.setattr(leaf, "call_llm_json", AsyncMock(return_value={}))

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []
    assert h.deep_verification_fingerprint is None


async def test_the_failure_state_is_the_idea_s_final_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A spent attempt is not re-offered by a later cycle.

    Verification became blanket over the pool when it moved ahead of the
    tournament, and it is affordable only once per idea. So the marker is
    written when the attempt is *issued*: re-offering on failure would
    re-fund exactly the population the verifier keeps failing on, every
    cycle. The transient case is answered below this seam instead --
    ``call_llm_json``'s own retry ladder, and on the durable path the item
    task's attempt budget -- so what reaches here is a spent attempt.
    """

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(leaf, "call_llm_json", _boom)
    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED

    later = AsyncMock(return_value=_verification_response())
    monkeypatch.setattr(leaf, "call_llm_json", later)
    await dv.deep_verification_node(state)

    assert later.await_count == 0
    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED


async def test_stale_verification_is_cleared_by_a_failed_reverification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale verdict is not carried through a failed re-verification."""

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(leaf, "call_llm_json", _boom)

    h = make_hypothesis(text="leader", elo_rating=2000)
    h.deep_verification_probes = [{"question": "old"}]
    h.deep_verification_verdict = "holds"
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    h.text = "materially different claim"  # invalidates the fingerprint

    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []


async def test_decomposition_and_decontextualization_are_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The E4 behaviors are captured on the hypothesis, bounded."""
    monkeypatch.setattr(
        leaf, "call_llm_json", AsyncMock(return_value=_verification_response())
    )

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    record = h.enrichments["deep_verification"]
    assert record["sub_assumptions"][0]["status"] == "supported"
    assert record["decontextualizations"][0]["general_claim"] == (
        "works in mammalian cells"
    )
    assert h.deep_verification_verdict == "holds"


async def test_decomposition_lists_are_bounded_on_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over-long decomposition output cannot grow the checkpoint."""
    from co_scientist.schemas.review import (
        DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS,
        DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS,
    )

    monkeypatch.setattr(
        leaf,
        "call_llm_json",
        AsyncMock(
            return_value=_verification_response(
                sub_assumptions=[
                    {
                        "assumption": f"a{i}",
                        "verification": "v",
                        "status": "uncertain",
                    }
                    for i in range(12)
                ],
                decontextualizations=[
                    {
                        "context_bound_claim": f"c{i}",
                        "general_claim": "g",
                        "assessment": "x",
                    }
                    for i in range(9)
                ],
            )
        ),
    )

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    record = h.enrichments["deep_verification"]
    assert len(record["sub_assumptions"]) == (
        DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS
    )
    assert len(record["decontextualizations"]) == (
        DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS
    )


def test_no_verification_verdict_bars_the_tournament() -> None:
    """Every verdict ranks; the worst of them is demoted, not withheld.

    "Unverified" is the fail-closed record for a verification that could
    not be produced, so barring it would let a provider outage delete
    ideas. "Undermined" is a real finding and used to bar the tournament,
    which made deep verification a second terminal gate behind the
    evidence gate; it now reports itself through ``is_undermined``, which
    demotes the idea in the published order instead.
    """
    h = make_hypothesis(text="leader", elo_rating=2000)
    h.review_disposition = "viable"
    h.deep_verification_verdict = dv.VERDICT_UNVERIFIED
    assert h.is_rankable()
    assert not h.is_undermined()

    h.deep_verification_verdict = "undermined"
    assert h.is_rankable()
    assert h.is_undermined()


def test_prompt_covers_decomposition_and_decontextualization() -> None:
    """The verifier is actually asked for the two E4 behaviors."""
    from co_scientist.prompts import get_deep_verification_prompt

    prompt, _ = get_deep_verification_prompt(
        research_goal="goal", hypothesis_text="X causes Y"
    )
    assert "Sub-assumption decomposition" in prompt
    assert "Decontextualization" in prompt


def test_corpus_fallback_selects_sources_matching_the_probe_queries() -> None:
    """Coverage over the query's terms picks the relevant corpus sources."""
    matching = make_article(
        "Tamoxifen efflux pump study",
        abstract="tamoxifen acrB expression Klebsiella pneumoniae",
        used_in_analysis=True,
    )
    unrelated = make_article(
        "Unrelated ecology survey",
        abstract="soil microbiome diversity survey",
        used_in_analysis=True,
    )
    state = make_state(articles=[unrelated, matching], mcp_available=False)

    articles, errors = dve._corpus_probe_evidence(
        state, ["tamoxifen acrB expression Klebsiella"]
    )

    assert [article.title for article in articles] == [
        "Tamoxifen efflux pump study"
    ]
    assert errors == [dve.CORPUS_FALLBACK_NOTE]


def test_corpus_fallback_retracted_sources_are_excluded() -> None:
    """A retracted source is not grounding even when its terms match."""
    retracted = make_article(
        "Retracted tamoxifen study",
        abstract="tamoxifen acrB expression Klebsiella",
        is_retracted=True,
    )
    state = make_state(articles=[retracted], mcp_available=False)

    articles, _ = dve._corpus_probe_evidence(
        state, ["tamoxifen acrB expression Klebsiella"]
    )

    assert articles == []


async def test_probe_retrieval_falls_back_to_corpus_without_mcp() -> None:
    """The node-level retrieval degrades to the corpus instead of skipping."""
    article = make_article(
        "Sertraline membrane study",
        abstract="sertraline proton motive force bacterial membrane",
        used_in_analysis=True,
    )
    state = make_state(articles=[article], mcp_available=False)

    articles, errors = await dve._retrieve_probe_evidence(
        state, ["sertraline proton motive force"]
    )

    assert articles == [article]
    assert errors == [dve.CORPUS_FALLBACK_NOTE]


async def test_probe_retrieval_with_no_queries_still_returns_nothing() -> None:
    """No queries means nothing to ground, with or without MCP."""
    article = make_article("Any paper", abstract="content")
    state = make_state(articles=[article], mcp_available=False)

    articles, errors = await dve._retrieve_probe_evidence(state, [])

    assert articles == []
    assert errors == []


async def test_verification_grounds_probes_in_corpus_when_mcp_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An MCP-down verification still gets a targeted evidence block.

    The probe's keywords match a corpus source, so the verifier is called
    a second time against it -- the same two-call shape as the live path,
    grounded in what the run already retrieved.
    """
    first = {
        "probes": [
            {
                "question": "Does sertraline dissipate proton motive force?",
                "answer": "Unknown.",
                "reasoning": "The corpus does not resolve it.",
                "assumption_is_fundamental": True,
                "search_query": "sertraline proton motive force",
            }
        ],
        "verdict": "weakened",
        "overall_assessment": "Evidence is missing.",
    }
    final = dict(first, verdict="holds")
    call = AsyncMock(side_effect=[first, final])
    monkeypatch.setattr(leaf, "call_llm_json", call)

    state = make_state(
        hypotheses=[make_hypothesis(text="leader", elo_rating=2000)],
        articles=[
            make_article(
                "Sertraline membrane study",
                abstract="sertraline proton motive force bacterial membrane",
                used_in_analysis=True,
            )
        ],
        research_goal="goal",
        model_name="test/model",
        run_id="r1",
        mcp_available=False,
    )

    output = await dv.deep_verification_node(state)

    assert call.await_count == 2
    second_prompt = call.await_args_list[1].kwargs["prompt"]
    assert "Targeted probe evidence" in second_prompt
    assert "Sertraline membrane study" in second_prompt
    result_errors = output["hypotheses"][0].enrichments["deep_verification"][
        "retrieval_errors"
    ]
    assert dve.CORPUS_FALLBACK_NOTE in result_errors
    assert output["hypotheses"][0].deep_verification_verdict == "holds"


async def test_review_queries_still_formulated_when_corpus_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP down with a corpus still spends a query-generation call."""
    call = AsyncMock(return_value={"queries": ["term one"]})
    monkeypatch.setattr(ev, "_call_hypothesis_query_llm", call)

    state = make_state(
        articles=[make_article("Paper", abstract="x")],
        mcp_available=False,
    )
    queries = await ev._hypothesis_search_queries(
        state, make_hypothesis(text="h")
    )

    assert queries == ["term one"]
    assert call.await_count == 1


async def test_review_queries_skipped_when_nothing_to_ground_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP and no corpus: a query call would only burn the budget."""
    call = AsyncMock(return_value={"queries": ["term one"]})
    monkeypatch.setattr(ev, "_call_hypothesis_query_llm", call)

    state = make_state(articles=None, mcp_available=False)
    queries = await ev._hypothesis_search_queries(
        state, make_hypothesis(text="h")
    )

    assert queries == []
    assert call.await_count == 0


def _hypothesis() -> Hypothesis:
    """One leader, as deep verification would see it."""
    return Hypothesis(id="h1", text="Blocking X reverses fibrosis in humans.")


def _article(source_id: str) -> Article:
    """One paper, identified the way the merge deduplicates on."""
    return Article(title=f"paper {source_id}", source_id=source_id)


def _state() -> WorkflowState:
    """The state fields the sharing key is built from."""
    return cast(WorkflowState, {"run_id": "run-1"})


async def _plant(
    state: WorkflowState,
    hypothesis: Hypothesis,
    evidence: _ReviewEvidence,
) -> None:
    """Put a completed gathering in the flight cache for this loop."""
    loop = asyncio.get_running_loop()
    flights = review_evidence._review_evidence_flights.setdefault(loop, {})
    task = loop.create_task(_resolved(evidence))
    await task
    flights[_evidence_key(state, hypothesis)] = task


async def _resolved(evidence: _ReviewEvidence) -> _ReviewEvidence:
    """A finished gathering."""
    return evidence


@pytest.mark.asyncio
async def test_verification_reads_research_the_reviews_already_bought() -> None:
    """The assignment: depth where depth was already paid for.

    Deep verification runs after comprehensive reflection on the same
    cohort's loop, over largely the same leaders, so the gathering it
    needs is usually already sitting in the flight cache.
    """
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state,
        hypothesis,
        _ReviewEvidence(["q"], [_article("a"), _article("b")], [], {"t": 1}),
    )

    found = researched_articles_for(state, hypothesis)

    assert [article.source_id for article in found] == ["a", "b"]


@pytest.mark.asyncio
async def test_a_hypothesis_that_bought_no_research_adds_nothing() -> None:
    """A gathering with no ledger did a probe round and no research.

    Its articles are the probe articles this verification is about to
    retrieve for itself, so returning them would double every paper in
    the prompt while claiming depth that was never bought.
    """
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state, hypothesis, _ReviewEvidence(["q"], [_article("a")], [], None)
    )

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_an_unresearched_leader_starts_nothing() -> None:
    """The cost ceiling, and the whole reason this is a read.

    A leader outside the reviews' funded set has no gathering. Starting
    one here would be a third per-hypothesis retrieval, multiplying by
    pool size and by iteration -- the exact shape that turned an express
    run into 299 model calls.
    """
    state, hypothesis = _state(), _hypothesis()

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_a_failed_gathering_is_not_an_error_here() -> None:
    """Verification still has its probes; it does not inherit the failure."""
    state, hypothesis = _state(), _hypothesis()
    loop = asyncio.get_running_loop()

    async def _boom() -> _ReviewEvidence:
        raise RuntimeError("search broke")

    task = loop.create_task(_boom())
    with pytest.raises(RuntimeError):
        await task
    review_evidence._review_evidence_flights.setdefault(loop, {})[
        _evidence_key(state, hypothesis)
    ] = task

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_a_paper_found_twice_is_carried_once() -> None:
    """A probe query and a research question can surface the same paper.

    Repeated in the prompt it spends the evidence budget twice to say one
    thing, and reads to the model as corroboration by two sources.
    """
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state,
        hypothesis,
        _ReviewEvidence(["q"], [_article("a"), _article("c")], [], {"t": 1}),
    )

    merged = with_researched(state, hypothesis, [_article("a")])

    assert [article.source_id for article in merged] == ["a", "c"]


def _deep_verification_selection_probe_response_mock() -> AsyncMock:
    """A verifier stub returning one non-fundamental probe and a verdict.

    Non-fundamental so ``_probe_queries`` still yields a search query but
    the run stays on the single-call path with no probe retrieval.
    """
    return AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": False,
                }
            ],
            "verdict": "holds",
            "overall_assessment": "ok",
        }
    )


async def test_verifies_every_unverified_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole pool is verified, not an Elo-selected slice of it.

    ``03-reflection.md`` runs deep verification inside
    ``ReviewHypothesis(HypothesisID)`` for the hypothesis being reviewed
    and only then creates that hypothesis's ``AddToTournament`` task, so
    the published rule is blanket: every idea, before it can be ranked.
    """
    fake = AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": True,
                }
            ],
            "verdict": "weakened",
            "overall_assessment": "ok",
        }
    )
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    hyps = [
        make_hypothesis(text=f"h{i}", elo_rating=1000 + i * 100)
        for i in range(5)  # elos 1000..1400
    ]
    state = make_state(
        hypotheses=hyps,
        research_goal="goal",
        model_name="test/model",
        run_id="r1",
    )
    out = await dv.deep_verification_node(state)

    verified = [h for h in out["hypotheses"] if h.deep_verification_probes]
    assert {h.text for h in verified} == {"h0", "h1", "h2", "h3", "h4"}
    assert verified[0].deep_verification_verdict == "weakened"
    # Full/simulation reviews run in the comprehensive Reflection node.
    assert fake.await_count == 5


async def test_a_verified_hypothesis_is_never_verified_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The once-ever marker outranks every staleness signal there is.

    Blanket verification is affordable only because it is incremental.
    Probe retrieval adds citations to the hypothesis it verified, so the
    freshness fingerprint alone would go stale on the very pass that
    wrote it and re-verify the whole pool every cycle.
    """
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="verified once")
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    assert fake.await_count == 1

    # Every input the fingerprint covers moves underneath it.
    h.citation_map = {"C9": {"source_id": "arrived-later"}}
    await dv.deep_verification_node(state)

    assert fake.await_count == 1
    assert dv.verification_issued(h)


async def test_a_resumed_run_does_not_re_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker rides in ``enrichments``, so it survives a checkpoint.

    Held only in memory it would turn a bounded, once-per-idea cost into
    a fresh whole-pool wave on every restart.
    """
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="verified before the restart")
    await dv.deep_verification_node(make_state(hypotheses=[h]))
    assert fake.await_count == 1

    restored = Hypothesis.from_dict(h.to_dict())
    await dv.deep_verification_node(make_state(hypotheses=[restored]))

    assert fake.await_count == 1


async def test_evolution_children_are_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child is a new idea, so it gets its own one verification.

    The child is a fresh ``Hypothesis`` with empty ``enrichments``; the
    parent's marker is not inherited, so the incremental rule funds each
    cycle's new ideas without re-funding the ones already verified.
    """
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    parent = make_hypothesis(text="parent")
    state = make_state(hypotheses=[parent])
    await dv.deep_verification_node(state)
    assert fake.await_count == 1

    child = make_hypothesis(text="child", parent_id=parent.id, generation=1)
    state["hypotheses"].append(child)
    await dv.deep_verification_node(state)

    assert fake.await_count == 2
    assert child.deep_verification_verdict == "holds"


async def test_blocked_ideas_are_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification guards tournament entry, so it funds only entrants.

    The published order puts the initial review's discard first ("Full
    review. If a hypothesis passes the initial review..."), and an idea
    the review gate barred never reaches a tournament match for deep
    verification to have protected.
    """
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    blocked = make_hypothesis(text="blocked", review_disposition="inaccurate")
    state = make_state(hypotheses=[blocked])
    await dv.deep_verification_node(state)

    assert fake.await_count == 0
    assert not dv.verification_issued(blocked)


async def test_skips_already_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leader whose verification inputs are unchanged is not re-verified."""
    fake = AsyncMock(
        return_value={
            "probes": [
                {
                    "question": "q",
                    "answer": "a",
                    "reasoning": "r",
                    "assumption_is_fundamental": False,
                }
            ],
            "verdict": "holds",
            "overall_assessment": "ok",
        }
    )
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="already", elo_rating=2000)
    h.deep_verification_probes = [
        {
            "question": "old",
            "answer": "a",
            "reasoning": "r",
            "assumption_is_fundamental": True,
        }
    ]
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    await dv.deep_verification_node(state)
    assert fake.await_count == 0  # inputs unchanged -> reused


async def test_reverifies_when_hypothesis_text_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rewriting a hypothesis invalidates the verification of the old one."""
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="original", elo_rating=2000)
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    # Evolution (or a scientist edit) rewrites the text in place.
    h.text = "materially different claim"

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_reverifies_when_the_verifier_model_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict from another model is not carried over as current."""
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, "some-other-model"
    )
    state = make_state(hypotheses=[h])

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_unrelated_evidence_does_not_invalidate_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence the hypothesis never cites cannot make its verdict stale.

    The evidence context is assembled run-wide, so hashing all of it would
    re-verify the whole leaderboard whenever any article arrived anywhere.
    """
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.citation_map = {"C1": {"source_id": "cited-1", "title": "Cited"}}
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    # A new article lands in the run that this hypothesis does not cite.
    state["articles"] = [
        make_article("Unrelated paper", abstract="x", used_in_analysis=True)
    ]

    await dv.deep_verification_node(state)

    assert fake.await_count == 0


async def test_reverifies_when_cited_evidence_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence the hypothesis now cites is a new input to its verdict."""
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.citation_map = {"C1": {"source_id": "cited-1"}}
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    h.citation_map["C2"] = {"source_id": "cited-2"}

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_a_hypothesis_with_no_stored_verification_is_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idea that has never been verified carries no fingerprint."""
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    verified = make_hypothesis(text="incumbent", elo_rating=2000)
    promoted = make_hypothesis(text="newcomer", elo_rating=1900)
    state = make_state(hypotheses=[verified, promoted])
    verified.deep_verification_fingerprint = dv.verification_fingerprint(
        verified, state["model_name"]
    )

    await dv.deep_verification_node(state)

    assert fake.await_count == 1
    assert promoted.deep_verification_fingerprint is not None


async def test_verification_is_run_once_across_repeated_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The observed four-cycle pattern costs one verification, not four.

    The node runs once per work cycle, ahead of each tournament. An idea
    already verified must not be re-verified by any later cycle.
    """
    fake = _deep_verification_selection_probe_response_mock()
    monkeypatch.setattr(leaf, "call_llm_json", fake)

    h = make_hypothesis(text="stable leader", elo_rating=2000)
    state = make_state(hypotheses=[h])

    for _ in range(4):
        await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_a_failed_verification_spends_the_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure is not recorded as a verification, and is not re-fired.

    The marker is written when the attempt is *issued*, not when it
    succeeds: re-firing on failure is how a bounded once-per-idea wave
    becomes a per-cycle one for exactly the ideas the verifier keeps
    failing on. The accepted cost is that a hard failure leaves the idea
    explicitly ``unverified`` for the rest of the run; the transient case
    is already answered by the retry ladders below this seam.
    """
    calls = 0

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(leaf, "call_llm_json", _boom)

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    await dv.deep_verification_node(state)

    assert calls == 1
    assert h.deep_verification_fingerprint is None
    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
