"""One parent's evolution failure must not discard the whole round.

``evolve_node`` dispatches one LLM call per selected parent under a single
``asyncio.gather``. Without isolation the first call to raise cancels its
siblings and aborts the node, so the round's other refinements -- already
generated and paid for -- are thrown away, and on the durable path the
whole evolution task fails and re-runs every parent.
"""

from typing import Any

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolve import evolve_node
from tests._state import make_hypothesis, make_state

_PARENTS = (
    "alpha membrane channel governs sodium",
    "bravo cytokine triggers inflammation cascade",
    "charlie enzyme catalyzes lipid breakdown",
)

# Disjoint vocabulary per parent so neither the unchanged guard nor the
# near-duplicate guard rejects the child for reasons unrelated to this test.
_EVOLVED = {
    _PARENTS[0]: "hotel peptide blocks vesicle fusion irreversibly",
    _PARENTS[1]: "india cofactor rescues folding intermediates rapidly",
    _PARENTS[2]: "juliet chaperone prevents aggregation of nascent chains",
}

_DOOMED = _PARENTS[1]


def _stub_one_failing_evolution(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch ``call_llm_json`` so exactly one parent's call raises.

    Returns the list every completed call appends its parent's text to, so a
    test can tell an isolated failure from a cancelled sibling.
    """
    attempted: list[str] = []

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        for original, evolved in _EVOLVED.items():
            if f"**Original Hypothesis:**\n{original}" not in prompt:
                continue
            attempted.append(original)
            if original == _DOOMED:
                raise RuntimeError("provider refused this refinement")
            return {
                "hypothesis": evolved,
                "refinement_summary": f"refined: {evolved}",
            }
        raise AssertionError("evolution called for an unselected hypothesis")

    monkeypatch.setattr(evolve, "call_llm_json", fake)
    return attempted


async def test_one_failed_parent_leaves_its_siblings_evolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising refinement costs its own parent, not the whole round."""
    hypotheses = [make_hypothesis(text=text) for text in _PARENTS]
    state = make_state(hypotheses=hypotheses, evolution_max_count=3)
    attempted = _stub_one_failing_evolution(monkeypatch)

    result = await evolve_node(state)

    assert sorted(attempted) == sorted(_PARENTS)
    children = list(result["hypotheses"].items)
    evolved_texts = sorted(child.text for child in children)
    assert evolved_texts == sorted(
        text for original, text in _EVOLVED.items() if original != _DOOMED
    )
    # The failed parent contributes no detail, and no detail is lost.
    assert len(result["evolution_details"]) == 2
