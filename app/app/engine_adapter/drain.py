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
from app.citations import (
    CitationRecord,
    classify_citation,
    empty_citation_summary,
)
from app.claim_grounding import (
    build_assessor,
    evidence_passages,
    ground_hypotheses,
)
from app.config import settings
from app.elo import INITIAL_ELO
from app.hypothesis_screening import screen_hypotheses
from app.report_render import format_deep_verification_critique
from app.text_utils import first_sentence

logger = logging.getLogger(__name__)


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
    ``origin``) rather than reconstructing lineage from ``evolution_history``
    (PLAN.md M1.4). Pre-lineage cached payloads (which lack these keys) fall
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
        novelty=float(h.get("score", 0) or 0) or None,
        status=(
            "rejected"
            if h.get("review_disposition")
            in {"inaccurate", "non_novel", "inaccurate_and_non_novel"}
            else "active"
        ),
        conn=conn,
    )


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
    child's engine parent_id already equals the parent's store row id), but
    only when that parent is itself in the persisted set — otherwise the
    parent was pruned (e.g. by proximity) and the ``hypotheses.parent_id``
    foreign key would be violated, so the child is stored as a root with a
    logged, broken lineage edge.

    Returns:
        A tuple of (persisted store row id, the engine's own id or None).
    """
    identity = _derive_hypothesis_identity(h)
    parent_id = identity.parent_id
    if parent_id is not None and parent_id not in persisted_engine_ids:
        logger.warning(
            "hypothesis %s references pruned parent %s; storing as root",
            identity.engine_id,
            parent_id,
        )
        parent_id = None
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


def _score_or_none(value: Any) -> float | None:
    """Coerce a raw engine score to a float, treating 0/falsy as unset."""
    return float(value or 0) or None


def _persist_engine_review_rows(
    run_id: str, hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's per-review rows from the engine's reviews list."""
    for rv in h.get("reviews") or []:
        scores = rv.get("scores", {})
        store.add_review(
            run_id=run_id,
            hypothesis_id=hyp_id,
            reviewer_agent="review",
            summary=rv.get("review_summary", ""),
            critique=rv.get("constructive_feedback", ""),
            novelty=_score_or_none(scores.get("novelty", 0)),
            plausibility=_score_or_none(scores.get("scientific_soundness", 0)),
            testability=_score_or_none(scores.get("testability", 0)),
            overall=_score_or_none(rv.get("overall_score", 0)),
            conn=conn,
        )


def _persist_deep_verification_review(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist deep-verification probes as a dedicated review row, if any."""
    probes = h.get("deep_verification_probes") or []
    if not probes:
        return
    summary, critique = format_deep_verification_critique(
        probes, h.get("deep_verification_verdict")
    )
    store.add_review(
        run_id=run_id,
        hypothesis_id=hyp_id,
        reviewer_agent="deep_verification",
        summary=summary,
        critique=critique,
        conn=conn,
    )


def _persist_engine_reviews(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's per-review rows plus its deep-verification row."""
    _persist_engine_review_rows(run_id, hyp_id, h, conn)
    _persist_deep_verification_review(run_id, hyp_id, h, conn)


def _ensure_citation_evidence_id(
    run_id: str,
    cite_title: str,
    cite_info: dict[str, Any],
    cite_url: str,
    ev_id_by_title: dict[str, str],
    conn: sqlite3.Connection,
) -> str:
    """Return the evidence id for a cited source, adding it on the fly.

    Mutates `ev_id_by_title` in place when a new evidence row is added.
    """
    cite_ev_id = ev_id_by_title.get(cite_title)
    if cite_ev_id is None:
        cite_ev_id = store.add_evidence(
            run_id,
            cite_title,
            source=cite_info.get("type", "engine"),
            url=cite_url,
            authors=cite_info.get("authors") or [],
            year=cite_info.get("year"),
            abstract="",
            available=True,
            conn=conn,
        )
        ev_id_by_title[cite_title] = cite_ev_id
    return cite_ev_id


def _hypothesis_grounding_text(h: dict[str, Any]) -> str:
    """Return the literature-grounding text used as a citation's claim basis.

    Falls back to the hypothesis's own statement text, then to empty, when no
    dedicated grounding text was generated.
    """
    return str(h.get("literature_grounding") or h.get("text") or "")


def _citation_map(h: dict[str, Any]) -> dict[str, Any]:
    """Return a hypothesis's raw engine citation map, defaulting to empty."""
    return h.get("citation_map") or {}


def _citation_url(cite_info: dict[str, Any]) -> str:
    """Return a citation's URL, defaulting to empty (an unavailable source)."""
    return cite_info.get("url") or ""


def _persist_engine_citations(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    ev_id_by_title: dict[str, str],
    abstract_by_title: dict[str, str],
    citation_summary: dict[str, int],
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's citations, classifying each via the shared path.

    Route each through the shared classifier (the same path the mock uses)
    rather than hardcoding a state, so the four-state citation UI reflects
    real runs. The hypothesis grounding is the claim the citation supports;
    it is matched against the cited paper's abstract (when the source was
    retrieved), and a source with no resolvable URL (e.g. a knowledge-graph
    statement) falls out as "unavailable".

    Mutates `ev_id_by_title` (a citation may add evidence for its source on
    the fly) and `citation_summary` (running citation-state counts) in place.
    """
    grounding = _hypothesis_grounding_text(h)
    for cite_key, cite_info in _citation_map(h).items():
        cite_title = cite_info.get("title", cite_key)
        cite_url = _citation_url(cite_info)
        cite_ev_id = _ensure_citation_evidence_id(
            run_id, cite_title, cite_info, cite_url, ev_id_by_title, conn
        )
        claim = f"[{cite_key}] cited in hypothesis"
        state = classify_citation(
            CitationRecord(
                url=cite_url,
                abstract=abstract_by_title.get(cite_title, ""),
                claim=grounding,
                available=(
                    bool(cite_url)
                    and not bool(cite_info.get("is_retracted"))
                    and str(cite_info.get("correction_status") or "").lower()
                    != "retracted"
                ),
            )
        )
        citation_summary[state] += 1
        store.add_citation(run_id, hyp_id, cite_ev_id, claim, state, conn=conn)


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
            run_id=run_id,
            iteration=0,
            winner_id=winner_id,
            loser_id=loser_id,
            winner_before=int(m.get("winner_elo_before", INITIAL_ELO)),
            winner_after=int(m.get("winner_elo_after", INITIAL_ELO)),
            loser_before=int(m.get("loser_elo_before", INITIAL_ELO)),
            loser_after=int(m.get("loser_elo_after", INITIAL_ELO)),
            rationale=m.get("reasoning", ""),
            tier=m.get("tier") or None,
            debate_turns=int(m.get("debate_turns", 1)),
            conn=conn,
        )


def _final_state_list(
    final_state: dict[str, Any], key: str
) -> list[dict[str, Any]]:
    """Return a list-valued key from the engine's final state, or empty."""
    return final_state.get(key) or []


def _final_state_dict(final_state: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a dict-valued key from the engine's final state, or empty."""
    return final_state.get(key) or {}


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
            run_id,
            source,
            target,
            float(edge.get("similarity", 0.0)),
            degree=edge.get("degree"),
            cluster_id=edge.get("cluster_id"),
            method=meta.get("method"),
            version=meta.get("version"),
            model=meta.get("model"),
            updated_at=meta.get("updated_at"),
            conn=conn,
        )


def _persist_final_state(
    *,
    run_id: str,
    final_state: dict[str, Any],
    db_path: str | None = None,
) -> dict[str, Any]:
    """Drain an engine final state into the store.

    Writes evidence, hypotheses (with reviews, deep-verification reviews, and
    citations), and tournament matches. Deep-verification probes ride the
    reviews table as ``reviewer_agent="deep_verification"`` rows. The report
    itself is built and persisted separately by ``finalize_report``; this helper
    returns the provider-specific inputs that path needs.

    Args:
        run_id: Identifier of the run being drained.
        final_state: Accumulated engine final state.
        db_path: Optional override for the SQLite database path.

    Returns:
        The report inputs only this provider knows: ``citation_summary``,
        ``meta_review``, and ``research_overview``. Row counts are not
        returned; ``finalize_report`` reads them from the store.
    """
    hyps = _final_state_list(final_state, "hypotheses")
    articles = _final_state_list(final_state, "articles")
    matchups = _final_state_list(final_state, "tournament_matchups")
    proximity_graph = _final_state_dict(final_state, "proximity_graph")
    citation_summary = empty_citation_summary()
    store_id_by_engine_id: dict[str, str] = {}
    # Every engine id being persisted, so a child's parent_id foreign key is
    # only set when the parent is also stored (see
    # _persist_engine_hypothesis_row). The walrus narrows the element type to
    # str (dropping the None from an id-less row).
    persisted_engine_ids = {hid for h in hyps if (hid := h.get("id"))}
    # Insert parents before children so the parent_id foreign key resolves.
    hyps_parents_first = sorted(hyps, key=lambda h: int(h.get("generation", 0)))

    # Batch the whole drain into one transaction: a real run writes dozens of
    # rows here, and per-call connections would fsync each one individually.
    with store.transaction(db_path) as conn:
        # 1. Evidence: persist retrieved articles.
        ev_id_by_title, abstract_by_title = _persist_engine_evidence(
            run_id, articles, conn
        )

        # 2. Hypotheses: persist parents before children (lineage order).
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

        # 3. Per-hypothesis safety screen: persist each hypothesis's
        # safety_status and record any blocking outcome. The engine ran its
        # tournament internally, so this enforces the guarantee at the app
        # boundary — blocked hypotheses are marked and the report path
        # (finalize_report) excludes them from ranking/synthesis exposure.
        persisted = store.list_hypotheses(run_id, conn=conn)
        screen_hypotheses(run_id, persisted, conn=conn)

        # 4. Claim-level grounding: extract atomic claims, retrieve and assess
        # each against the retrieved evidence (deterministic by default, or the
        # semantic NLI assessor when settings.claim_assessor == "llm"), persist
        # the provenance-stamped claim-evidence graph, and record any
        # contradicted (publication-gate blocking) hypothesis.
        passages = evidence_passages(run_id, conn=conn)
        assessor, assessor_id = build_assessor(
            settings.claim_assessor,
            settings.claim_verifier_model or settings.model_name,
        )
        ground_hypotheses(
            run_id,
            persisted,
            passages,
            assessor=assessor,
            assessor_id=assessor_id,
            conn=conn,
        )

        # 5. Tournament matches: resolve each side by the engine's stable
        # hypothesis id.
        _persist_engine_matches(run_id, matchups, store_id_by_engine_id, conn)

        # 6. Proximity graph: resolve engine ids after every hypothesis exists.
        _persist_engine_proximity(
            run_id, proximity_graph, store_id_by_engine_id, conn
        )

    return {
        "citation_summary": citation_summary,
        "meta_review": _final_state_dict(final_state, "meta_review"),
        "research_overview": _final_state_dict(
            final_state, "research_overview"
        ),
    }
