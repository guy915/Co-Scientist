"""Tests for the full Reflection review cascade."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import review_evidence as ev
from co_scientist.agents.reflection.research_evidence import ReviewResearch
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Article
from tests._state import make_hypothesis, make_state


def _validation_article() -> Article:
    """The single retrieved article a targeted full review evaluates."""
    return Article(
        title="Targeted validation",
        source_id="validation-1",
        abstract="The proposed mechanism survived direct testing.",
        used_in_analysis=True,
    )


async def test_full_and_simulation_run_for_every_viable_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every idea passing initial review receives both mature review modes.

    A blocked idea gets neither: its one call is the recheck, a single
    recurrent review it is owed once for the whole run
    (``review_recheck``), not the two-review cascade.
    """
    fake = AsyncMock(return_value={"verdict": "sound"})
    monkeypatch.setattr(cr, "call_llm_json", fake)
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"
    rejected = make_hypothesis(text="rejected")
    rejected.review_disposition = "non_novel"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=[*viable, rejected], current_iteration=0)
    )

    assert fake.await_count == 5
    assert all("full" in h.enrichments for h in viable)
    assert all("simulation" in h.enrichments for h in viable)
    assert "full" not in rejected.enrichments
    assert "recurrent" in rejected.enrichments
    assert result["metrics"].llm_calls == 5


async def test_later_cycle_runs_recurrent_review_with_tournament_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mature hypotheses are re-reviewed once per later tournament cycle."""
    fake = AsyncMock(return_value={"verdict": "needs_revision"})
    monkeypatch.setattr(cr, "call_llm_json", fake)
    hypothesis = make_hypothesis(text="mature", elo_rating=1337)
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    state = make_state(
        hypotheses=[hypothesis],
        current_iteration=2,
        meta_review={"common_weaknesses": ["missing control"]},
    )

    await cr.comprehensive_reflection_node(state)
    await cr.comprehensive_reflection_node(state)

    assert fake.await_count == 1
    call = fake.await_args
    assert call is not None
    prompt = call.kwargs["prompt"]
    assert "recurrent/tournament review" in prompt
    assert "1337" in prompt
    assert hypothesis.enrichments["recurrent_review_iteration"] == 2


async def test_a_fatal_full_review_changes_the_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fatal finding is no longer write-only (audit E1).

    The cascade reviews ideas the initial gate marked viable; when the
    full review then rejects one, the disposition flips to a blocking
    value and the idea leaves the tournament, exactly as if the initial
    gate had scored it not viable. The sound simulation beside it cannot
    outvote the rejection.
    """

    async def fake_llm(**kwargs: object) -> dict[str, object]:
        prompt = str(kwargs.get("prompt", ""))
        if "simulation review" in prompt:
            return {"verdict": "holds"}
        return {"verdict": "rejected", "justification": "circular mechanism"}

    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(side_effect=fake_llm))
    hypothesis = make_hypothesis(text="idea")
    hypothesis.review_disposition = "viable"

    await cr.comprehensive_reflection_node(
        make_state(hypotheses=[hypothesis], current_iteration=0)
    )

    assert hypothesis.enrichments["full"]["verdict"] == "rejected"
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


async def test_evolved_hypothesis_receives_missing_observation_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-evolution cascade restores the observation-review invariant."""
    hypothesis = make_hypothesis(text="evolved child")
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    observation = AsyncMock(
        return_value={
            "classification": "missing_piece",
            "reasoning": "explains x",
        }
    )
    monkeypatch.setattr(cr, "analyze_single_hypothesis", observation)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(return_value={}))

    await cr.comprehensive_reflection_node(
        make_state(
            hypotheses=[hypothesis],
            current_iteration=0,
            articles_with_reasoning="retrieved observations",
        )
    )

    observation.assert_awaited_once()
    assert (
        hypothesis.enrichments["observation"]["classification"]
        == "missing_piece"
    )
    assert "explains x" in (hypothesis.reflection_notes or "")


async def test_missing_observation_review_appends_confirmed_strengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-evolution observation positives reach the idea too (K8)."""
    hypothesis = make_hypothesis(text="evolved child")
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    observation = AsyncMock(
        return_value={
            "classification": "missing_piece",
            "reasoning": "explains x",
            "positive_observations": ["accounts for the late onset"],
        }
    )
    monkeypatch.setattr(cr, "analyze_single_hypothesis", observation)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(return_value={}))

    await cr.comprehensive_reflection_node(
        make_state(
            hypotheses=[hypothesis],
            current_iteration=0,
            articles_with_reasoning="retrieved observations",
        )
    )

    notes = hypothesis.reflection_notes or ""
    assert "accounts for the late onset" in notes
    assert notes.index("accounts for the late onset") < notes.index(
        "Classification: missing_piece"
    )
    assert hypothesis.enrichments["observation"]["positive_observations"] == [
        "accounts for the late onset"
    ]


