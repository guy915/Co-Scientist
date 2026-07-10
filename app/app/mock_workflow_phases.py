"""Persistence helpers for the mock workflow's numbered phases.

Each helper below persists one numbered phase of ``run_mock_workflow`` (see the
``mock_workflow`` module docstring for the full stage list) and returns just the
data its caller needs to build the phase's emitted event payload. Splitting the
phases out keeps the orchestration in ``mock_workflow`` linear and readable
while each phase's persistence logic stays independently nameable. These helpers
write through ``app.store`` and draw their content from the pure generators in
``mock_workflow_seeds``.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from typing import Any

from app import store
from app.citations import (
    CitationRecord,
    classify_citation,
    empty_citation_summary,
)
from app.elo import INITIAL_ELO, update_pair
from app.mock_workflow_seeds import (
    _build_evolved_child,
    _build_tournament_pairs,
    _cluster_id,
    _deep_verification_seed,
    _evidence_seed,
    _hypothesis_seed,
    _judge_pair,
    _mock_match_tier,
)
from app.report_render import format_deep_verification_critique

logger = logging.getLogger(__name__)

# Debate depth for a tournament matchup, mirroring the engine's allocation:
# top-ranked pairs run a multi-turn scientific debate; lower-ranked pairs run
# a single-turn comparison (SSR §4, §12). Kept local so the mock workflow
# stays engine-independent.
MULTI_TURN_DEBATE_TURNS = 3
SINGLE_TURN_DEBATE_TURNS = 1


def _persist_literature_review(
    run_id: str,
    db_path: str | None,
    rng: random.Random,
    research_goal: str,
    evidence_count: int,
) -> list[dict[str, Any]]:
    """Seed and persist deterministic evidence rows for the literature review.

    Returns:
        The evidence payloads, each carrying its persisted store id.
    """
    evidence_payload: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for i in range(evidence_count):
            ev = _evidence_seed(rng, research_goal, i)
            ev_id = store.add_evidence(
                run_id,
                title=ev["title"],
                source="mock",
                url=ev["url"],
                authors=ev["authors"],
                year=ev["year"],
                abstract=ev["abstract"],
                available=ev["available"],
                conn=conn,
            )
            evidence_payload.append({"id": ev_id, **ev})
    return evidence_payload


def _persist_generation(
    run_id: str,
    db_path: str | None,
    rng: random.Random,
    research_goal: str,
    initial_count: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Seed and persist the initial generation of hypotheses.

    Returns:
        A tuple of (hypothesis ids in generation order, their payloads).
    """
    hyp_ids: list[str] = []
    hyp_payloads: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for i in range(initial_count):
            h = _hypothesis_seed(rng, research_goal, i)
            hid = store.add_hypothesis(
                run_id,
                title=h["title"],
                statement=h["statement"],
                category=h.get("category"),
                mechanism=h["mechanism"],
                expected_effect=h["expected_effect"],
                experimental_context=h["experimental_context"],
                generation=0,
                created_by_agent="generation",
                conn=conn,
            )
            hyp_ids.append(hid)
            hyp_payloads.append(
                {"id": hid, **h, "elo_rating": INITIAL_ELO, "generation": 0}
            )
    return hyp_ids, hyp_payloads


def _persist_reflection(
    run_id: str,
    db_path: str | None,
    rng: random.Random,
    hyp_ids: list[str],
    hyp_payloads: list[dict[str, Any]],
    evidence_count: int,
) -> None:
    """Seed and persist a reflection review for each initial hypothesis."""
    with store.transaction(db_path) as conn:
        for hid, h in zip(hyp_ids, hyp_payloads, strict=True):
            critique = (
                f"Reflection: '{h['title']}' offers a plausible "
                "mechanism but should be checked against "
                f"the {evidence_count} retrieved sources for prior "
                "work; novelty is moderate; testability is high if "
                "the experimental context is constrained."
            )
            store.add_review(
                run_id,
                hid,
                "reflection",
                summary=f"Initial reflection on {h['title']}",
                critique=critique,
                novelty=round(rng.uniform(0.4, 0.8), 2),
                plausibility=round(rng.uniform(0.5, 0.9), 2),
                testability=round(rng.uniform(0.5, 0.95), 2),
                overall=round(rng.uniform(0.55, 0.85), 2),
                conn=conn,
            )


def _persist_proximity(
    db_path: str | None, hyp_ids: list[str]
) -> dict[str, list[str]]:
    """Assign each hypothesis to a fixed mock proximity cluster; persist it."""
    clusters: dict[str, list[str]] = {}
    with store.transaction(db_path) as conn:
        for i, hid in enumerate(hyp_ids):
            cid = _cluster_id(i)
            clusters.setdefault(cid, []).append(hid)
            store.update_hypothesis_state(hid, cluster_id=cid, conn=conn)
    return clusters


