"""Evidence and hypothesis persistence for the engine final-state drain.

Holds the per-row persistence helpers the drain runs inside its first
transaction: retrieved articles as evidence rows, and each engine
hypothesis (identity/lineage derivation, the store row, its mutable Elo
state, and its reviews/citations via the ``drain_reviews`` helpers), plus
the proximity-pruned archive merge. Split from ``drain`` by concern;
``drain`` re-exports every name so its namespace keeps resolving.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, NamedTuple

from app import store
from app.elo import INITIAL_ELO
from app.engine_adapter.drain_reviews import (
    _CitationSink,
    _persist_engine_citations,
    _persist_engine_reviews,
    _score_or_none,
)
from app.text_utils import first_sentence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _HypothesisSink:
    """The drain's hypothesis lookups, mutated in place as rows are written.

    Attributes:
        citations: Evidence/abstract/citation-count lookups the citation
            pass reads and updates.
        store_id_by_engine_id: Persisted row id per engine hypothesis id.
        persisted_engine_ids: Every engine id this drain is persisting, so a
            child's parent reference is only kept when the parent is stored.
    """

    citations: _CitationSink
    store_id_by_engine_id: dict[str, str]
    persisted_engine_ids: set[str]


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
    citations: _CitationSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist retrieved articles as evidence rows.

    Fills the sink's (evidence id by title, abstract by title) lookups the
    hypothesis/citation pass needs: the citation_map carries no abstract of
    its own, so a cited source is classified against its evidence row's
    abstract via this title-keyed map.

    Args:
        run_id: Run the evidence belongs to.
        articles: The engine's retrieved articles.
        citations: The drain's citation lookups, filled in place.
        conn: Open connection of the caller's transaction.
    """
    ev_id_by_title = citations.ev_id_by_title
    abstract_by_title = citations.abstract_by_title
    for art in articles:
        url, authors, abstract = _article_coalesced_fields(art)
        ev_id = store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=art.get("title", "Untitled"),
                source=art.get("source", "engine"),
                url=url,
                authors=authors,
                year=art.get("year"),
                abstract=abstract,
                available=bool(url) and not bool(art.get("is_retracted")),
            ),
            conn=conn,
        )
        ev_id_by_title[art.get("title", "")] = ev_id
        abstract_by_title[art.get("title", "")] = abstract


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


BLOCKING_REVIEW_DISPOSITIONS = frozenset(
    {
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "evidence_blocked",
    }
)

# Excluded from the ranked report, but not by a judgement on the idea: a
# duplicate is archived by proximity because a higher-ranked idea already
# says the same thing. Kept apart from BLOCKING_REVIEW_DISPOSITIONS so the
# two reach the reader as different words -- lumping them told a scientist
# their ideas had been rejected on the merits when most had simply been
# deduplicated. One run showed twenty "Disqualified" ideas on that basis.
DEDUPLICATED_REVIEW_DISPOSITION = "duplicate"


def _hypothesis_status(h: dict[str, Any]) -> str:
    """Return the persisted status for a drained hypothesis.

    Three outcomes the UI must be able to tell apart:

    - ``rejected``: excluded from the tournament on merit. Mirrors the
      engine's ``Hypothesis.is_rankable`` -- a blocking review disposition
      *or* a deep-verification verdict of "undermined". An undermined idea
      recorded as active would show as merely unranked, which is exactly
      the conflation this status exists to remove.
    - ``duplicate``: archived by proximity as redundant, not judged.
    - ``active``: everything else, including ideas the initial review
      flagged as needing revision -- those still rank and publish.
    """
    if h.get("review_disposition") == DEDUPLICATED_REVIEW_DISPOSITION:
        return "duplicate"
    if (
        h.get("review_disposition") in BLOCKING_REVIEW_DISPOSITIONS
        or h.get("deep_verification_verdict") == "undermined"
    ):
        return "rejected"
    return "active"


def _is_rejected(h: dict[str, Any]) -> bool:
    """Return whether a hypothesis was excluded from the tournament."""
    return _hypothesis_status(h) != "active"


def _persist_hypothesis_state(
    hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's mutable state: Elo rating, wins, losses, score."""
    store.update_hypothesis_state(
        hyp_id,
        store.HypothesisStateChanges(
            elo_rating=int(h.get("elo_rating", INITIAL_ELO)),
            win_delta=int(h.get("win_count", 0)),
            loss_delta=int(h.get("loss_count", 0)),
            novelty=_score_or_none(h.get("score", 0)),
            status=_hypothesis_status(h),
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
        store.NewHypothesis(
            run_id=run_id,
            title=identity.title,
            statement=identity.text,
            hypothesis_id=identity.engine_id,
            parent_id=parent_id,
            generation=identity.generation,
            category=h.get("category") or None,
            mechanism=h.get("literature_grounding") or "",
            expected_effect=h.get("explanation") or "",
            experimental_context=h.get("experiment") or "",
            created_by_agent=identity.agent,
        ),
        conn=conn,
    )
    _persist_hypothesis_state(hyp_id, h, conn)
    return hyp_id, identity.engine_id


def _persist_engine_hypothesis(
    run_id: str,
    h: dict[str, Any],
    sink: _HypothesisSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist one engine hypothesis: its row, state, reviews, and citations.

    Mutates the sink in place: `store_id_by_engine_id` (engine id ->
    persisted row id), `citations.ev_id_by_title` (a citation may add
    evidence for its source on the fly), and `citations.citation_summary`
    (running citation-state counts).

    Args:
        run_id: Run the hypothesis belongs to.
        h: The engine's raw hypothesis payload.
        sink: The drain's hypothesis and citation lookups.
        conn: Open connection of the caller's transaction.
    """
    hyp_id, engine_id = _persist_engine_hypothesis_row(
        run_id, h, sink.persisted_engine_ids, conn
    )
    if engine_id:
        sink.store_id_by_engine_id[engine_id] = hyp_id
    _persist_engine_reviews(run_id, hyp_id, h, conn)
    _persist_engine_citations(run_id, hyp_id, h, sink.citations, conn)


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
