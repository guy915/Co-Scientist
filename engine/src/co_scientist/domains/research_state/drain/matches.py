from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from co_scientist.domains.research_state.models.matchup import Matchup
from co_scientist.domains.research_state.repository import records as store
from co_scientist.domains.research_state.repository.records import NewMatch, NewProximityEdge
from co_scientist.platform.telemetry import retrieval_calls as retrieval
from co_scientist.science.ranking.ranking_debate import (
    debate_transcript_document,
)
from co_scientist.science.research import result_from_dict

logger = logging.getLogger(__name__)


def _persist_retrieval_calls(
    run_id: str,
    final_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Content-addressed IDs deduplicate resumed searches and identical
    searches from different researchers.
    """
    ledgers = final_state.get("research_ledgers")
    if not isinstance(ledgers, list):
        return 0
    rows = [
        row
        for ledger in ledgers
        if isinstance(ledger, dict) and ledger
        for row in retrieval.retrieval_call_rows(run_id, result_from_dict(ledger))
    ]
    if not rows:
        return 0
    written = retrieval.add_retrieval_calls(rows, conn=conn)
    logger.info(
        "Recorded %s of %s research searches for run %s",
        written,
        len(rows),
        run_id,
    )
    return written


def _debate_transcript_json(m: Matchup) -> str | None:
    """Missing historical transcripts remain null rather than being
    reconstructed from closing rationale.
    """
    if not m.debate_transcript:
        return None
    document = debate_transcript_document(list(m.debate_transcript), m.verdict)
    return json.dumps(document, ensure_ascii=False)


def _resolve_match_sides(
    m: Matchup,
    store_id_by_engine_id: dict[str, str],
) -> tuple[str, str] | None:
    """Proximity pruning may remove a former tournament participant;
    unresolved match sides are expected and skipped.
    """
    winner_id = store_id_by_engine_id.get(m.winner_id or "")
    loser_id = store_id_by_engine_id.get(m.loser_id or "")
    # Inline checks preserve mypy's flow-sensitive narrowing of both IDs.
    if not winner_id or not loser_id:
        logger.warning(
            "skipping matchup: unresolved hypothesis id "
            "(winner=%s, loser=%s) — likely a hypothesis dropped "
            "during evolution",
            m.winner_id,
            m.loser_id,
        )
        return None
    return winner_id, loser_id


def _persist_engine_matches(
    run_id: str,
    matchups: list[dict[str, Any]],
    store_id_by_engine_id: dict[str, str],
    conn: sqlite3.Connection,
) -> None:
    for raw in matchups:
        m = Matchup.from_dict(raw)
        sides = _resolve_match_sides(m, store_id_by_engine_id)
        if sides is None:
            continue
        winner_id, loser_id = sides
        store.add_match(
            NewMatch(
                run_id=run_id,
                # Match rows retain authoring-cycle provenance; accumulated Elo
                # history must not collapse into cycle zero.
                iteration=int(m.iteration),
                winner_id=winner_id,
                loser_id=loser_id,
                winner_before=int(m.winner_elo_before),
                winner_after=int(m.winner_elo_after),
                loser_before=int(m.loser_elo_before),
                loser_after=int(m.loser_elo_after),
                rationale=m.reasoning or "",
                tier=m.tier or None,
                debate_turns=int(m.debate_turns),
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
    """Each edge keeps its own measurement provenance; legacy checkpoints
    fall back to the graph-level clustering method.
    """
    meta = graph.get("meta") or {}
    for edge in graph.get("edges") or []:
        source = store_id_by_engine_id.get(str(edge.get("source") or ""))
        target = store_id_by_engine_id.get(str(edge.get("target") or ""))
        if not source or not target:
            continue
        store.add_proximity_edge(
            NewProximityEdge(
                run_id=run_id,
                source_hypothesis_id=source,
                target_hypothesis_id=target,
                similarity=float(edge.get("similarity", 0.0)),
                degree=edge.get("degree"),
                cluster_id=edge.get("cluster_id"),
                method=edge.get("method", meta.get("method")),
                version=meta.get("version"),
                model=meta.get("model"),
                updated_at=meta.get("updated_at"),
            ),
            conn=conn,
        )
