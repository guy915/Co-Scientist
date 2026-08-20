"""Reflection researching one hypothesis's own claim.

The full and simulation reviews used to search once and stop. These
tests pin what the second half costs and who gets it: research is
refused unless the tier funds reviews, only the best-ranked handful of
hypotheses are funded at all, the first questions come from the doubts
this run already recorded about this hypothesis rather than from a fresh
guess, and every paper it brings back names the search that found it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.reflection.research_evidence import (
    _researched_hypothesis_ids,
    _seed_questions,
    research_for_review,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.models import Hypothesis
from co_scientist.research import result_from_dict
from co_scientist.research_adapter.budget import (
    review_budget_for_tier,
    reviewed_hypothesis_limit,
)
from tests._research_tools import (
    FakeResearchClient,
    research_registry,
)
from tests._state import make_hypothesis, make_state

_PAPERS = {
    "doc-a": {
        "title": "Blockade in humans",
        "abstract": "TGF-beta blockade reduced fibrosis in a human cohort.",
        "pdf_url": "u/a",
    },
    "doc-b": {"title": "Merely listed", "abstract": "Unrelated."},
}


class _ScriptedModel:
    """Answers each of the five research prompts by what it was asked."""

    def __init__(self) -> None:
        """Start with nothing asked."""
        self.prompts: list[str] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Answer one prompt, recording it."""
        self.prompts.append(prompt)
        if "perspectives to research" in prompt:
            return {"stances": ["mechanism"]}
        if "questions this perspective needs" in prompt:
            return {"questions": ["is the mechanism shown in humans?"]}
        if "search query" in prompt:
            return {"query": "TGF-beta blockade human"}
        if "retrieved documents" in prompt:
            return {
                "findings": [
                    {
                        "document": 0,
                        "claim": "Blockade reduced fibrosis in humans",
                        "quote": (
                            "TGF-beta blockade reduced fibrosis in a"
                            " human cohort."
                        ),
                    }
                ],
                "follow_ups": [],
            }
        return {"summary": "Human evidence exists but is thin."}


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    """Route the adapter's model calls to a scripted answerer."""
    model = _ScriptedModel()
    monkeypatch.setattr(
        "co_scientist.research_adapter.model.call_llm_json", model
    )
    return model


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeResearchClient:
    """Serve every MCP call in this module from a scripted client."""
    fake = FakeResearchClient(
        {
            "search_alpha": _PAPERS,
            "read_pdf": {
                "content": "TGF-beta blockade reduced fibrosis in a"
                " human cohort."
            },
        }
    )

    async def get_client(**_: Any) -> MCPToolClient:
        return cast(MCPToolClient, fake)

    monkeypatch.setattr("co_scientist.mcp_client.get_mcp_client", get_client)
    return fake


def _state(tmp_path: Path, hypotheses: list[Hypothesis], *, tier: str) -> Any:
    """A run state whose tools are this suite's, at the given tier."""
    return make_state(
        research_goal="reverse fibrosis",
        model_name="offline/test",
        run_id="run-1",
        hypotheses=hypotheses,
        mcp_available=True,
        research_tier=tier,
        tool_registry=research_registry(tmp_path),
    )


def _viable(text: str, *, elo: int) -> Hypothesis:
    """A hypothesis the reviews would reach, at a given standing."""
    hypothesis = make_hypothesis(text=text)
    hypothesis.review_disposition = "viable"
    hypothesis.elo_rating = elo
    return hypothesis


