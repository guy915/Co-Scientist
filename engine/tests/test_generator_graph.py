"""Tests for the post-node routing decisions in the workflow graph topology.

``co_scientist.generator.graph`` wires up the LangGraph node/edge topology;
the node-set and terminal-node shape are already covered by
``tests/test_generator.py`` via ``HypothesisGenerator._build_graph``. This
file exercises the two conditional-edge routing functions,
``_after_ranking`` and ``_after_proximity``, directly against a
``WorkflowState``, covering every branch.
"""

from co_scientist.generator.graph import _after_proximity, _after_ranking
from tests._state import make_state

# --- _after_ranking -----------------------------------------------------


def test_after_ranking_without_meta_review_iterates_when_under_max() -> None:
    """No meta_review yet and iterations remain -> route to iterate."""
    state = make_state(current_iteration=0, max_iterations=2, meta_review={})
    assert _after_ranking(state) == "iterate"


def test_after_ranking_without_meta_review_ends_when_at_max() -> None:
    """No meta_review yet and no iterations configured -> route to end."""
    state = make_state(current_iteration=0, max_iterations=0, meta_review={})
    assert _after_ranking(state) == "end"


def test_after_ranking_with_meta_review_goes_to_proximity() -> None:
    """A populated meta_review indicates an iteration cycle -> proximity."""
    state = make_state(
        current_iteration=0,
        max_iterations=5,
        meta_review={"summary": "reviewed"},
    )
    assert _after_ranking(state) == "proximity"


# --- _after_proximity -----------------------------------------------------


def test_after_proximity_continues_when_under_max() -> None:
    """Iterations remain after proximity dedup -> route to iterate."""
    state = make_state(current_iteration=1, max_iterations=3)
    assert _after_proximity(state) == "iterate"


def test_after_proximity_ends_when_at_max() -> None:
    """No iterations remain after proximity dedup -> route to end."""
    state = make_state(current_iteration=3, max_iterations=3)
    assert _after_proximity(state) == "end"


def test_after_proximity_ends_when_over_max() -> None:
    """Current iteration past max still routes to end (not just equal)."""
    state = make_state(current_iteration=5, max_iterations=3)
    assert _after_proximity(state) == "end"
