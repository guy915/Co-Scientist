"""Parent selection, dominance, and the discovery config it reads.

Split from ``test_discovery_tasks`` because these are the search's
decisions rather than its execution: which variants get bred from, which
count as the real trades, and what a run's config is allowed to say.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.engine_tasks_variants_schedule import (
    pareto_variant_ids,
    select_parents,
)


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def _config_for(**discovery: Any) -> dict[str, Any]:
    """A minimal discovery config for the parsing tests."""
    block: dict[str, Any] = {
        "objective": {"metric": "score", "direction": "maximize"},
        "stages": [{"name": "run", "argv": ["true"]}],
        "seed_source": {"main.py": "pass"},
    }
    block.update(discovery)
    return {"discovery": block}


def _row(variant_id: str, fitness: float | None, **over: Any) -> dict[str, Any]:
    """A stored variant row, as the scheduler reads it."""
    return {
        "id": variant_id,
        "fitness": fitness,
        "ordinal": int(over.get("ordinal", 1)),
        "operator": over.get("operator"),
        "objective_values": over.get("values", [fitness]),
        "source": {"main.py": "x = 1\n" * int(over.get("lines", 5))},
    }


def test_select_parents_always_breeds_from_the_best(db: str) -> None:
    rows = [
        _row("weak", 1.0, operator="simplify", ordinal=1),
        _row("best", 9.0, operator="vectorize", ordinal=2),
        _row("mid", 5.0, operator="explore", ordinal=3),
    ]
    assert "best" in {v["id"] for v in select_parents(rows, 3)}


def test_select_parents_still_breeds_from_failures(db: str) -> None:
    # A generation where everything failed must still have parents, or
    # the run ends at its first bad round with nothing repaired.
    rows = [
        _row("a", None, operator="simplify", ordinal=1),
        _row("b", None, operator="vectorize", ordinal=2),
    ]
    assert select_parents(rows, 2)


def test_select_parents_does_not_hand_a_crowd_every_slot(db: str) -> None:
    # Eight near-identical top scorers and two genuinely different
    # programs. Score-only selection returns four copies of one idea;
    # the archive gives the different ones a share.
    crowd = [
        _row(
            f"tweak{i}",
            9.0 - i * 0.01,
            operator="hyperparameters",
            ordinal=i,
            lines=5,
        )
        for i in range(8)
    ]
    different = [
        _row("tiny", 2.0, operator="simplify", ordinal=20, lines=1),
        _row("huge", 3.0, operator="algorithm_swap", ordinal=21, lines=200),
    ]
    chosen = {v["id"] for v in select_parents(crowd + different, 4)}
    assert len(chosen & {v["id"] for v in crowd}) <= 2


def test_the_pareto_front_keeps_a_second_objective_winner(db: str) -> None:
    # Loses badly on the primary objective, wins the secondary one. A
    # single-axis reading drops it; the front is what keeps it visible.
    rows = [
        _row("accurate", 9.0, ordinal=1, values=[9.0, 1.0]),
        _row("fast", 1.0, ordinal=2, values=[1.0, 9.0]),
        _row("neither", 0.5, ordinal=3, values=[0.5, 0.5]),
    ]
    assert pareto_variant_ids(rows) == {"accurate", "fast"}


def test_the_pareto_front_of_one_objective_is_the_best(db: str) -> None:
    rows = [
        _row("a", 1.0, ordinal=1),
        _row("b", 4.0, ordinal=2),
    ]
    assert pareto_variant_ids(rows) == {"b"}


def test_an_unscored_variant_is_not_on_the_front(db: str) -> None:
    rows = [_row("failed", None, ordinal=1), _row("ok", 1.0, ordinal=2)]
    assert pareto_variant_ids(rows) == {"ok"}


def test_a_malformed_descriptor_is_refused(db: str) -> None:
    # Present-and-wrong is not the same as absent: silently defaulting
    # would niche a run along axes its author did not choose.
    from app.discovery_spec import DiscoverySpecError, descriptors

    with pytest.raises(DiscoverySpecError):
        descriptors({"discovery": {"descriptors": [{"bins": [1]}]}})


def test_absent_descriptors_fall_back_to_the_defaults(db: str) -> None:
    from app.discovery_spec import descriptors

    assert [d.feature for d in descriptors({"discovery": {}})] == [
        "operator",
        "source_lines",
    ]


def test_a_single_objective_config_still_parses(db: str) -> None:
    # The `objective` key predates `objectives` and stays supported.
    from app.discovery_spec import evaluator_spec

    spec = evaluator_spec(_config_for())
    assert len(spec.objectives) == 1
    assert spec.objective.metric == "score"


def test_an_empty_objectives_list_is_refused(db: str) -> None:
    from app.discovery_spec import DiscoverySpecError, evaluator_spec

    config = _config_for(objectives=[])
    with pytest.raises(DiscoverySpecError):
        evaluator_spec(config)
