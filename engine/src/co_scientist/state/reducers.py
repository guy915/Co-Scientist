"""State reducers, plus the hypothesis-pool reducer ops that feed one of them.

Two channels on :class:`~co_scientist.state.WorkflowState` must combine a
node's result with what is already there rather than replace it, and both
learned that the hard way -- under last-write-wins a multi-cycle run kept
one cycle of tournament history, and a run whose literature review *and*
whose reviews both researched kept one of their ledgers.

They live here rather than beside the state definition only because that
file is at its length ceiling; ``state`` re-exports them. The annotation
on the channel is the only registration: the durable path reads it through
``task_runtime.channel_reducers``. ``deduplicate_hypotheses`` and its
``AppendHypotheses``/``ReplaceHypotheses`` op types moved here for the same
reason and are re-exported by ``state`` the same way.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from co_scientist.models import Hypothesis

logger = logging.getLogger(__name__)


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


def _normalized_text(hyp: Hypothesis) -> str:
    """Return a hypothesis's stripped, lowercased text (the exact-dup key)."""
    return hyp.text.strip().lower()


@dataclasses.dataclass(frozen=True)
class AppendHypotheses:
    """Explicit reducer op: append these hypotheses to the pool.

    Producing nodes (Generation, Evolution) return this instead of a bare list
    so the reducer *appends* their output to the existing pool rather than
    replacing it. Items are dropped only when they collide by id or exact
    normalized text with a hypothesis already in the pool (or an earlier item
    in the same batch); this is a deterministic identity check, not the former
    text-overlap heuristic.

    This is what makes an evolved child coexist with its parent: the child has
    a distinct id and (post-refinement) distinct text, so it is appended while
    the parent is left byte-for-byte unchanged (paper invariant SSR §4, §12).
    """

    items: list[Hypothesis]


@dataclasses.dataclass(frozen=True)
class ReplaceHypotheses:
    """Explicit reducer op: replace the pool with exactly these hypotheses.

    Unlike a bare list (where an empty list is treated as "no change"),
    ``ReplaceHypotheses([])`` genuinely sets the pool to empty. The safety
    screen node uses this so a fully-blocked pool is cleared rather than
    silently surviving the empty-list guard.
    """

    items: list[Hypothesis]


# Explicit reducer op payloads a node may return for the "hypotheses" channel.
# A bare ``list[Hypothesis]`` means REPLACE (set the pool to exactly this list).
HypothesisUpdate = list[Hypothesis] | AppendHypotheses | ReplaceHypotheses


def _dedup_by_id(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return hypotheses with later same-id entries dropped (first wins).

    Identity is the stable ``id``. Curating nodes (ranking, proximity, review)
    return an authoritative pool; this only guards against a node accidentally
    listing the same id twice, without the old text-overlap collapsing.

    Args:
        hypotheses: The pool to deduplicate by id.

    Returns:
        The pool with duplicate ids removed, order preserved.
    """
    seen: set[str] = set()
    result: list[Hypothesis] = []
    for hyp in hypotheses:
        if hyp.id not in seen:
            seen.add(hyp.id)
            result.append(hyp)
    return result


def _append_hypotheses(
    existing: list[Hypothesis], incoming: list[Hypothesis]
) -> list[Hypothesis]:
    """Append `incoming` to `existing`, dropping id/exact-text collisions.

    An incoming hypothesis is dropped when its id, or its exact normalized
    text, already appears in the existing pool or earlier in the same batch.
    This preserves the anti-duplicate safety net at the one place genuinely
    new content enters the pool (Generation/Evolution) while leaving the
    dedup of near-duplicates to the Proximity agent.

    Args:
        existing: The current hypothesis pool (left unchanged).
        incoming: Hypotheses a producing node wants to append.

    Returns:
        `existing` followed by the accepted `incoming` items.
    """
    seen_ids = {hyp.id for hyp in existing}
    seen_texts = {_normalized_text(hyp) for hyp in existing}
    result = list(existing)
    for hyp in incoming:
        text_key = _normalized_text(hyp)
        if hyp.id in seen_ids or text_key in seen_texts:
            logger.debug(
                "append: skipped duplicate hypothesis (id/text): %s...",
                hyp.text[:80],
            )
            continue
        seen_ids.add(hyp.id)
        seen_texts.add(text_key)
        result.append(hyp)
    return result


# This is the LangGraph reducer wired to WorkflowState.hypotheses (see
# `Annotated[list[Hypothesis], deduplicate_hypotheses]` on that channel in
# the state package): every node that returns a "hypotheses" key in its state
# update triggers this function, with `existing` the current cumulative pool and
# `new` the value just returned by that node. `new` is either a bare list
# (REPLACE the pool with exactly that list) or an AppendHypotheses op
# (APPEND to the pool).
def deduplicate_hypotheses(
    existing: list[Hypothesis], new: HypothesisUpdate
) -> list[Hypothesis]:
    """State reducer combining a node's hypotheses update with the pool.

    Explicit, deterministic operations replace the former identity/text
    heuristic:

    - ``AppendHypotheses(items)`` — append items, dropping id/exact-text
      collisions. Used by Generation and Evolution so an evolved child cannot
      replace its parent.
    - a bare ``list[Hypothesis]`` — REPLACE: the pool becomes exactly this
      list (deduplicated by id). Used by every curating node (ranking,
      proximity, review, reflection, deep_verification), which already return
      the full or intentionally pruned pool. An empty bare list is treated as
      "no change" so a node that reports nothing cannot wipe the pool.

    Args:
        existing: Existing hypotheses in state.
        new: The node's update — an append op or a replacement list.

    Returns:
        The combined hypothesis pool.
    """
    if isinstance(new, AppendHypotheses):
        return _append_hypotheses(existing, new.items)
    if isinstance(new, ReplaceHypotheses):
        return _dedup_by_id(new.items)
    # Bare list => REPLACE. An empty list means "no update" (never a wipe).
    if not new:
        return existing
    return _dedup_by_id(new)
