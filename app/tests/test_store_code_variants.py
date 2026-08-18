"""Code-variant storage: lineage, ordering, and the running-best flag.

The interesting cases here are the ones where a variant *fails*. A
discovery run's sequence is only honest if the attempts that went
nowhere keep their place in it, and the flag the breakthrough plot reads
has to survive variants landing out of order.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app import store


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def _seed(
    run_id: str,
    *,
    parent_id: str | None = None,
    generation: int = 0,
    operator: str | None = None,
) -> str:
    """Adds a variant with a one-file program, returning its id."""
    return store.add_code_variant(
        store.NewCodeVariant(
            run_id=run_id,
            source={"main.py": "x = 1"},
            parent_id=parent_id,
            generation=generation,
            operator=operator,
        )
    )


def _fetch(variant_id: str) -> dict[str, Any]:
    """Reads a variant that the test has just written, so it must exist."""
    variant = store.get_code_variant(variant_id)
    assert variant is not None
    return variant


def _evaluated(run_id: str, fitness: float | None, status: str = "ok") -> str:
    """Adds a variant and immediately records an evaluation for it."""
    variant_id = _seed(run_id)
    store.record_variant_evaluation(
        variant_id, store.VariantEvaluation(status=status, fitness=fitness)
    )
    return variant_id


def test_ordinals_are_dense_and_start_at_one(db: str) -> None:
    run = store.create_run("variants", "standard", "mock", {})
    for _ in range(3):
        _seed(run.id)
    assert [v["ordinal"] for v in store.list_code_variants(run.id)] == [1, 2, 3]


def test_ordinals_are_per_run(db: str) -> None:
    first = store.create_run("a", "standard", "mock", {})
    second = store.create_run("b", "standard", "mock", {})
    _seed(first.id)
    _seed(second.id)
    assert store.list_code_variants(second.id)[0]["ordinal"] == 1


def test_a_failed_variant_still_takes_a_number(db: str) -> None:
    # The whole point of the dense ordinal: skipping dead attempts makes
    # the plot read as faster progress than actually happened.
    run = store.create_run("failures count", "standard", "mock", {})
    _evaluated(run.id, 1.0)
    _evaluated(run.id, None, status="failed")
    third = _evaluated(run.id, 2.0)
    assert _fetch(third)["ordinal"] == 3


def test_a_new_variant_starts_pending(db: str) -> None:
    run = store.create_run("pending", "standard", "mock", {})
    variant = _fetch(_seed(run.id))
    assert variant["status"] == "pending"
    assert variant["fitness"] is None


def test_source_round_trips(db: str) -> None:
    run = store.create_run("source", "standard", "mock", {})
    variant_id = store.add_code_variant(
        store.NewCodeVariant(
            run_id=run.id, source={"a.py": "print(1)", "b.txt": "notes"}
        )
    )
    stored = _fetch(variant_id)["source"]
    assert stored == {"a.py": "print(1)", "b.txt": "notes"}


def test_lineage_and_operator_are_preserved(db: str) -> None:
    run = store.create_run("lineage", "standard", "mock", {})
    parent = _seed(run.id)
    child = _seed(run.id, parent_id=parent, generation=1, operator="vectorize")
    stored = _fetch(child)
    assert stored["parent_id"] == parent
    assert stored["operator"] == "vectorize"
    assert stored["generation"] == 1


def test_metrics_are_stored_raw(db: str) -> None:
    # Uncorrected, so a minimized metric still reads as itself even though
    # fitness carries the opposite sign.
    run = store.create_run("metrics", "standard", "mock", {})
    variant_id = _seed(run.id)
    store.record_variant_evaluation(
        variant_id,
        store.VariantEvaluation(
            status="ok", fitness=-0.8, metrics={"latency_seconds": 0.8}
        ),
    )
    stored = _fetch(variant_id)
    assert stored["metrics"] == {"latency_seconds": 0.8}
    assert stored["fitness"] == -0.8


def test_artifacts_are_stored_for_a_failure(db: str) -> None:
    run = store.create_run("artifacts", "standard", "mock", {})
    variant_id = _seed(run.id)
    store.record_variant_evaluation(
        variant_id,
        store.VariantEvaluation(
            status="failed", artifacts={"stderr": "ZeroDivisionError"}
        ),
    )
    assert _fetch(variant_id)["artifacts"] == {"stderr": "ZeroDivisionError"}


def test_re_evaluation_drops_the_previous_metrics(db: str) -> None:
    # Otherwise a variant reports the union of two runs' metric sets.
    run = store.create_run("re-eval", "standard", "mock", {})
    variant_id = _seed(run.id)
    store.record_variant_evaluation(
        variant_id,
        store.VariantEvaluation(status="ok", metrics={"old": 1.0, "keep": 2.0}),
    )
    store.record_variant_evaluation(
        variant_id, store.VariantEvaluation(status="ok", metrics={"keep": 3.0})
    )
    assert _fetch(variant_id)["metrics"] == {"keep": 3.0}


def test_best_so_far_marks_each_improvement(db: str) -> None:
    run = store.create_run("running best", "standard", "mock", {})
    for fitness in (1.0, 0.5, 2.0, 1.5):
        _evaluated(run.id, fitness)
    flags = [v["is_best_so_far"] for v in store.list_code_variants(run.id)]
    assert flags == [True, False, True, False]


def test_best_so_far_is_recomputed_when_a_variant_lands_late(db: str) -> None:
    # Variants evaluate concurrently, so an earlier attempt can finish
    # after a later one. Deciding the flag once, at evaluation time, would
    # leave the second variant permanently marked best.
    run = store.create_run("out of order", "standard", "mock", {})
    first = _seed(run.id)
    second = _seed(run.id)
    store.record_variant_evaluation(
        second, store.VariantEvaluation(status="ok", fitness=1.0)
    )
    store.record_variant_evaluation(
        first, store.VariantEvaluation(status="ok", fitness=5.0)
    )
    flags = [v["is_best_so_far"] for v in store.list_code_variants(run.id)]
    assert flags == [True, False]


def test_an_unscored_variant_is_never_best(db: str) -> None:
    # None is "no position in the ordering", not a score of zero.
    run = store.create_run("unscored", "standard", "mock", {})
    _evaluated(run.id, None, status="failed")
    _evaluated(run.id, -10.0)
    flags = [v["is_best_so_far"] for v in store.list_code_variants(run.id)]
    assert flags == [False, True]


def test_best_code_variant_prefers_the_earlier_attempt_on_a_tie(
    db: str,
) -> None:
    run = store.create_run("tie", "standard", "mock", {})
    first = _evaluated(run.id, 3.0)
    _evaluated(run.id, 3.0)
    best = store.best_code_variant(run.id)
    assert best is not None and best["id"] == first


def test_best_code_variant_is_none_when_nothing_scored(db: str) -> None:
    run = store.create_run("nothing", "standard", "mock", {})
    _evaluated(run.id, None, status="failed")
    assert store.best_code_variant(run.id) is None


def test_recording_against_an_unknown_variant_is_a_no_op(db: str) -> None:
    # The durable queue can retry a task whose run was deleted underneath
    # it; that must not raise, because only UnsupportedTaskError is a
    # permanent failure and anything else burns a retry.
    store.record_variant_evaluation(
        "no-such-variant", store.VariantEvaluation(status="ok", fitness=1.0)
    )


def test_variants_are_listed_in_attempt_order_not_by_fitness(db: str) -> None:
    run = store.create_run("order", "standard", "mock", {})
    _evaluated(run.id, 1.0)
    _evaluated(run.id, 9.0)
    _evaluated(run.id, 2.0)
    listed = store.list_code_variants(run.id)
    assert [v["fitness"] for v in listed] == [1.0, 9.0, 2.0]


def test_deleting_a_run_removes_its_variants(db: str) -> None:
    run = store.create_run("cascade", "standard", "mock", {})
    variant_id = _evaluated(run.id, 1.0)
    store.delete_run(run.id)
    assert store.get_code_variant(variant_id) is None
