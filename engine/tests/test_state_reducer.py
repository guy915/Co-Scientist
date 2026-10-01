"""Tests for the ``deduplicate_hypotheses`` state reducer (explicit ops).

The reducer combines a node's ``hypotheses`` update with the running pool using
explicit, deterministic operations, replacing the former
text-overlap heuristic:

- a bare ``list[Hypothesis]`` REPLACES the pool (dedup by id);
- an ``AppendHypotheses(items)`` APPENDS, dropping id/exact-text collisions.

These tests pin both operations, the empty-update guard, and the critical M1
invariant that an evolved child (distinct id) is appended without replacing or
resurrecting anything.
"""

from co_scientist.models import Hypothesis
from co_scientist.state import AppendHypotheses, deduplicate_hypotheses
from tests._state import make_hypothesis

# --- Empty-update guard -----------------------------------------------------


def test_empty_bare_list_returns_existing_unchanged() -> None:
    """An empty bare-list update is 'no change', never a wipe."""
    existing = [make_hypothesis("Foo")]
    result = deduplicate_hypotheses(existing, [])
    assert result is existing


def test_both_empty() -> None:
    """Both empty returns the (empty) ``existing`` object."""
    existing: list[Hypothesis] = []
    result = deduplicate_hypotheses(existing, [])
    assert result is existing


def test_empty_append_is_noop() -> None:
    """An empty AppendHypotheses leaves the pool unchanged."""
    existing = [make_hypothesis("Foo")]
    result = deduplicate_hypotheses(existing, AppendHypotheses([]))
    assert [h.text for h in result] == ["Foo"]


# --- REPLACE (bare list) ----------------------------------------------------


def test_bare_list_replaces_pool() -> None:
    """A bare list sets the pool to exactly that list (curating nodes)."""
    existing = [make_hypothesis("A"), make_hypothesis("B")]
    new = [make_hypothesis("A2"), make_hypothesis("B2")]
    result = deduplicate_hypotheses(existing, new)
    assert [h.text for h in result] == ["A2", "B2"]


def test_replace_drops_existing_absent_from_new() -> None:
    """REPLACE discards existing hypotheses not present in ``new``.

    This is how Proximity prunes duplicates: it returns the kept subset and
    the pool becomes exactly that subset.
    """
    a, b = make_hypothesis("A"), make_hypothesis("B")
    result = deduplicate_hypotheses([a, b], [a])
    assert [h.id for h in result] == [a.id]


def test_replace_dedups_by_id_keeping_first() -> None:
    """REPLACE removes later same-id entries, preserving order."""
    a = make_hypothesis("A", score=1.0)
    a_dup = Hypothesis(text="A rescored", id=a.id, score=2.0)
    result = deduplicate_hypotheses([], [a, a_dup])
    assert len(result) == 1
    assert result[0].id == a.id
    assert result[0].score == 1.0  # first occurrence kept


def test_replace_preserves_ranking_order() -> None:
    """REPLACE keeps the incoming order (ranking sets Elo-sorted order)."""
    existing = [make_hypothesis("A"), make_hypothesis("B")]
    reordered = [existing[1], existing[0]]
    result = deduplicate_hypotheses(existing, reordered)
    assert [h.id for h in result] == [existing[1].id, existing[0].id]


# --- APPEND (AppendHypotheses) ----------------------------------------------


def test_append_adds_new_hypotheses() -> None:
    """APPEND extends the pool with genuinely new hypotheses."""
    existing = [make_hypothesis("A"), make_hypothesis("B")]
    new = [make_hypothesis("C"), make_hypothesis("D")]
    result = deduplicate_hypotheses(existing, AppendHypotheses(new))
    assert [h.text for h in result] == ["A", "B", "C", "D"]


def test_append_skips_existing_id() -> None:
    """APPEND drops an item whose id already exists in the pool."""
    a = make_hypothesis("A")
    result = deduplicate_hypotheses([a], AppendHypotheses([a]))
    assert len(result) == 1
    assert result[0] is a


def test_append_skips_exact_text_duplicate() -> None:
    """APPEND drops an item whose exact normalized text already exists."""
    existing = [make_hypothesis("Foo", score=1.0)]
    incoming = [make_hypothesis(" foo ", score=2.0)]  # same normalized text
    result = deduplicate_hypotheses(existing, AppendHypotheses(incoming))
    assert len(result) == 1
    assert result[0].score == 1.0  # existing kept, duplicate dropped


