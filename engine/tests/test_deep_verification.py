"""Tests for the deep-verification node.

The node runs probing-question deep verification on the top-k hypotheses by
Elo. These tests monkeypatch ``call_llm_json`` on the node module so no LLM or
network calls are made, and assert that only the highest-Elo hypotheses are
verified and that already-verified hypotheses are skipped.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.models import Article
from tests._state import make_article, make_hypothesis, make_state


async def test_verifies_only_top_k_by_elo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the three highest-Elo hypotheses receive probes."""
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
    monkeypatch.setattr(dv, "call_llm_json", fake)

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
    # DEEP_VERIFICATION_TOP_K == 3 -> only the three highest-Elo get probes.
    assert len(verified) == 3
    assert {h.text for h in verified} == {"h4", "h3", "h2"}
    assert verified[0].deep_verification_verdict == "weakened"
    # Full/simulation reviews run in the comprehensive Reflection node.
    assert fake.await_count == 3


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

    monkeypatch.setattr(dv, "call_llm_json", capture)

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


async def test_skips_already_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hypothesis that already has probes is not re-verified."""
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
    monkeypatch.setattr(dv, "call_llm_json", fake)

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
    await dv.deep_verification_node(state)
    assert fake.await_count == 0  # already has probes -> skipped


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


@pytest.mark.asyncio
async def test_probe_questions_trigger_retrieval_and_second_adjudication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep verification searches its probes before the final verdict.

    The search uses each probe's ``search_query``, not its question: the
    literature back end ANDs every term, so the question form would match
    nothing.
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
    monkeypatch.setattr(dv, "call_llm_json", call)
    monkeypatch.setattr(dv, "_retrieve_probe_evidence", retrieve)
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
    queries = dv._probe_queries(
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
    queries = dv._probe_queries(
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
