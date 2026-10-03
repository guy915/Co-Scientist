"""Offline contracts for checkpoint."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

import co_scientist.checkpoint as checkpoint_module
from co_scientist.checkpoint import (
    CHECKPOINT_VERSION,
    CheckpointSchemaError,
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.models import (
    ExecutionMetrics,
    Hypothesis,
    HypothesisOrigin,
    HypothesisReview,
)
from co_scientist.patch import (
    Patch,
    PatchError,
    UpdateFile,
    apply_patch,
    parse_patch,
    seek_anchor,
)
from co_scientist.state import AppendHypotheses, deduplicate_hypotheses
from tests._state import make_hypothesis


def _rich_hypotheses() -> list[Hypothesis]:
    """A parent and its evolved child carrying reviews and match tallies."""
    parent = Hypothesis(text="parent hypothesis", elo_rating=1240)
    child = Hypothesis(
        text="child hypothesis",
        parent_id=parent.id,
        generation=1,
        origin=HypothesisOrigin.EVOLUTION,
        reviews=[
            HypothesisReview(
                review_summary="ok",
                scores={"novelty": 4},
                safety_ethical_concerns="none",
                detailed_feedback={"a": "b"},
                constructive_feedback="tighten",
                overall_score=4.0,
            )
        ],
        win_count=2,
        loss_count=1,
    )
    return [parent, child]


def _rich_state() -> dict[str, object]:
    """A workflow state carrying every non-trivial checkpoint field."""
    return {
        "research_goal": "Explain X",
        "model_name": "fake/model",
        "supervisor_model_name": "fake/model",
        "max_iterations": 3,
        "hypotheses": _rich_hypotheses(),
        "current_iteration": 2,
        "task_history": [{"task_type": "evolve", "reason": "leaders"}],
        "next_task": "generate",
        "termination_reason": None,
        "budget": {"max_iterations": 3, "max_llm_calls": 100},
        "orchestrator_state": {"prev_top_elo": 1240, "rank_stable_cycles": 1},
        "meta_review": {"summary": "s"},
        "proximity_graph": {"edges": [], "meta": {"edge_count": 0}},
        "tournament_matchups": [{"winner": "a"}],
        "metrics": ExecutionMetrics(llm_calls=17, reviews_count=4),
        "start_time": 1000.0,
        "run_id": "run-123",
        "messages": [{"role": "assistant", "content": "hi"}],
        # Runtime handles that must NOT be serialized.
        "progress_callback": lambda *a: None,
        "tool_registry": object(),
    }


def test_round_trip_preserves_serializable_state() -> None:
    """Serialize then restore reproduces the pool, lineage, metrics, ledger."""
    state = _rich_state()
    checkpoint = serialize_workflow_state(state, last_event_seq=42)
    restored = restore_workflow_state(checkpoint)

    assert restored["research_goal"] == "Explain X"
    assert restored["current_iteration"] == 2
    assert restored["next_task"] == "generate"
    assert restored["budget"] == {"max_iterations": 3, "max_llm_calls": 100}
    assert restored["task_history"] == state["task_history"]
    assert restored["orchestrator_state"] == state["orchestrator_state"]

    # Hypotheses and their lineage round-trip.
    hyps = restored["hypotheses"]
    assert [h.text for h in hyps] == ["parent hypothesis", "child hypothesis"]
    child = hyps[1]
    assert child.parent_id == hyps[0].id
    assert child.generation == 1
    assert child.origin is HypothesisOrigin.EVOLUTION
    assert child.win_count == 2 and child.loss_count == 1
    assert child.reviews[0].overall_score == 4.0

    # Metrics round-trip.
    assert restored["metrics"].llm_calls == 17
    assert restored["metrics"].reviews_count == 4


def test_runtime_handles_excluded_and_reinjected() -> None:
    """The callback/registry are not serialized but are re-injected."""
    state = _rich_state()
    checkpoint = serialize_workflow_state(state, last_event_seq=1)

    # Not present in the serialized envelope.
    assert "progress_callback" not in checkpoint["state"]
    assert "tool_registry" not in checkpoint["state"]

    sentinel_cb = lambda *a: "cb"  # noqa: E731
    sentinel_registry = object()
    restored = restore_workflow_state(
        checkpoint,
        progress_callback=sentinel_cb,
        tool_registry=sentinel_registry,
    )
    assert restored["progress_callback"] is sentinel_cb
    assert restored["tool_registry"] is sentinel_registry


def test_restore_sets_resume_flag() -> None:
    """A restored state carries resume=True so the graph resumes."""
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    assert restore_workflow_state(checkpoint)["resume"] is True


def _freeze_time(monkeypatch: pytest.MonkeyPatch, now: float) -> None:
    """Pin the checkpoint module's clock to a fixed timestamp."""
    monkeypatch.setattr(
        checkpoint_module, "time", types.SimpleNamespace(time=lambda: now)
    )