def _judge_and_persist_match(
    run_id: str,
    conn: sqlite3.Connection,
    itr: int,
    a: str,
    b: str,
    elo_state: dict[str, int],
    title_by_id: dict[str, str],
    k_factor: int,
    debate_turns: int = 1,
) -> dict[str, Any]:
    """Judge one pair, update Elo state, and persist the resulting match.

    Mutates `elo_state` in place with the post-match ratings. `debate_turns`
    is the matchup's debate depth (1 = single-turn comparison, >1 = multi-turn
    scientific debate), mirroring the engine's median-Elo allocation
    (SSR §4, §12).

    Returns:
        The match record for the ranking round's emitted payload.
    """
    winner, loser, rationale = _judge_pair(run_id, title_by_id, a, b)
    wb = elo_state[winner]
    lb = elo_state[loser]
    tier = _mock_match_tier(wb, lb)
    wa, la = update_pair(wb, lb, k_factor=k_factor)
    elo_state[winner] = wa
    elo_state[loser] = la
    store.update_hypothesis_state(winner, elo_rating=wa, win_delta=1, conn=conn)
    store.update_hypothesis_state(loser, elo_rating=la, loss_delta=1, conn=conn)
    store.add_match(
        run_id,
        iteration=itr,
        winner_id=winner,
        loser_id=loser,
        winner_before=wb,
        winner_after=wa,
        loser_before=lb,
        loser_after=la,
        rationale=rationale,
        tier=tier,
        debate_turns=debate_turns,
        conn=conn,
    )
    return {
        "winner_id": winner,
        "loser_id": loser,
        "winner_elo_before": wb,
        "winner_elo_after": wa,
        "loser_elo_before": lb,
        "loser_elo_after": la,
        "rationale": rationale,
        "tier": tier,
        "debate_turns": debate_turns,
    }


def _run_ranking_round(
    run_id: str,
    db_path: str | None,
    itr: int,
    pairs: list[tuple[str, str]],
    elo_state: dict[str, int],
    title_by_id: dict[str, str],
    k_factor: int,
) -> list[dict[str, Any]]:
    """Judge and persist one round of tournament matches.

    Mutates `elo_state` in place with the post-match ratings.

    Returns:
        The round's match records, in judged order.
    """
    median_elo = _median_elo(elo_state)
    round_matches: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for a, b in pairs:
            turns = _pair_debate_turns(a, b, elo_state, median_elo)
            round_matches.append(
                _judge_and_persist_match(
                    run_id,
                    conn,
                    itr,
                    a,
                    b,
                    elo_state,
                    title_by_id,
                    k_factor,
                    debate_turns=turns,
                )
            )
    return round_matches


def _median_elo(elo_state: dict[str, int]) -> float:
    """Return the median Elo rating across the current pool (0.0 if empty)."""
    ratings = sorted(elo_state.values())
    if not ratings:
        return 0.0
    mid = len(ratings) // 2
    if len(ratings) % 2:
        return float(ratings[mid])
    return (ratings[mid - 1] + ratings[mid]) / 2.0


def _pair_debate_turns(
    a: str, b: str, elo_state: dict[str, int], median_elo: float
) -> int:
    """Debate depth for a mock matchup, mirroring the engine's median split.

    Top-ranked comparisons (at least one side at or above the pool median)
    run a multi-turn scientific debate; all-lower-ranked comparisons run a
    single-turn comparison (SSR §4, §12).
    """
    top_ranked = (
        elo_state.get(a, 0) >= median_elo or elo_state.get(b, 0) >= median_elo
    )
    return MULTI_TURN_DEBATE_TURNS if top_ranked else SINGLE_TURN_DEBATE_TURNS


def _persist_evolved_child(
    run_id: str,
    conn: sqlite3.Connection,
    rng: random.Random,
    research_goal: str,
    parent_id: str,
    parent: dict[str, Any],
    child_index: int,
) -> dict[str, Any]:
    """Build, persist, and return one evolved child hypothesis payload."""
    child_h = _build_evolved_child(rng, research_goal, parent, child_index)
    child_id = store.add_hypothesis(
        run_id,
        title=child_h["title"],
        statement=child_h["statement"],
        category=parent.get("category") or child_h.get("category"),
        mechanism=child_h["mechanism"],
        expected_effect=child_h["expected_effect"],
        experimental_context=child_h["experimental_context"],
        parent_id=parent_id,
        generation=parent["generation"] + 1,
        created_by_agent="evolution",
        conn=conn,
    )
    return {"id": child_id, "parent_id": parent_id, **child_h}


def _run_evolve_round(
    run_id: str,
    db_path: str | None,
    rng: random.Random,
    research_goal: str,
    hyp_ids: list[str],
    elo_state: dict[str, int],
    evolution_max_count: int,
) -> tuple[list[tuple[str, int]], list[dict[str, Any]]]:
    """Evolve the top-k hypotheses (by Elo) into persisted child hypotheses.

    Mutates `hyp_ids` (appending each child's id) and `elo_state` (seeding
    each child at `INITIAL_ELO`) in place.

    Returns:
        A tuple of (top-k `(hypothesis_id, elo)` pairs, the child payloads).
    """
    top_k = sorted(elo_state.items(), key=lambda kv: -kv[1])[
        :evolution_max_count
    ]
    children: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for parent_id, _ in top_k:
            parent = store.get_hypothesis(parent_id, conn=conn)
            if not parent:
                continue
            child = _persist_evolved_child(
                run_id,
                conn,
                rng,
                research_goal,
                parent_id,
                parent,
                len(hyp_ids) + len(children),
            )
            hyp_ids.append(child["id"])
            elo_state[child["id"]] = INITIAL_ELO
            children.append(child)
    return top_k, children