async def test_a_tier_that_funds_no_reviews_researches_none(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    """Per hypothesis, this is a multiplier on the whole run's cost."""
    hypothesis = _viable("mechanism X drives fibrosis", elo=1500)

    found = await research_for_review(
        _state(tmp_path, [hypothesis], tier="standard"), hypothesis
    )

    assert found is None
    assert client.calls == []
    assert scripted.prompts == []


async def test_only_the_best_ranked_hypotheses_are_researched(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    """The cap is half the ceiling; without it the cost is a product."""
    pool = [_viable(f"mechanism {n}", elo=1000 + n) for n in range(6)]
    state = _state(tmp_path, pool, tier="extended")

    funded = _researched_hypothesis_ids(state, "extended")

    assert len(funded) == reviewed_hypothesis_limit("extended")
    assert funded == {h.id for h in pool[-3:]}
    assert await research_for_review(state, pool[0]) is None
    assert client.calls == []


def test_before_any_tournament_the_review_score_decides(
    tmp_path: Path,
) -> None:
    """This node runs before ranking, so cycle one has no Elo to sort by.

    Every rating is the default on the first cycle. Without a second key
    the funded set would be an arbitrary three of the pool -- and the
    first cycle is where every hypothesis gets its one full review.
    """
    pool = []
    for n in range(6):
        hypothesis = _viable(f"mechanism {n}", elo=1200)
        hypothesis.score = 50.0 + n
        pool.append(hypothesis)

    funded = _researched_hypothesis_ids(
        _state(tmp_path, pool, tier="extended"), "extended"
    )

    assert funded == {h.id for h in pool[-3:]}


async def test_a_funded_hypothesis_researches_and_names_its_searches(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    """The article-to-search link is what makes the evidence checkable."""
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)

    found = await research_for_review(
        _state(tmp_path, [hypothesis], tier="extended"), hypothesis
    )

    assert found is not None
    # Only the document a finding was drawn from becomes an article.
    assert [article.source_id for article in found.articles] == ["doc-a"]
    made = result_from_dict(found.ledger).calls
    assert found.articles[0].retrieval_call_id in {call.id for call in made}


async def test_research_asks_about_the_claim_not_only_the_goal(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    """A review researching the run's goal repeats the literature review."""
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)

    await research_for_review(
        _state(tmp_path, [hypothesis], tier="extended"), hypothesis
    )

    assert any(
        "mechanism X drives fibrosis" in prompt for prompt in scripted.prompts
    )


async def test_the_first_questions_are_the_doubts_already_on_record(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    """An unconfirmed assumption is the question the run has earned."""
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)
    hypothesis.enrichments["full"] = {
        "assumptions": [
            {
                "assumption": "the receptor is expressed in humans",
                "support": "uncertain",
            },
            {"assumption": "fibrosis is reversible", "support": "supported"},
        ]
    }

    found = await research_for_review(
        _state(tmp_path, [hypothesis], tier="extended"), hypothesis
    )

    assert found is not None
    asked = [thread["question"]["text"] for thread in found.ledger["threads"]]
    assert "the receptor is expressed in humans" in asked
    # A confirmed assumption is not a question.
    assert "fibrosis is reversible" not in asked
    # Seeded, so no stance planning call was made.
    assert not any("perspectives to research" in p for p in scripted.prompts)


async def test_a_hypothesis_with_no_recorded_doubts_plans_its_own(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    """A first-cycle hypothesis has no prior review to seed from."""
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)

    found = await research_for_review(
        _state(tmp_path, [hypothesis], tier="extended"), hypothesis
    )

    assert found is not None
    assert any("perspectives to research" in p for p in scripted.prompts)


def test_a_simulation_failure_point_is_a_doubt_too() -> None:
    """What the mechanism was said to break on is worth researching."""
    hypothesis = make_hypothesis(text="mechanism X")
    hypothesis.enrichments["simulation"] = {
        "failure_points": ["step 3 needs a cofactor nothing supplies"]
    }

    assert _seed_questions(hypothesis, 4) == [
        "step 3 needs a cofactor nothing supplies"
    ]


def test_seed_questions_stop_at_the_first_level_breadth() -> None:
    """More seeds than the level can fund would be declined anyway."""
    hypothesis = make_hypothesis(text="mechanism X")
    hypothesis.enrichments["full"] = {
        "assumptions": [
            {"assumption": f"doubt {n}", "support": "likely_false"}
            for n in range(5)
        ]
    }

    assert _seed_questions(hypothesis, 2) == ["doubt 0", "doubt 1"]


def test_the_run_can_quote_its_review_research_ceiling() -> None:
    """Both factors are bounded, so the product is quotable up front."""
    for tier, threads in (("extended", 4), ("ultra", 5)):
        budget = review_budget_for_tier(tier, ("alpha",))
        assert budget is not None
        assert budget.max_threads() == threads
    assert review_budget_for_tier("standard", ("alpha",)) is None
    assert review_budget_for_tier("ultra", ()) is None
    assert reviewed_hypothesis_limit("standard") == 0
