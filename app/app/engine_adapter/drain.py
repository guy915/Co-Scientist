"""Final-state drain: persist a real engine run's results into the store.

Writes a streamed engine run's accumulated final state — evidence,
hypotheses (with reviews, deep-verification reviews, and citations), and
tournament matches — into the SQLite store in one transaction, and returns
the provider-specific report inputs the shared finalize path needs.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, NamedTuple

from app import store
from app.citations import empty_citation_summary
from app.claim_grounding import (
    assess_hypothesis_claims,
    build_assessor,
    evidence_passages,
    persist_grounding,
)
from app.claims import EvidencePassage
from app.config import settings
from app.elo import INITIAL_ELO

# Review/citation and match/proximity persistence moved verbatim to sibling
# modules; every moved name is re-exported so this module's namespace (the
# seam tests and callers patch/import against) keeps resolving.
from app.engine_adapter.drain_matches import (
    _matchup_loser_engine_id as _matchup_loser_engine_id,
)
from app.engine_adapter.drain_matches import (
    _persist_engine_matches as _persist_engine_matches,
)
from app.engine_adapter.drain_matches import (
    _persist_engine_proximity as _persist_engine_proximity,
)
from app.engine_adapter.drain_matches import (
    _resolve_match_sides as _resolve_match_sides,
)
from app.engine_adapter.drain_reviews import (
    _citation_map as _citation_map,
)
from app.engine_adapter.drain_reviews import (
    _citation_url as _citation_url,
)
from app.engine_adapter.drain_reviews import (
    _ensure_citation_evidence_id as _ensure_citation_evidence_id,
)
from app.engine_adapter.drain_reviews import (
    _hypothesis_grounding_text as _hypothesis_grounding_text,
)
from app.engine_adapter.drain_reviews import (
    _persist_deep_verification_review as _persist_deep_verification_review,
)
from app.engine_adapter.drain_reviews import (
    _persist_engine_citations as _persist_engine_citations,
)
from app.engine_adapter.drain_reviews import (
    _persist_engine_review_rows as _persist_engine_review_rows,
)
from app.engine_adapter.drain_reviews import (
    _persist_engine_reviews as _persist_engine_reviews,
)
from app.engine_adapter.drain_reviews import (
    _score_or_none as _score_or_none,
)
from app.hypothesis_screening import screen_hypotheses
from app.text_utils import first_sentence

logger = logging.getLogger(__name__)


class DrainResult(NamedTuple):
    """What one drained final state hands the report path and stage events.

    ``report_inputs`` is spread verbatim into ``finalize_report``; the two
    count dicts are emitted by the caller as the post-drain
    ``safety.hypothesis`` and ``citation.grounding`` stage events.
    """

    report_inputs: dict[str, Any]
    safety_counts: dict[str, int]
    grounding_counts: dict[str, int]


class _HypIdentity(NamedTuple):
    """An engine hypothesis's persistence identity and lineage.

    Bundles the fields the drain derives once from an engine hypothesis dict
    and threads into the store row: the statement text, a derived title, and
    the explicit lineage (generation, creating agent, engine id, parent id).
    """

    text: str
    title: str
    generation: int
    agent: str
    engine_id: str | None
    parent_id: str | None


def _article_coalesced_fields(
    art: dict[str, Any],
) -> tuple[str, list[str], str]:
    """Extract an article's (url, authors, abstract), each falling back.

    Isolates the fields whose raw value needs an empty-default fallback (as
    opposed to the fields below that already have a `dict.get` default), so
    the persistence loop stays free of branching.
    """
    url = art.get("url") or ""
    authors = art.get("authors") or []
    abstract = art.get("abstract") or ""
    return url, authors, abstract


def _persist_engine_evidence(
    run_id: str,
    articles: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> tuple[dict[str, str], dict[str, str]]:
    """Persist retrieved articles as evidence rows.

    Returns:
        A tuple of (evidence id by title, abstract by title) lookups the
        hypothesis/citation pass needs: the citation_map carries no abstract
        of its own, so a cited source is classified against its evidence
        row's abstract via this title-keyed map.
    """
    ev_id_by_title: dict[str, str] = {}
    abstract_by_title: dict[str, str] = {}
    for art in articles:
        url, authors, abstract = _article_coalesced_fields(art)
        ev_id = store.add_evidence(
            run_id,
            art.get("title", "Untitled"),
            source=art.get("source", "engine"),
            url=url,
            authors=authors,
            year=art.get("year"),
            abstract=abstract,
            available=bool(url) and not bool(art.get("is_retracted")),
            conn=conn,
        )
        ev_id_by_title[art.get("title", "")] = ev_id
        abstract_by_title[art.get("title", "")] = abstract
    return ev_id_by_title, abstract_by_title


def _derive_hypothesis_identity(h: dict[str, Any]) -> _HypIdentity:
    """Derive an engine hypothesis's statement, title, and explicit lineage.

    Reads the engine's explicit lineage fields (``parent_id``/``generation``/
    ``origin``) rather than reconstructing lineage from ``evolution_history``.
    Pre-lineage cached payloads (which lack these keys) fall
    back to the old ``evolution_history`` inference so old runs still drain.
    The title is the first sentence of the statement (see ``first_sentence``).

    Returns:
        The hypothesis's persistence identity and lineage.
    """
    text = h.get("text", "")
    title = first_sentence(text)
    engine_id = h.get("id") or None

    if "generation" in h or "parent_id" in h or "origin" in h:
        # Explicit lineage from a current engine payload.
        generation = int(h.get("generation", 0))
        parent_id = h.get("parent_id") or None
        agent = str(h.get("origin") or "generation")
    else:
        # Legacy fallback: infer from evolution_history (pre-lineage cache).
        is_evolved = bool(h.get("evolution_history"))
        generation = 1 if is_evolved else 0
        parent_id = None
        agent = "evolution" if is_evolved else "generation"

    return _HypIdentity(text, title, generation, agent, engine_id, parent_id)


def _persist_hypothesis_state(
    hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's mutable state: Elo rating, wins, losses, score."""
    store.update_hypothesis_state(
        hyp_id,
        elo_rating=int(h.get("elo_rating", INITIAL_ELO)),
        win_delta=int(h.get("win_count", 0)),
        loss_delta=int(h.get("loss_count", 0)),
        novelty=_score_or_none(h.get("score", 0)),
        status=(
            "rejected"
            if h.get("review_disposition")
            in {
                "inaccurate",
                "non_novel",
                "inaccurate_and_non_novel",
                "duplicate",
                "evidence_blocked",
            }
            else "active"
        ),
        conn=conn,
    )


