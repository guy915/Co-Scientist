"""Tournament-match and proximity-edge persistence for the drain.

Extracted verbatim from ``app.engine_adapter.drain``: matchup side
resolution by engine hypothesis id, match-row persistence, and weighted
proximity-graph edges. ``drain`` re-exports every name here, so the
original module namespace keeps resolving.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from co_scientist.agents.ranking.ranking_debate_turns import (
    debate_transcript_document,
)

from app import store
from app.elo import INITIAL_ELO

logger = logging.getLogger(__name__)


def _debate_transcript_json(m: dict[str, Any]) -> str | None:
    """Serialize a matchup's debate turns for its match row, or None.

    The judge returns every turn of the simulated debate; this is the
    boundary that used to keep only the closing rationale. Stored in the
    published exemplar's shape (see
    ``ranking_debate_turns.debate_transcript_document``) rather than as
    the loop's own bookkeeping, so the row holds what a reader is shown
    and nothing else. A matchup with no recorded turns stores NULL, which
    is how every match judged before this column reads.
    """
    turns = m.get("debate_transcript") or []
    if not turns:
        return None
    # A matchup dict from before the judge recorded the verdict number
    # still names its winner, and the canonical side "a" is idea 1.
    verdict = str(
        m.get("debate_verdict") or ("2" if m.get("winner") == "b" else "1")
    )
    document = debate_transcript_document(list(turns), verdict)
    return json.dumps(document, ensure_ascii=False)


def _matchup_loser_engine_id(
    m: dict[str, Any], a_engine_id: str | None, winner_engine_id: str | None
) -> str | None:
    """Return the losing side's engine id: whichever side didn't win."""
    b_engine_id = m.get("hypothesis_b_id")
    return b_engine_id if winner_engine_id == a_engine_id else a_engine_id


def _resolve_match_sides(
    m: dict[str, Any],
    store_id_by_engine_id: dict[str, str],
) -> tuple[str, str] | None:
    """Resolve a matchup's winner/loser store ids, or None if unresolved.

    Matchups may legitimately reference hypotheses that are absent from the
    final set (e.g. proximity pruned a duplicate after it competed), so an
    unresolved id is expected rather than an error — logged and skipped by
    the caller.
    """
    a_engine_id = m.get("hypothesis_a_id")
    winner_engine_id = m.get("winner_id")
    loser_engine_id = _matchup_loser_engine_id(m, a_engine_id, winner_engine_id)

    winner_id = store_id_by_engine_id.get(winner_engine_id or "")
    loser_id = store_id_by_engine_id.get(loser_engine_id or "")
    # Inlined (rather than routed through a predicate helper) so mypy's
    # flow-sensitive narrowing sees both ids as non-None below.
    if not winner_id or not loser_id:
        logger.warning(
            "skipping matchup: unresolved hypothesis id "
            "(winner=%s, loser=%s) — likely a hypothesis dropped "
            "during evolution",
            winner_engine_id,
            loser_engine_id,
        )
        return None
    return winner_id, loser_id


def _persist_engine_matches(
    run_id: str,
    matchups: list[dict[str, Any]],
    store_id_by_engine_id: dict[str, str],
    conn: sqlite3.Connection,
) -> None:
    """Persist tournament matches, resolving each side by engine id."""
    for m in matchups:
        sides = _resolve_match_sides(m, store_id_by_engine_id)
        if sides is None:
            continue
        winner_id, loser_id = sides
        store.add_match(
            store.NewMatch(
                run_id=run_id,
                # The cycle the matchup was judged in, stamped on the
                # detail by the engine's ``_build_matchup_detail``. A
                # literal 0 here (what this used to be) reads back as a
                # whole run's Elo history happening in one cycle: the
                # matchups of every cycle are accumulated in state and
                # drained together, so this row is the only record of
                # when a match happened. Absent on checkpoints written
                # before the field existed, which a resume can still
                # drain.
                iteration=int(m.get("iteration", 0)),
                winner_id=winner_id,
                loser_id=loser_id,
                winner_before=int(m.get("winner_elo_before", INITIAL_ELO)),
                winner_after=int(m.get("winner_elo_after", INITIAL_ELO)),
                loser_before=int(m.get("loser_elo_before", INITIAL_ELO)),
                loser_after=int(m.get("loser_elo_after", INITIAL_ELO)),
                rationale=m.get("reasoning", ""),
                tier=m.get("tier") or None,
                debate_turns=int(m.get("debate_turns", 1)),
                debate_transcript=_debate_transcript_json(m),
            ),
            conn=conn,
        )


def _persist_engine_proximity(
    run_id: str,
    graph: dict[str, Any],
    store_id_by_engine_id: dict[str, str],
    conn: sqlite3.Connection,
) -> None:
    """Persist weighted graph edges after resolving engine hypothesis ids."""
    meta = graph.get("meta") or {}
    for edge in graph.get("edges") or []:
        source = store_id_by_engine_id.get(str(edge.get("source") or ""))
        target = store_id_by_engine_id.get(str(edge.get("target") or ""))
        if not source or not target:
            continue
        store.add_proximity_edge(
            store.NewProximityEdge(
                run_id=run_id,
                source_hypothesis_id=source,
                target_hypothesis_id=target,
                similarity=float(edge.get("similarity", 0.0)),
                degree=edge.get("degree"),
                cluster_id=edge.get("cluster_id"),
                method=meta.get("method"),
                version=meta.get("version"),
                model=meta.get("model"),
                updated_at=meta.get("updated_at"),
            ),
            conn=conn,
        )
