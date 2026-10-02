"""A Robin outcome child is compared with peers, not its parent's edges."""

from typing import Any

import pytest

from co_scientist.agents.evolution import (
    EvolutionContext,
    evolve,
    evolve_single_hypothesis_from_outcome,
)
from tests._state import make_hypothesis


@pytest.mark.parametrize(
    ("child_text", "accepted"),
    [
        ("novel offspring uses another lexicon", True),
        ("separate offspring uses another lexicon", True),
        ("separate phrases entirely", False),
    ],
)
@pytest.mark.asyncio
async def test_outcome_refinement_compares_child_text_to_peer(
    monkeypatch: pytest.MonkeyPatch,
    child_text: str,
    accepted: bool,
) -> None:
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    peer = make_hypothesis(text="separate phrases entirely")
    graph = {
        "edges": [{"source": parent.id, "target": peer.id, "similarity": 1.0}]
    }

    async def fake_response(*args: Any, **kwargs: Any) -> dict[str, str]:
        assert args[1] == []  # Siblings reach validation, never prompt peers.
        return {"hypothesis": child_text}

    monkeypatch.setattr(evolve, "_evolve_llm_response", fake_response)
    context = EvolutionContext(
        model_name="fake/model",
        meta_review={},
        removed_duplicates=[],
        proximity_graph=graph,
    )
    child, detail = await evolve_single_hypothesis_from_outcome(
        parent, context, "Observed result", [peer]
    )

    assert (child is not None) is accepted
    assert (detail is not None) is accepted