def test_restore_rebases_start_time_excluding_idle_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Elapsed time after resume counts active seconds, not the paused gap.

    A run checkpointed after 300 active seconds and resumed much later must
    not immediately trip ``max_wall_clock_s``: the checkpoint stores consumed
    time, and restore rebases ``start_time`` against the resume clock.
    """
    state = _rich_state()
    state["start_time"] = 1000.0
    _freeze_time(monkeypatch, 1300.0)
    checkpoint = serialize_workflow_state(state, last_event_seq=1)

    # The envelope carries consumed active time, not the raw timestamp.
    assert "start_time" not in checkpoint["state"]
    assert checkpoint["state"]["elapsed_active_s"] == pytest.approx(300.0)

    # Resume after a large real-world gap.
    _freeze_time(monkeypatch, 500_000.0)
    restored = restore_workflow_state(checkpoint)
    assert 500_000.0 - restored["start_time"] == pytest.approx(300.0)


def test_restore_legacy_checkpoint_keeps_verbatim_start_time() -> None:
    """A version-1 checkpoint without elapsed_active_s restores unchanged.

    Older checkpoints carried ``start_time`` verbatim; the fallback preserves
    that value so no version bump was needed for the rebasing change.
    """
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    del checkpoint["state"]["elapsed_active_s"]
    checkpoint["state"]["start_time"] = 1234.5

    restored = restore_workflow_state(checkpoint)
    assert restored["start_time"] == 1234.5


def test_checkpoint_records_last_event_seq() -> None:
    """The checkpoint carries the last durable event seq (high-water mark)."""
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=99)
    assert checkpoint["last_event_seq"] == 99


def test_incompatible_version_fails_closed() -> None:
    """Restoring a mismatched-version checkpoint raises, never loads."""
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    checkpoint["version"] = CHECKPOINT_VERSION + 1
    with pytest.raises(CheckpointSchemaError):
        restore_workflow_state(checkpoint)


def test_checkpoint_is_json_serializable() -> None:
    """The envelope must be JSON-serializable for durable SQLite storage."""
    import json

    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    dumped = json.dumps(checkpoint)
    reloaded = json.loads(dumped)
    restored = restore_workflow_state(reloaded)
    assert restored["run_id"] == "run-123"


def test_langchain_messages_round_trip_through_json() -> None:
    """LangChain messages (added by ``add_messages``) survive JSON persistence.

    At runtime the ``messages`` channel holds ``BaseMessage`` objects, which
    are not JSON-serializable; the serializer must convert them so the app
    store can ``json.dumps`` the envelope, and restore them on the way back.
    """
    import json

    from langchain_core.messages import AIMessage, HumanMessage

    state = _rich_state()
    state["messages"] = [
        HumanMessage(content="goal"),
        AIMessage(content="hypothesis drafted"),
    ]

    checkpoint = serialize_workflow_state(state, last_event_seq=1)
    # The envelope is genuinely JSON-serializable (no BaseMessage leaks).
    reloaded = json.loads(json.dumps(checkpoint))
    restored = restore_workflow_state(reloaded)

    messages = restored["messages"]
    assert [type(m).__name__ for m in messages] == [
        "HumanMessage",
        "AIMessage",
    ]
    assert [m.content for m in messages] == ["goal", "hypothesis drafted"]


def _envelope(*body: str) -> str:
    """Wraps operation lines in the patch envelope."""
    return "\n".join(["*** Begin Patch", *body, "*** End Patch"])


def _apply(text: str, root: Path) -> Patch:
    """Parses and applies a patch, returning the parsed form."""
    patch = parse_patch(text)
    apply_patch(patch, root)
    return patch


# --- parsing --------------------------------------------------------------


def test_envelope_markers_are_required() -> None:
    with pytest.raises(PatchError, match="must start with"):
        parse_patch("*** Update File: a.py\n+x\n*** End Patch")
    with pytest.raises(PatchError, match="must end with"):
        parse_patch("*** Begin Patch\n*** Update File: a.py\n")


def test_an_empty_patch_is_rejected() -> None:
    with pytest.raises(PatchError, match="no file operations"):
        parse_patch(_envelope())


def test_an_unrecognized_hunk_line_is_rejected() -> None:
    with pytest.raises(PatchError, match="unrecognized line"):
        parse_patch(_envelope("*** Update File: a.py", "@@", "?bad marker"))


def test_a_blank_line_in_a_hunk_reads_as_blank_context() -> None:
    """A blank context line is ' ', which gets whitespace-stripped en route."""
    patch = parse_patch(
        _envelope("*** Update File: a.py", "@@", " keep", "", "-drop")
    )
    update = patch.operations[0]
    assert isinstance(update, UpdateFile)
    assert update.hunks[0].anchor == ("keep", "", "drop")


def test_multiple_files_parse_into_one_envelope() -> None:
    patch = parse_patch(
        _envelope(
            "*** Add File: new.py",
            "+print(1)",
            "*** Delete File: gone.py",
            "*** Update File: kept.py",
            "@@",
            " context",
            "-old",
            "+new",
        )
    )
    assert patch.paths == ("new.py", "gone.py", "kept.py")


# --- seeking --------------------------------------------------------------


def test_repeated_blocks_resolve_in_order_not_by_best_match() -> None:
    """The monotonic cursor.

    A scoring matcher would return the same "best" occurrence twice.
    """
    lines = ["x", "dup", "y", "dup", "z"]
    first = seek_anchor(lines, ("dup",), 0)
    assert first is not None and first.start == 1
    second = seek_anchor(lines, ("dup",), first.end)
    assert second is not None and second.start == 3


def test_the_ladder_prefers_an_exact_match_anywhere() -> None:
    """Rung-major search: an exact match later beats a fuzzy one earlier."""
    lines = ["value ", "value"]
    found = seek_anchor(lines, ("value",), 0)
    assert found is not None
    assert found.start == 1
    assert found.rung == "exact"


def test_trailing_whitespace_differences_still_match() -> None:
    found = seek_anchor(["  code  "], ("  code",), 0)
    assert found is not None
    assert found.rung == "trailing-whitespace"


def test_smart_quotes_still_match() -> None:
    """A quote that changed shape in transit must not fail an edit."""
    found = seek_anchor(['x = "a"'], ("x = “a”",), 0)
    assert found is not None
    assert found.rung == "unicode-punctuation"


def test_a_missing_anchor_returns_nothing() -> None:
    assert seek_anchor(["a", "b"], ("absent",), 0) is None


# --- applying -------------------------------------------------------------


def test_update_replaces_the_anchored_lines(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("before\nold\nafter\n")

    _apply(
        _envelope(
            "*** Update File: a.py",
            "@@",
            " before",
            "-old",
            "+new",
            " after",
        ),
        tmp_path,
    )

    assert target.read_text() == "before\nnew\nafter\n"


def test_add_creates_a_file(tmp_path: Path) -> None:
    _apply(
        _envelope("*** Add File: sub/new.py", "+print(1)"),
        tmp_path,
    )
    assert (tmp_path / "sub" / "new.py").read_text() == "print(1)\n"


def test_add_refuses_to_clobber(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("existing\n")
    with pytest.raises(PatchError, match="already exists"):
        _apply(_envelope("*** Add File: a.py", "+new"), tmp_path)
    assert (tmp_path / "a.py").read_text() == "existing\n"


def test_delete_removes_a_file(tmp_path: Path) -> None:
    (tmp_path / "gone.py").write_text("x\n")
    _apply(_envelope("*** Delete File: gone.py"), tmp_path)
    assert not (tmp_path / "gone.py").exists()


def test_move_renames_and_edits(tmp_path: Path) -> None:
    (tmp_path / "old.py").write_text("keep\nold\n")
    _apply(
        _envelope(
            "*** Update File: old.py",
            "*** Move to: new.py",
            "@@",
            " keep",
            "-old",
            "+new",
        ),
        tmp_path,
    )
    assert not (tmp_path / "old.py").exists()
    assert (tmp_path / "new.py").read_text() == "keep\nnew\n"


def test_a_stale_context_fails_rather_than_applying_elsewhere(
    tmp_path: Path,
) -> None:
    """The central property.

    A line-addressed editor would happily write at the numbered line,
    which now holds something else.
    """
    target = tmp_path / "a.py"
    target.write_text("completely\ndifferent\ncontent\n")

    with pytest.raises(PatchError, match="did not match"):
        _apply(
            _envelope(
                "*** Update File: a.py", "@@", " expected", "-old", "+new"
            ),
            tmp_path,
        )
    assert target.read_text() == "completely\ndifferent\ncontent\n"


def test_a_failing_patch_leaves_every_file_untouched(
    tmp_path: Path,
) -> None:
    """All-or-nothing across files.

    The first operation is valid; the second is not. Without the
    plan-then-commit split, the first would already be on disk and the
    tree would be in a state nobody asked for.
    """
    good = tmp_path / "good.py"
    good.write_text("old\n")

    with pytest.raises(PatchError, match="does not exist"):
        _apply(
            _envelope(
                "*** Update File: good.py",
                "@@",
                "-old",
                "+new",
                "*** Update File: missing.py",
                "@@",
                "-a",
                "+b",
            ),
            tmp_path,
        )

    assert good.read_text() == "old\n"


def test_hunks_apply_in_order_within_one_file(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("dup\nmiddle\ndup\n")

    _apply(
        _envelope(
            "*** Update File: a.py",
            "@@",
            "-dup",
            "+first",
            "@@",
            "-dup",
            "+second",
        ),
        tmp_path,
    )

    assert target.read_text() == "first\nmiddle\nsecond\n"


# --- containment ----------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["../escape.py", "sub/../../escape.py", "/etc/passwd"]
)
def test_paths_outside_the_root_are_refused(tmp_path: Path, path: str) -> None:
    with pytest.raises(PatchError, match=r"relative|outside"):
        _apply(_envelope(f"*** Add File: {path}", "+x"), tmp_path)


def test_a_symlinked_escape_is_refused(tmp_path: Path) -> None:
    """Containment is checked after resolution, so a link cannot step out."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)

    with pytest.raises(PatchError, match="outside"):
        _apply(_envelope("*** Add File: link/escape.py", "+x"), root)


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
    from co_scientist.state import accumulate_research_ledgers

    ledger = {"goal": "reverse fibrosis", "calls": []}

    assert accumulate_research_ledgers([ledger], [dict(ledger)]) == [ledger]


def test_a_node_that_researched_nothing_keeps_what_came_before() -> None:
    """Most nodes return no ledger; none of them may clear the list."""
    from co_scientist.state import accumulate_research_ledgers

    existing = [{"goal": "reverse fibrosis"}]

    assert accumulate_research_ledgers(existing, []) == existing
