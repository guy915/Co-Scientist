"""Regression tests for the ``deduplicate_hypotheses`` state reducer.

These tests lock in the *current* behavior of the LangGraph anti-duplicate
reducer in ``co_scientist.state`` so that upcoming refactors have a safety net.
The reducer has non-obvious branch logic: depending on the text overlap between
the existing and new lists it either treats ``new`` as a wholesale replacement
or merges ``existing + new``, and the two branches keep *different* instances
when texts collide. The tests below pin both branches, the dedup key, and the
edge cases.
"""

from co_scientist.models import Hypothesis
from co_scientist.state import deduplicate_hypotheses


def make_hypothesis(text: str, score: float = 0.0) -> Hypothesis:
    """Builds a minimal ``Hypothesis`` for reducer tests.

    Only ``text`` is required by the dataclass. ``score`` is exposed so a test
    can distinguish two hypotheses that share the same ``text`` and thus prove
    *which* instance the reducer kept on a collision.

    Args:
        text: The hypothesis text (the reducer's dedup key derives from this).
        score: A distinguishing marker identifying the surviving instance.

    Returns:
        A ``Hypothesis`` instance.
    """
    return Hypothesis(text=text, score=score)


# --- Empty-input edge cases -------------------------------------------------


def test_empty_new_returns_existing_unchanged() -> None:
    """Empty ``new`` returns the exact ``existing`` object (no dedup runs)."""
    existing = [make_hypothesis("Foo")]
    result = deduplicate_hypotheses(existing, [])
    assert result is existing


def test_empty_new_does_not_dedup_existing() -> None:
    """With empty ``new``, internal duplicates in ``existing`` are preserved.

    Dedup only runs when ``new`` is non-empty, so a dirty ``existing`` passes
    through untouched. This is surprising but is the current behavior.
    """
    existing = [make_hypothesis("Foo"), make_hypothesis("Foo")]
    result = deduplicate_hypotheses(existing, [])
    assert result is existing
    assert len(result) == 2


def test_both_empty() -> None:
    """Both lists empty returns the (empty) ``existing`` object."""
    existing: list[Hypothesis] = []
    result = deduplicate_hypotheses(existing, [])
    assert result == []
    assert result is existing


def test_existing_empty_new_present_is_addition() -> None:
    """Empty ``existing`` with a fresh ``new`` adds (and dedups within new)."""
    result = deduplicate_hypotheses([], [make_hypothesis("Foo")])
    assert [h.text for h in result] == ["Foo"]


# --- Dedup key: case- and whitespace-insensitive ----------------------------


def test_dedup_key_is_case_and_whitespace_insensitive() -> None:
    """Texts "Foo" and " foo " collapse to a single hypothesis.

    These are disjoint from ``existing`` so the reducer takes the merge branch;
    the within-list dedup then collapses the two equivalent new entries,
    keeping the first occurrence ("Foo").
    """
    existing = [make_hypothesis("Existing")]
    new = [make_hypothesis("Foo"), make_hypothesis(" foo ")]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["Existing", "Foo"]


def test_within_new_duplicates_keep_first_occurrence() -> None:
    """Among duplicate new entries the first occurrence (by order) is kept."""
    existing = [make_hypothesis("Existing")]
    new = [
        make_hypothesis("Dup", score=1.0),
        make_hypothesis("DUP", score=2.0),
        make_hypothesis(" dup ", score=3.0),
    ]
    result = deduplicate_hypotheses(existing, new)
    dup = [h for h in result if h.text.strip().lower() == "dup"]
    assert len(dup) == 1
    assert dup[0].score == 1.0
    assert dup[0].text == "Dup"


# --- Merge (addition) branch: overlap <= 50% of len(new) --------------------


def test_disjoint_new_is_addition() -> None:
    """Fully disjoint ``new`` is appended to ``existing`` (merge branch)."""
    existing = [make_hypothesis("A"), make_hypothesis("B")]
    new = [make_hypothesis("C"), make_hypothesis("D")]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["A", "B", "C", "D"]


