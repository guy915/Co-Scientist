"""Tournament-match persistence in the final-state drain.

Covers ``engine_adapter.drain.matches``: the columns a judged matchup
carries into its ``matches`` row. Id resolution and the unresolved-side
skip live in ``test_engine_drain.py``; this module holds the cycle the
match was judged in, which the drain used to discard.
"""

from __future__ import annotations

from app import store
from tests._drain_helpers import _final_state_with_features, _persist


def test_persist_match_records_the_iteration_it_was_judged_in(
    isolated_db: str,
) -> None:
    """The matchup's own iteration reaches the row, not a hardcoded zero.

    The drain wrote ``iteration=0`` for every match on every run. Production
    extended run bc77950f judged its 23 matches across three iterations and
    stored all of them as iteration 0, so the persisted Elo history could
    not be read back by cycle.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0]["iteration"] = 2
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [2]


def test_persist_match_without_an_iteration_falls_back_to_zero(
    isolated_db: str,
) -> None:
    """A matchup judged before the field existed still persists.

    Checkpoints written by an earlier build carry no ``iteration`` on their
    matchups, and a resumed run drains them alongside newly judged ones.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0].pop("iteration", None)
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [0]