def _resolve_persisted_parent_id(
    identity: _HypIdentity, persisted_engine_ids: set[str]
) -> str | None:
    """Return the parent id to persist, dropping references to pruned parents.

    The parent was pruned (e.g. by proximity) whenever it is absent from
    ``persisted_engine_ids``, in which case persisting it would violate the
    ``hypotheses.parent_id`` foreign key, so the child is stored as a root
    with a logged, broken lineage edge instead.
    """
    parent_id = identity.parent_id
    if parent_id is not None and parent_id not in persisted_engine_ids:
        logger.warning(
            "hypothesis %s references pruned parent %s; storing as root",
            identity.engine_id,
            parent_id,
        )
        return None
    return parent_id


def _persist_engine_hypothesis_row(
    run_id: str,
    h: dict[str, Any],
    persisted_engine_ids: set[str],
    conn: sqlite3.Connection,
) -> tuple[str, str | None]:
    """Persist one engine hypothesis's row and mutable state (Elo/wins/losses).

    The engine's stable hypothesis id is passed straight through as the store
    row id, so identity holds end-to-end (engine -> DB -> API -> UI) and
    matchups resolve by id rather than by fragile text-prefix matching.
    ``parent_id`` is carried through (store rows share the engine id, so a
    child's engine parent_id already equals the parent's store row id) via
    ``_resolve_persisted_parent_id``.

    Returns:
        A tuple of (persisted store row id, the engine's own id or None).
    """
    identity = _derive_hypothesis_identity(h)
    parent_id = _resolve_persisted_parent_id(identity, persisted_engine_ids)
    hyp_id = store.add_hypothesis(
        run_id=run_id,
        title=identity.title,
        statement=identity.text,
        hypothesis_id=identity.engine_id,
        parent_id=parent_id,
        category=h.get("category") or None,
        mechanism=h.get("literature_grounding") or "",
        expected_effect=h.get("explanation") or "",
        experimental_context=h.get("experiment") or "",
        generation=identity.generation,
        created_by_agent=identity.agent,
        conn=conn,
    )
    _persist_hypothesis_state(hyp_id, h, conn)
    return hyp_id, identity.engine_id


