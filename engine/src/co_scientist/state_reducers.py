"""Accumulating state reducers.

Two channels on :class:`~co_scientist.state.WorkflowState` must combine a
node's result with what is already there rather than replace it, and both
learned that the hard way -- under last-write-wins a multi-cycle run kept
one cycle of tournament history, and a run whose literature review *and*
whose reviews both researched kept one of their ledgers.

They live here rather than beside the state definition only because that
file is at its length ceiling; ``state`` re-exports them, and the durable
path needs them registered in ``task_runtime._CHANNEL_REDUCERS`` as well
as annotated on the channel.
"""

from __future__ import annotations

from typing import Any


def accumulate_research_ledgers(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """State reducer keeping every ledger a run's researchers produced.

    Research has more than one owner: the literature review researches
    what its reading left open, and each deeply reviewed hypothesis
    researches its own claim. Each returns a whole result rather than a
    fragment of a shared one -- a ledger carries its own goal and stop
    reason, so there is nothing coherent to merge them into -- and under
    last-write-wins the second writer erased the first, taking that
    search's provenance with it.

    Args:
        existing: Ledgers accumulated so far this run.
        new: Ledgers the node just produced.

    Returns:
        The combined list, in the order the ledgers were produced, with
        verbatim repeats dropped so a replayed task cannot double it.

    """
    if not new:
        return existing
    combined = list(existing)
    for ledger in new:
        if ledger not in combined:
            combined.append(ledger)
    return combined


def accumulate_matchups(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """State reducer keeping every tournament's matchups, not just the last.

    The ranking node runs once per cycle and returns only the matchups it
    just judged. Under last-write-wins each tournament erased the record of
    the ones before it, so a multi-cycle run persisted a single cycle's
    matches and the earlier Elo history simply vanished from the matches
    table. The hypotheses' own win/loss tallies carried forward, which is
    why the loss stayed invisible.

    Deduplicated on the matchup's identity -- the two hypotheses and the
    ratings they came in with -- so a replayed or resumed ranking task
    cannot double-count a match it already committed, while a genuine
    rematch in a later cycle (necessarily at different ratings) is kept.

    Args:
        existing: Matchups already accumulated this run.
        new: Matchups the ranking node just judged.

    Returns:
        The combined matchup list in judging order.
    """
    if not new:
        return existing
    combined = list(existing)
    seen = {_matchup_identity(item) for item in existing}
    for item in new:
        identity = _matchup_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        combined.append(item)
    return combined


def _matchup_identity(matchup: dict[str, Any]) -> tuple[Any, ...]:
    """Identity of one judged matchup: the pair plus its pre-match ratings."""
    return (
        matchup.get("hypothesis_a_id"),
        matchup.get("hypothesis_b_id"),
        matchup.get("winner_elo_before"),
        matchup.get("loser_elo_before"),
    )
