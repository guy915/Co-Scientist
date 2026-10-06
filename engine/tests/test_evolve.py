from __future__ import annotations

import random
from typing import Any

from co_scientist.agents.evolution.evolve_prompt import (
    sample_context_hypotheses,
)
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis

# Disjoint vocabulary avoids unchanged and near-duplicate guards.
_RAPAMYCIN_RESPONSE: dict[str, Any] = {
    "hypothesis": "rapamycin suppresses mtor signaling downstream",
    "explanation": "fresh layman walkthrough",
    "experiment": "knock down the kinase and measure growth",
    "refinement_summary": "pivoted to a kinase mechanism",
}


# Ascending ratings put the strongest ideas last, exposing list-order slicing.


def _children(result: dict[str, Any]) -> list[Hypothesis]:
    return list(result["hypotheses"].items)


def test_sample_context_hypotheses_large_pool_caps_at_max_context() -> None:
    exclude = make_hypothesis(text="the hypothesis being evolved")
    others = [
        make_hypothesis(text=f"other hypothesis {i}", elo_rating=2000 - i)
        for i in range(20)
    ]
    all_hypotheses = [exclude, *others]

    result = sample_context_hypotheses(
        all_hypotheses,
        exclude_hypothesis=exclude,
        max_context=15,
        rng=random.Random(7),
    )

    assert len(result) == 15
    # Fewer others than the top slice leaves nothing to sample at random.
    assert (
        len(
            sample_context_hypotheses(
                [exclude, *others[:4]],
                exclude_hypothesis=exclude,
                max_context=3,
            )
        )
        == 4
    )
    top_five_texts = {h.text for h in others[:5]}
    assert top_five_texts.issubset({h.text for h in result})
    assert all(h.text != exclude.text for h in result)