def _persist_engine_hypothesis(
    run_id: str,
    h: dict[str, Any],
    ev_id_by_title: dict[str, str],
    abstract_by_title: dict[str, str],
    store_id_by_engine_id: dict[str, str],
    citation_summary: dict[str, int],
    persisted_engine_ids: set[str],
    conn: sqlite3.Connection,
) -> None:
    """Persist one engine hypothesis: its row, state, reviews, and citations.

    Mutates `store_id_by_engine_id` (engine id -> persisted row id),
    `ev_id_by_title` (a citation may add evidence for its source on the fly),
    and `citation_summary` (running citation-state counts) in place.
    """
    hyp_id, engine_id = _persist_engine_hypothesis_row(
        run_id, h, persisted_engine_ids, conn
    )
    if engine_id:
        store_id_by_engine_id[engine_id] = hyp_id
    _persist_engine_reviews(run_id, hyp_id, h, conn)
    _persist_engine_citations(
        run_id,
        hyp_id,
        h,
        ev_id_by_title,
        abstract_by_title,
        citation_summary,
        conn,
    )


def _hypotheses_with_proximity_archive(
    active: list[dict[str, Any]], removed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return active hypotheses plus full proximity-pruned archive records."""
    archived: dict[str, dict[str, Any]] = {}
    for record in removed:
        hypothesis = record.get("hypothesis")
        if not isinstance(hypothesis, dict) or not hypothesis.get("id"):
            # Legacy checkpoints retained only a text audit entry. They cannot
            # safely reconstruct stable identity or lineage after the fact.
            continue
        archived_hypothesis = dict(hypothesis)
        archived_hypothesis["review_disposition"] = "duplicate"
        archived[str(archived_hypothesis["id"])] = archived_hypothesis

    # An active row wins if an old audit record and the current pool ever share
    # an id; the archive exists only for hypotheses absent from active ranking.
    by_id = dict(archived)
    by_id.update(
        {
            str(hypothesis["id"]): hypothesis
            for hypothesis in active
            if hypothesis.get("id")
        }
    )
    return list(by_id.values())


def _final_state_list(
    final_state: dict[str, Any], key: str
) -> list[dict[str, Any]]:
    """Return a list-valued key from the engine's final state, or empty."""
    return final_state.get(key) or []


def _final_state_dict(final_state: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a dict-valued key from the engine's final state, or empty."""
    return final_state.get(key) or {}


def _persist_evidence_and_hypotheses(
    run_id: str,
    articles: list[dict[str, Any]],
    hyps_parents_first: list[dict[str, Any]],
    store_id_by_engine_id: dict[str, str],
    citation_summary: dict[str, int],
    persisted_engine_ids: set[str],
    conn: sqlite3.Connection,
) -> None:
    """Persist retrieved evidence, then hypotheses parents before children.

    Mutates `store_id_by_engine_id` and `citation_summary` in place (see
    `_persist_engine_hypothesis`).
    """
    ev_id_by_title, abstract_by_title = _persist_engine_evidence(
        run_id, articles, conn
    )
    for h in hyps_parents_first:
        _persist_engine_hypothesis(
            run_id,
            h,
            ev_id_by_title,
            abstract_by_title,
            store_id_by_engine_id,
            citation_summary,
            persisted_engine_ids,
            conn,
        )


def _screen_and_collect_grounding_inputs(
    run_id: str, conn: sqlite3.Connection
) -> tuple[Any, list[EvidencePassage], list[dict[str, Any]]]:
    """Run the per-hypothesis safety screen and gather claim-grounding inputs.

    The engine ran its tournament internally, so the safety screen enforces
    the guarantee at the app boundary -- blocked hypotheses are marked and
    the report path (finalize_report) excludes them from ranking/synthesis
    exposure. Grounding inputs are read here (inside the transaction) but the
    claim assessment itself runs later, outside any transaction.

    Returns:
        A tuple of (screening result, evidence passages, grounding
        candidates -- persisted hypotheses not already rejected).
    """
    persisted = store.list_hypotheses(run_id, conn=conn)
    screening_result = screen_hypotheses(run_id, persisted, conn=conn)
    passages = evidence_passages(run_id, conn=conn)
    grounding_candidates = [
        hypothesis
        for hypothesis in persisted
        if hypothesis.get("status") != "rejected"
    ]
    return screening_result, passages, grounding_candidates


def _persist_grounding_matches_and_proximity(
    run_id: str,
    assessed: Any,
    matchups: list[dict[str, Any]],
    store_id_by_engine_id: dict[str, str],
    proximity_graph: dict[str, Any],
    conn: sqlite3.Connection,
) -> Any:
    """Persist claim grounding, tournament matches, and the proximity graph.

    Pure database work: the claim assessment that produced `assessed` has
    already run, outside any transaction.

    Returns:
        The claim-grounding persistence result.
    """
    grounding_result = persist_grounding(run_id, assessed, conn=conn)
    _persist_engine_matches(run_id, matchups, store_id_by_engine_id, conn)
    _persist_engine_proximity(
        run_id, proximity_graph, store_id_by_engine_id, conn
    )
    return grounding_result


def _build_drain_result(
    final_state: dict[str, Any],
    citation_summary: dict[str, int],
    screening_result: Any,
    grounding_result: Any,
    grounding_candidates: list[dict[str, Any]],
) -> DrainResult:
    """Assemble the `DrainResult` from a completed drain's tallies."""
    return DrainResult(
        report_inputs={
            "citation_summary": citation_summary,
            "meta_review": _final_state_dict(final_state, "meta_review"),
            "research_overview": _final_state_dict(
                final_state, "research_overview"
            ),
        },
        safety_counts={
            "screened": screening_result.screened_count,
            "blocked": screening_result.blocked_count,
            "eligible": (
                screening_result.screened_count - screening_result.blocked_count
            ),
        },
        grounding_counts={
            "grounded": len(grounding_result.reason_by_id),
            "blocked": grounding_result.blocked_count,
            "eligible": (
                len(grounding_candidates) - grounding_result.blocked_count
            ),
        },
    )


class _FinalStateInputs(NamedTuple):
    """Precomputed persistence inputs derived from an engine final state."""

    hyps_parents_first: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    matchups: list[dict[str, Any]]
    proximity_graph: dict[str, Any]
    persisted_engine_ids: set[str]


def _prepare_final_state_inputs(
    final_state: dict[str, Any],
) -> _FinalStateInputs:
    """Derive the drain's persistence inputs from an engine final state.

    Hypotheses are ordered parents-first so the ``parent_id`` foreign key
    resolves during insertion. ``persisted_engine_ids`` is every engine id
    being persisted, so a child's parent_id is only kept when the parent is
    also stored (see ``_resolve_persisted_parent_id``); the walrus narrows
    the element type to str (dropping the None from an id-less row).
    """
    hyps = _hypotheses_with_proximity_archive(
        _final_state_list(final_state, "hypotheses"),
        _final_state_list(final_state, "removed_duplicates"),
    )
    persisted_engine_ids = {hid for h in hyps if (hid := h.get("id"))}
    hyps_parents_first = sorted(hyps, key=lambda h: int(h.get("generation", 0)))
    return _FinalStateInputs(
        hyps_parents_first=hyps_parents_first,
        articles=_final_state_list(final_state, "articles"),
        matchups=_final_state_list(final_state, "tournament_matchups"),
        proximity_graph=_final_state_dict(final_state, "proximity_graph"),
        persisted_engine_ids=persisted_engine_ids,
    )


def _assess_claims(
    grounding_candidates: list[dict[str, Any]],
    passages: list[EvidencePassage],
) -> Any:
    """Assess each hypothesis claim against retrieved evidence passages.

    Must run outside any transaction -- see ``_persist_final_state``.
    """
    assessor, assessor_id = build_assessor(
        settings.claim_assessor,
        settings.claim_verifier_model or settings.model_name,
    )
    return assess_hypothesis_claims(
        grounding_candidates,
        passages,
        assessor=assessor,
        assessor_id=assessor_id,
    )


def _persist_evidence_hypotheses_and_screen(
    run_id: str,
    inputs: _FinalStateInputs,
    citation_summary: dict[str, int],
    store_id_by_engine_id: dict[str, str],
    db_path: str | None,
) -> tuple[Any, list[EvidencePassage], list[dict[str, Any]]]:
    """Run the drain's first transaction: evidence, hypotheses, screening.

    Batches this half of the drain into one transaction: a real run writes
    dozens of rows here, and per-call connections would fsync each one
    individually. Mutates `citation_summary` and `store_id_by_engine_id` in
    place.

    Returns:
        The (screening result, evidence passages, grounding candidates)
        tuple `_screen_and_collect_grounding_inputs` produces.
    """
    with store.transaction(db_path) as conn:
        _persist_evidence_and_hypotheses(
            run_id,
            inputs.articles,
            inputs.hyps_parents_first,
            store_id_by_engine_id,
            citation_summary,
            inputs.persisted_engine_ids,
            conn,
        )
        return _screen_and_collect_grounding_inputs(run_id, conn)


def _persist_grounding_matches_proximity_txn(
    run_id: str,
    assessed: Any,
    inputs: _FinalStateInputs,
    store_id_by_engine_id: dict[str, str],
    db_path: str | None,
) -> Any:
    """Run the drain's second transaction: grounding, matches, proximity."""
    with store.transaction(db_path) as conn:
        return _persist_grounding_matches_and_proximity(
            run_id,
            assessed,
            inputs.matchups,
            store_id_by_engine_id,
            inputs.proximity_graph,
            conn,
        )


def _persist_final_state(
    *,
    run_id: str,
    final_state: dict[str, Any],
    db_path: str | None = None,
) -> DrainResult:
    """Drain an engine final state into the store.

    Writes evidence, hypotheses (with reviews, deep-verification reviews,
    and citations), and tournament matches; the report is built separately
    by ``finalize_report``, which consumes the returned inputs.

    Claim assessment (provider work, no DB) runs between the two
    transactions, via ``_assess_claims``: it used to run inside one
    transaction, holding SQLite's write lock across minutes of network I/O.
    Never reorder a store call relative to it, or extend a transaction.

    Returns:
        A :class:`DrainResult`: the ``finalize_report`` kwargs plus the
        screen/grounding tallies emitted as post-drain stage events.
    """
    inputs = _prepare_final_state_inputs(final_state)
    citation_summary = empty_citation_summary()
    store_id_by_engine_id: dict[str, str] = {}
    screening_result, passages, grounding_candidates = (
        _persist_evidence_hypotheses_and_screen(
            run_id, inputs, citation_summary, store_id_by_engine_id, db_path
        )
    )
    assessed = _assess_claims(grounding_candidates, passages)
    grounding_result = _persist_grounding_matches_proximity_txn(
        run_id, assessed, inputs, store_id_by_engine_id, db_path
    )
    return _build_drain_result(
        final_state,
        citation_summary,
        screening_result,
        grounding_result,
        grounding_candidates,
    )