def _persist_meta_review_round(
    run_id: str,
    db_path: str | None,
    itr: int,
    top_k: list[tuple[str, int]],
    hyp_ids: list[str],
) -> str:
    """Persist a per-iteration meta-review critique and return its text."""
    mr_critique = (
        f"Meta-review (iter {itr}): the leading hypotheses "
        "cluster around the same mechanistic frame; recommend "
        "diversifying the experimental context in the next round "
        "and tightening the citation grounding for the top three."
    )
    store.add_review(
        run_id,
        top_k[0][0] if top_k else hyp_ids[0],
        "meta_review",
        summary=f"Meta-review iteration {itr}",
        critique=mr_critique,
        db_path=db_path,
    )
    return mr_critique


def _persist_deep_verification(
    run_id: str,
    db_path: str | None,
    rng: random.Random,
    leaderboard_ids: list[str],
    top_k_count: int,
) -> list[dict[str, Any]]:
    """Probe and persist deep-verification reviews for the top-k by Elo."""
    dv_entries: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for hid in leaderboard_ids[:top_k_count]:
            hyp = store.get_hypothesis(hid, conn=conn)
            if not hyp:
                continue
            dv = _deep_verification_seed(rng, hyp["title"])
            summary, critique = format_deep_verification_critique(
                dv["probes"], dv["verdict"]
            )
            store.add_review(
                run_id,
                hid,
                "deep_verification",
                summary=summary,
                critique=critique,
                conn=conn,
            )
            dv_entries.append(
                {
                    "hypothesis_id": hid,
                    "verdict": dv["verdict"],
                    "probes": dv["probes"],
                }
            )
    return dv_entries


def _persist_citation_audit(
    run_id: str,
    db_path: str | None,
    hyp_ids: list[str],
    evidence_payload: list[dict[str, Any]],
) -> dict[str, int]:
    """Link mock citations for a subset of hypotheses and classify each one."""
    cit_summary = empty_citation_summary()
    with store.transaction(db_path) as conn:
        # Cite at least 3 hypotheses, or half of them if that is more, so
        # small runs still get a non-trivial citation audit.
        for hid in hyp_ids[: max(3, len(hyp_ids) // 2)]:
            # Link first 2 evidence items to each hypothesis as supporting
            # citations
            for ev in evidence_payload[:2]:
                claim = (
                    f"Mechanism mentioned in {ev['title'][:30]} "
                    "supports hypothesis"
                )
                state = classify_citation(
                    CitationRecord(
                        url=ev["url"],
                        abstract=ev["abstract"],
                        claim=claim,
                        available=ev["available"],
                    )
                )
                cit_summary[state] += 1
                store.add_citation(
                    run_id, hid, ev["id"], claim, state, conn=conn
                )
    return cit_summary


def _apply_pending_steering(run_id: str, db_path: str | None, itr: int) -> None:
    """Apply any steering messages queued for this run iteration, if any."""
    pending = store.get_pending_steering(run_id, db_path=db_path)
    if not pending:
        return
    steering_note = "; ".join(m.content for m in pending)
    logger.info(
        "run %s iteration %d: applying steering: %s", run_id, itr, steering_note
    )
    store.mark_steering_applied([m.id for m in pending], db_path=db_path)


def _fetch_top_hypotheses(
    db_path: str | None, leaderboard_ids: list[str], top_n: int
) -> list[dict[str, Any]]:
    """Fetch the top `top_n` leaderboard hypotheses, dropping missing rows."""
    with store.connect(db_path) as conn:
        raw: list[dict[str, Any] | None] = [
            store.get_hypothesis(hid, conn=conn)
            for hid in leaderboard_ids[:top_n]
        ]
    return [h for h in raw if h]


def _seed_tournament_round(
    hyp_ids: list[str],
    hyp_payloads: list[dict[str, Any]],
    rng: random.Random,
    pair_count: int,
) -> tuple[dict[str, int], dict[str, str], list[tuple[str, str]]]:
    """Seed Elo state, the title lookup, and the first round's pairs.

    Mapping each hypothesis id to its seed-deterministic title (rather than
    keying the judge on the row UUIDs) is what keeps the tournament outcome
    -- and thus the leaderboard, deep-verification selection, and research
    overview -- reproducible for a fixed (run_id, goal).
    """
    elo_state = dict.fromkeys(hyp_ids, INITIAL_ELO)
    title_by_id = {p["id"]: p["title"] for p in hyp_payloads}
    pairs = _build_tournament_pairs(rng, hyp_ids, pair_count)
    return elo_state, title_by_id, pairs
