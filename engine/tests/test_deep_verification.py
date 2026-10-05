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
from tests._llm_fake import mock_call_llm_json
from tests._state import (
    make_article,
    make_hypothesis,
    make_state,
    make_verification_response,
)


async def test_deep_verification_prompt_includes_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """Search uses probe keywords: ANDing a full question can return nothing."""
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
    response: dict[str, object] = {
        **make_verification_response(),
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

    mock_call_llm_json(
        monkeypatch, leaf, side_effect=RuntimeError("verifier unavailable")
    )

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []
    assert h.deep_verification_fingerprint is None


async def test_degraded_verification_records_explicit_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """Mark issuance once per idea; retries belong below this seam, not in
    later work cycles."""

    mock_call_llm_json(
        monkeypatch, leaf, side_effect=RuntimeError("verifier unavailable")
    )
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

    mock_call_llm_json(
        monkeypatch, leaf, side_effect=RuntimeError("verifier unavailable")
    )

    h = make_hypothesis(text="leader", elo_rating=2000)
    h.deep_verification_probes = [{"question": "old"}]
    h.deep_verification_verdict = "holds"
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    h.text = "materially different claim"

    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []


async def test_decomposition_and_decontextualization_are_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """Provider outages must not delete ideas; real failures demote rather
    than exclude them."""
    h = make_hypothesis(text="leader", elo_rating=2000)
    h.review_disposition = "viable"
    h.deep_verification_verdict = dv.VERDICT_UNVERIFIED
    assert h.is_rankable()
    assert not h.is_undermined()

    h.deep_verification_verdict = "undermined"
    assert h.is_rankable()
    assert h.is_undermined()


def test_prompt_covers_decomposition_and_decontextualization() -> None:
    from co_scientist.prompts import get_deep_verification_prompt

    prompt, _ = get_deep_verification_prompt(
        research_goal="goal", hypothesis_text="X causes Y"
    )
    assert "Sub-assumption decomposition" in prompt
    assert "Decontextualization" in prompt


def test_corpus_fallback_selects_sources_matching_the_probe_queries() -> None:
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
    article = make_article("Any paper", abstract="content")
    state = make_state(articles=[article], mcp_available=False)

    articles, errors = await dve._retrieve_probe_evidence(state, [])

    assert articles == []
    assert errors == []


async def test_verification_grounds_probes_in_corpus_when_mcp_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    call = AsyncMock(return_value={"queries": ["term one"]})
    monkeypatch.setattr(ev, "_call_hypothesis_query_llm", call)

    state = make_state(articles=None, mcp_available=False)
    queries = await ev._hypothesis_search_queries(
        state, make_hypothesis(text="h")
    )

    assert queries == []
    assert call.await_count == 0


def _hypothesis() -> Hypothesis:
    return Hypothesis(id="h1", text="Blocking X reverses fibrosis in humans.")


def _article(source_id: str) -> Article:
    return Article(title=f"paper {source_id}", source_id=source_id)


def _state() -> WorkflowState:
    return cast(WorkflowState, {"run_id": "run-1"})


async def _plant(
    state: WorkflowState,
    hypothesis: Hypothesis,
    evidence: _ReviewEvidence,
) -> None:
    loop = asyncio.get_running_loop()
    flights = review_evidence._review_evidence_flights.setdefault(loop, {})
    task = loop.create_task(_resolved(evidence))
    await task
    flights[_evidence_key(state, hypothesis)] = task


async def _resolved(evidence: _ReviewEvidence) -> _ReviewEvidence:
    return evidence


@pytest.mark.asyncio
async def test_verification_reads_research_the_reviews_already_bought() -> None:
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
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state, hypothesis, _ReviewEvidence(["q"], [_article("a")], [], None)
    )

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_an_unresearched_leader_starts_nothing() -> None:
    """Starting retrieval here would add another per-hypothesis wave every
    cycle."""
    state, hypothesis = _state(), _hypothesis()

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_a_failed_gathering_is_not_an_error_here() -> None:
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
    """Duplicate papers spend context twice and falsely resemble independent
    corroboration."""
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state,
        hypothesis,
        _ReviewEvidence(["q"], [_article("a"), _article("c")], [], {"t": 1}),
    )

    merged = with_researched(state, hypothesis, [_article("a")])

    assert [article.source_id for article in merged] == ["a", "c"]


async def test_verifies_every_unverified_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        for i in range(5)
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
    assert fake.await_count == 5


async def test_a_verified_hypothesis_is_never_verified_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe citations change freshness on the verification pass itself;
    issuance must win."""
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

    h = make_hypothesis(text="verified once")
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    assert fake.await_count == 1

    h.citation_map = {"C9": {"source_id": "arrived-later"}}
    await dv.deep_verification_node(state)

    assert fake.await_count == 1
    assert dv.verification_issued(h)


async def test_a_resumed_run_does_not_re_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A memory-only marker would rebuy whole-pool verification after every
    restart."""
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

    h = make_hypothesis(text="verified before the restart")
    await dv.deep_verification_node(make_state(hypotheses=[h]))
    assert fake.await_count == 1

    restored = Hypothesis.from_dict(h.to_dict())
    await dv.deep_verification_node(make_state(hypotheses=[restored]))

    assert fake.await_count == 1


async def test_evolution_children_are_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

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
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

    blocked = make_hypothesis(text="blocked", review_disposition="inaccurate")
    state = make_state(hypotheses=[blocked])
    await dv.deep_verification_node(state)

    assert fake.await_count == 0
    assert not dv.verification_issued(blocked)


async def test_skips_already_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

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
    assert fake.await_count == 0


async def test_reverifies_when_hypothesis_text_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

    h = make_hypothesis(text="original", elo_rating=2000)
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    h.text = "materially different claim"

    await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_reverifies_when_the_verifier_model_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

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
    """Hashing the whole corpus would invalidate every idea when any article
    arrives."""
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

    h = make_hypothesis(text="stable", elo_rating=2000)
    h.citation_map = {"C1": {"source_id": "cited-1", "title": "Cited"}}
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    state["articles"] = [
        make_article("Unrelated paper", abstract="x", used_in_analysis=True)
    ]

    await dv.deep_verification_node(state)

    assert fake.await_count == 0


async def test_reverifies_when_cited_evidence_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

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
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

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
    fake = mock_call_llm_json(monkeypatch, leaf, make_verification_response())

    h = make_hypothesis(text="stable leader", elo_rating=2000)
    state = make_state(hypotheses=[h])

    for _ in range(4):
        await dv.deep_verification_node(state)

    assert fake.await_count == 1


async def test_a_failed_verification_spends_the_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures consume issuance too; lower retry budgets answer transient
    failures."""
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