def test_merge_collision_keeps_existing_instance() -> None:
    """In the merge branch, a text collision keeps the EXISTING instance.

    ``existing + new`` is iterated first-to-last, so the existing copy wins.
    The marker ``score`` proves it is the existing instance, not the new one.
    """
    existing = [make_hypothesis("Foo", score=1.0)]
    new = [make_hypothesis("Bar", score=9.0), make_hypothesis("Foo", score=2.0)]
    # overlap = {"foo"} -> 1; len(new) * 0.5 = 1.0; 1 > 1.0 is False -> merge.
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["Foo", "Bar"]
    foo = next(h for h in result if h.text == "Foo")
    assert foo.score == 1.0  # existing instance survived


def test_boundary_exactly_fifty_percent_overlap_is_merge() -> None:
    """Exactly 50% overlap takes the MERGE branch (threshold is strict ``>``).

    ``existing=[A]``, ``new=[A, C]``: overlap is 1, ``len(new) * 0.5`` is 1.0,
    and ``1 > 1.0`` is False. So this merges: ``existing + new`` = ``[A, A, C]``
    deduped to ``[A, C]``, with the existing A kept (score marker proves it).
    """
    existing = [make_hypothesis("A", score=1.0)]
    new = [make_hypothesis("A", score=2.0), make_hypothesis("C", score=3.0)]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["A", "C"]
    a = next(h for h in result if h.text == "A")
    assert a.score == 1.0  # merge branch keeps existing A


# --- Replacement branch: overlap > 50% of len(new) --------------------------


def test_full_overlap_is_replacement_keeping_new_instance() -> None:
    """Fully overlapping ``new`` replaces ``existing`` with the NEW instances.

    ``existing=[Foo]``, ``new=[Foo]``: overlap 1 > ``len(new) * 0.5`` = 0.5, so
    the replacement branch runs and ``all_hyps = new``. The new instance wins.
    """
    existing = [make_hypothesis("Foo", score=1.0)]
    new = [make_hypothesis("Foo", score=2.0)]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["Foo"]
    assert result[0].score == 2.0  # new instance survived


def test_just_over_fifty_percent_overlap_is_replacement() -> None:
    """Just-over-50% overlap takes the REPLACEMENT branch.

    ``existing=[A, B]``, ``new=[A, B, C]``: overlap 2 > ``len(new) * 0.5`` =
    1.5, so ``all_hyps = new``. The result is the NEW instances of A and B plus
    the genuinely new C; the original existing A and B are discarded wholesale.
    """
    existing = [
        make_hypothesis("A", score=1.0),
        make_hypothesis("B", score=1.0),
    ]
    new = [
        make_hypothesis("A", score=2.0),
        make_hypothesis("B", score=2.0),
        make_hypothesis("C", score=2.0),
    ]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["A", "B", "C"]
    assert all(h.score == 2.0 for h in result)  # all from new


def test_replacement_dedups_within_new() -> None:
    """Replacement still dedups internal duplicates of ``new`` (first kept).

    ``existing=[A, B]``, ``new=[A, " a ", B]``: the deduped new texts are
    ``{"a", "b"}`` (2) and ``len(new) * 0.5`` is 1.5, so ``2 > 1.5`` triggers
    replacement. Within ``new`` the first "A" (score 2.0) is kept and its
    case/space variant " a " (score 3.0) is dropped.
    """
    existing = [
        make_hypothesis("A", score=1.0),
        make_hypothesis("B", score=1.0),
    ]
    new = [
        make_hypothesis("A", score=2.0),
        make_hypothesis(" a ", score=3.0),
        make_hypothesis("B", score=2.0),
    ]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["A", "B"]
    a = next(h for h in result if h.text == "A")
    assert a.score == 2.0  # new instance, first occurrence within new


def test_replacement_drops_existing_not_in_new() -> None:
    """Replacement discards existing hypotheses absent from ``new``.

    ``existing=[A, B]``, ``new=[A]``: overlap 1 > ``len(new) * 0.5`` = 0.5, so
    replacement runs and ``all_hyps = new = [A]``. B is dropped entirely.
    """
    existing = [
        make_hypothesis("A", score=1.0),
        make_hypothesis("B", score=1.0),
    ]
    new = [make_hypothesis("A", score=2.0)]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["A"]
    assert result[0].score == 2.0