def test_append_dedups_within_batch() -> None:
    """APPEND drops later exact-text duplicates within the same batch."""
    existing: list[Hypothesis] = []
    batch = [
        make_hypothesis("Dup", score=1.0),
        make_hypothesis("DUP", score=2.0),
    ]
    result = deduplicate_hypotheses(existing, AppendHypotheses(batch))
    assert len(result) == 1
    assert result[0].score == 1.0


# --- M1 invariant: evolved child coexists with its parent -------------------


def test_evolved_child_appends_without_replacing_parent() -> None:
    """An evolved child (distinct id + text) is appended; the parent stays.

    This is the core M1 behavior: producing a child must not replace the
    parent or resurrect a pruned hypothesis. The child has a fresh id and a
    refined text, so APPEND adds it alongside the untouched parent.
    """
    parent = make_hypothesis("A hypothesis about kinase X")
    others = [make_hypothesis("B"), make_hypothesis("C")]
    existing = [parent, *others]
    child = Hypothesis(
        text="A refined hypothesis about kinase X and cofactor W",
        parent_id=parent.id,
        generation=1,
    )
    result = deduplicate_hypotheses(existing, AppendHypotheses([child]))
    ids = [h.id for h in result]
    # Parent and all peers survive; child is added.
    assert parent.id in ids
    assert child.id in ids
    assert len(result) == 4
    # Parent object is unchanged (same text).
    surviving_parent = next(h for h in result if h.id == parent.id)
    assert surviving_parent.text == "A hypothesis about kinase X"


def _matchup(
    a_id: str, b_id: str, winner_before: int = 1200, loser_before: int = 1200
) -> dict[str, object]:
    """One judged matchup detail, reduced to the fields identity uses."""
    return {
        "hypothesis_a_id": a_id,
        "hypothesis_b_id": b_id,
        "winner_elo_before": winner_before,
        "loser_elo_before": loser_before,
    }


def test_matchups_from_later_tournaments_do_not_erase_earlier_ones() -> None:
    """Ranking runs once per cycle and returns only what it just judged.

    Under last-write-wins each tournament erased the record of the ones
    before it, so a multi-cycle run persisted a single cycle of Elo history.
    """
    from co_scientist.state import accumulate_matchups

    first = [_matchup("a", "b")]
    second = [_matchup("c", "d")]

    combined = accumulate_matchups(first, second)

    assert combined == [_matchup("a", "b"), _matchup("c", "d")]


def test_replaying_a_committed_tournament_does_not_double_count() -> None:
    """A resumed ranking task must not commit its matches a second time."""
    from co_scientist.state import accumulate_matchups

    judged = [_matchup("a", "b"), _matchup("c", "d")]

    assert accumulate_matchups(judged, list(judged)) == judged


def test_a_genuine_rematch_at_new_ratings_is_kept() -> None:
    """A later cycle re-pairs against updated ratings, which is real work."""
    from co_scientist.state import accumulate_matchups

    first = [_matchup("a", "b", winner_before=1200, loser_before=1200)]
    rematch = [_matchup("a", "b", winner_before=1224, loser_before=1176)]

    assert len(accumulate_matchups(first, rematch)) == 2


def test_an_empty_ranking_update_never_wipes_the_history() -> None:
    """A tournament that judged nothing must not clear what came before."""
    from co_scientist.state import accumulate_matchups

    existing = [_matchup("a", "b")]

    assert accumulate_matchups(existing, []) == existing


def test_a_replayed_task_does_not_double_its_own_ledger() -> None:
    """Ledgers are content, not events: the same one twice is once."""
    from co_scientist.state.reducers import accumulate_research_ledgers

    ledger = {"goal": "reverse fibrosis", "calls": []}

    assert accumulate_research_ledgers([ledger], [dict(ledger)]) == [ledger]


def test_a_node_that_researched_nothing_keeps_what_came_before() -> None:
    """Most nodes return no ledger; none of them may clear the list."""
    from co_scientist.state.reducers import accumulate_research_ledgers

    existing = [{"goal": "reverse fibrosis"}]

    assert accumulate_research_ledgers(existing, []) == existing
