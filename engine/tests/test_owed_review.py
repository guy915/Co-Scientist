"""Per-hypothesis marker and run-wide cap for the owed-review override.

Mirrors ``review_recheck``'s own bound (a blocked idea's one recheck),
and for the same reason: marked on issue, before the answer is known, so
a failed attempt still spends it, plus a run-wide ceiling on top so a
pool that keeps growing with newly-admitted, never-reviewed ideas cannot
spend the override without limit.
"""

import pytest

from co_scientist.agents.reflection import owed_review
from co_scientist.agents.reflection.owed_review import (
    mark_owed_review_issued,
    owed_review_count,
    owed_review_issued,
    owed_review_targets,
)
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_review


def _unreviewed(index: int = 0) -> Hypothesis:
    return make_hypothesis(text=f"unreviewed idea {index}")


def _reviewed(index: int = 0) -> Hypothesis:
    return make_hypothesis(
        text=f"reviewed idea {index}", reviews=[make_review()]
    )


def test_only_unreviewed_hypotheses_are_owed() -> None:
    unreviewed = _unreviewed(0)
    pool = [unreviewed, _reviewed(1)]

    assert owed_review_targets(pool) == [unreviewed]
    assert owed_review_count(pool) == 1


def test_marking_removes_a_hypothesis_from_the_owed_set() -> None:
    hypothesis = _unreviewed()
    mark_owed_review_issued(hypothesis)

    assert owed_review_issued(hypothesis)
    assert owed_review_targets([hypothesis]) == []
    assert owed_review_count([hypothesis]) == 0


def test_marking_is_permanent_even_if_the_hypothesis_stays_unreviewed() -> None:
    # The whole point: a review that failed must not re-arm the check.
    hypothesis = _unreviewed()
    mark_owed_review_issued(hypothesis)

    assert not hypothesis.reviews  # the forced review never landed
    assert owed_review_count([hypothesis]) == 0


def test_the_marker_survives_a_checkpoint_round_trip() -> None:
    hypothesis = _unreviewed()
    mark_owed_review_issued(hypothesis)

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert owed_review_targets([restored]) == []


def test_an_unreviewed_but_already_archived_duplicate_is_not_owed() -> None:
    # Proximity's archive marker can land on an idea before it is ever
    # peer-reviewed; reviewing an idea already excluded from the report
    # buys nothing.
    hypothesis = _unreviewed()
    hypothesis.review_disposition = "duplicate"

    assert owed_review_targets([hypothesis]) == []


def test_the_run_wide_ceiling_bounds_a_pathological_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(owed_review, "MAX_OWED_REVIEW_OVERRIDES_PER_RUN", 3)
    pool = [_unreviewed(i) for i in range(10)]

    first = owed_review_targets(pool)
    for hypothesis in first:
        mark_owed_review_issued(hypothesis)
    second = owed_review_targets(pool)

    assert len(first) == 3
    assert second == []