@pytest.mark.asyncio
async def test_full_review_executes_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full review searches and evaluates evidence specific to the idea.

    The search runs on keywords formulated from the hypothesis, not on the
    hypothesis text itself: the literature back end ANDs every term, so prose
    would retrieve nothing and leave the review ungrounded.
    """
    # First call formulates the queries, second is the review itself.
    call = AsyncMock(return_value={"verdict": "sound"})
    retrieve = AsyncMock(return_value=([_validation_article()], []))
    monkeypatch.setattr(cr, "call_llm_json", call)
    monkeypatch.setattr(
        ev,
        "call_llm_json",
        AsyncMock(return_value={"queries": ["mechanism X response Y"]}),
    )
    monkeypatch.setattr(ev, "_retrieve_probe_evidence", retrieve)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=True,
    )

    _, result, _ = await cr._run_review(state, hypothesis, ReviewType.FULL)

    retrieve.assert_awaited_once_with(state, ["mechanism X response Y"])
    assert result is not None
    assert result["retrieval_queries"] == ["mechanism X response Y"]
    assert result["retrieved_articles"][0]["source_id"] == "validation-1"
    # The retrieved evidence reaches the review prompt (the last call).
    prompt = call.await_args_list[-1].kwargs["prompt"]
    assert "Targeted validation" in prompt
    assert "survived direct testing" in prompt


@pytest.mark.asyncio
async def test_query_generation_is_skipped_without_a_search_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP means no search, so the review must not pay to write queries."""
    call = AsyncMock(return_value={"verdict": "sound"})
    monkeypatch.setattr(cr, "call_llm_json", call)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=False,
    )

    _, result, _ = await cr._run_review(state, hypothesis, ReviewType.FULL)

    assert result is not None
    assert result["retrieval_queries"] == []
    # The review call only -- no query-generation call was spent.
    assert call.await_count == 1


async def test_full_and_simulation_share_one_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One hypothesis costs one query-generation call and one retrieval.

    Both reviews ask the same question of the same literature: queries come
    from the hypothesis text and the research goal, neither of which varies
    by review mode. Run independently they paid for it twice, on the run's
    critical path.
    """
    query_calls = 0
    retrievals = 0

    async def _queries(
        _state: object, _hypothesis: object
    ) -> dict[str, object]:
        nonlocal query_calls
        query_calls += 1
        # Yield, so a stampeding second caller has the chance to start its
        # own retrieval before this one records a result to share.
        await asyncio.sleep(0)
        return {"queries": ["targeted query"]}

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        nonlocal retrievals
        retrievals += 1
        await asyncio.sleep(0)
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_call_hypothesis_query_llm", _queries)
    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        cr,
        "call_llm_json",
        AsyncMock(return_value={"assessment": "ok", "score": 4}),
    )

    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, _ = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    assert query_calls == 1
    assert retrievals == 1
    # Both reviews persist the shared evidence, so it survives the
    # checkpoint without depending on the in-process cache.
    for mode in (ReviewType.FULL, ReviewType.SIMULATION):
        stored = hypothesis.enrichments[mode.value]["retrieved_articles"]
        assert [item["source_id"] for item in stored] == ["validation-1"]


async def test_rewritten_hypothesis_does_not_reuse_stale_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evolution rewrites a hypothesis; old evidence no longer answers it."""
    hypothesis = make_hypothesis(text="original claim")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    before = ev._evidence_key(state, hypothesis)
    hypothesis.text = "a materially different claim"

    assert ev._evidence_key(state, hypothesis) != before


# =============================================================================
# Research: the second retrieval round the deep tiers buy
# =============================================================================


def _stub_review_research(
    monkeypatch: pytest.MonkeyPatch, *, fails: bool = False
) -> None:
    """Make research return one article and a ledger, or blow up."""

    async def fake_research(_state: object, _hypothesis: object) -> object:
        if fails:
            raise RuntimeError("source unreachable")
        return ReviewResearch(
            articles=[
                Article(
                    title="Researched paper",
                    source_id="researched-1",
                    abstract="Human evidence for the mechanism.",
                    retrieval_call_id="call-1",
                )
            ],
            ledger={"goal": "g", "threads": [], "calls": [], "findings": []},
        )

    monkeypatch.setattr(ev, "research_for_review", fake_research)


async def test_research_adds_to_the_probe_round_rather_than_replacing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A funded review keeps what its first search found and gains more."""

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        ev,
        "_call_hypothesis_query_llm",
        AsyncMock(return_value={"queries": ["targeted query"]}),
    )
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    _stub_review_research(monkeypatch)
    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, ledgers = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    stored = hypothesis.enrichments["full"]["retrieved_articles"]
    assert [item["source_id"] for item in stored] == [
        "validation-1",
        "researched-1",
    ]
    # Both reviews share one retrieval, so the run is billed one ledger.
    assert len(ledgers) == 1


async def test_a_review_whose_research_broke_is_still_a_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grounding in what the first round found beats failing the item."""

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        ev,
        "_call_hypothesis_query_llm",
        AsyncMock(return_value={"queries": ["targeted query"]}),
    )
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    _stub_review_research(monkeypatch, fails=True)
    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, ledgers = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    assert ledgers == []
    stored = hypothesis.enrichments["full"]["retrieved_articles"]
    assert [item["source_id"] for item in stored] == ["validation-1"]


async def test_the_node_carries_every_hypothesis_ledger_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ledgers are the run's, so the node returns them on its update.

    Left inside the reviews they would never reach the drain, and the
    searches a review paid for would be unrecorded.
    """
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    _stub_review_research(monkeypatch)
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=viable, current_iteration=0)
    )

    # One per hypothesis: identical ledgers here, deduplicated by the
    # state's own reducer rather than by the node.
    assert len(result["research_ledgers"]) == 2
