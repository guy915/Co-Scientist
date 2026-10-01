"""Citation persistence for the engine final-state drain.

Holds the per-hypothesis citation pass: resolving (or adding) the evidence
row a citation points at, narrowing the grounding paragraph to the part that
actually cites a given source, and classifying the pair through the shared
citation path. Split out of ``drain.reviews`` by concern once that module
outgrew the repository's 500-line file ceiling -- reviews and citations
share no helper, so the seam is clean. ``drain.reviews`` re-exports the
names callers use, so importers written against it keep resolving.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from app import store
from app.citations import CitationRecord, classify_citation
from app.claims_assessor import SENTENCE_SPLIT

# Bracketed citation groups inside a grounding sentence: "[C1]", "[C1, C3]".
_BRACKET_GROUP = re.compile(r"\[([^\[\]]+)\]")


@dataclass(frozen=True)
class _CitationSink:
    """The drain's citation lookups, mutated in place as rows are written.

    Attributes:
        ev_id_by_title: Evidence id per source title; a citation may add its
            own source on the fly.
        abstract_by_title: Abstract per retrieved source title, used to
            classify a citation against the paper it cites.
        citation_summary: Running per-state citation counts.
    """

    ev_id_by_title: dict[str, str]
    abstract_by_title: dict[str, str]
    citation_summary: dict[str, int]


@dataclass(frozen=True)
class _CitationTarget:
    """The hypothesis row a citation attaches to, inside one transaction.

    Attributes:
        run_id: Run the citation belongs to.
        hyp_id: Persisted hypothesis row the citation attaches to.
        grounding: Claim text the citation is matched against.
        conn: Open connection of the caller's transaction.
    """

    run_id: str
    hyp_id: str
    grounding: str
    conn: sqlite3.Connection


def _ensure_citation_evidence_id(
    run_id: str,
    cite_title: str,
    cite_info: dict[str, Any],
    ev_id_by_title: dict[str, str],
    conn: sqlite3.Connection,
) -> str:
    """Return the evidence id for a cited source, adding it on the fly.

    Mutates `ev_id_by_title` in place when a new evidence row is added.

    Args:
        run_id: Run the cited source belongs to.
        cite_title: Title the source is keyed by.
        cite_info: The engine's raw citation entry.
        ev_id_by_title: Evidence id per source title, updated in place.
        conn: Open connection of the caller's transaction.

    Returns:
        The evidence id for the cited source.
    """
    cite_ev_id = ev_id_by_title.get(cite_title)
    if cite_ev_id is None:
        cite_ev_id = store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=cite_title,
                source=cite_info.get("type", "engine"),
                url=_citation_url(cite_info),
                authors=cite_info.get("authors") or [],
                year=cite_info.get("year"),
                abstract="",
                available=True,
            ),
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


def _claim_cited_by(grounding: str, cite_key: str) -> str:
    """The part of a grounding paragraph that actually cites ``cite_key``.

    A grounding is a synthesis spanning every source the hypothesis rests on,
    and each source backs one or two of its sentences. ``_token_overlap``
    measures coverage over the *claim's* vocabulary, so handing a single
    paper's abstract the whole paragraph divides its real overlap by every
    other source's words as well -- which puts the upper states out of reach
    however well the paper supports what it was cited for. On one live run
    the best of 27 citations scored 0.23 against a 0.30 "partial" line, and
    the audit reported 0 verified, 0 partial, 33 unsupported: the same
    unreachable-upper-states failure the coverage metric was introduced to
    fix, arriving through the claim side instead of the metric.

    Args:
        grounding: The hypothesis's whole literature-grounding text.
        cite_key: The engine's key for one citation (e.g. ``C1``).

    Returns:
        The grounding sentences carrying a ``[C1]``-style marker for this
        key, or the whole grounding when the key is not marked inline (a
        knowledge-graph source, or a payload that never inlined markers).
    """
    marker = f"[{cite_key}]"
    cited = [
        sentence
        for sentence in SENTENCE_SPLIT.split(grounding)
        # A sentence may list several keys ("[C1, C3]"), so match the key
        # inside a bracket group rather than only a lone marker.
        if marker in sentence
        or any(
            cite_key == part.strip()
            for group in _BRACKET_GROUP.findall(sentence)
            for part in group.split(",")
        )
    ]
    return " ".join(cited).strip() or grounding


def _citation_map(h: dict[str, Any]) -> dict[str, Any]:
    """Return a hypothesis's raw engine citation map, defaulting to empty."""
    return h.get("citation_map") or {}


def _citation_url(cite_info: dict[str, Any]) -> str:
    """Return a citation's URL, defaulting to empty (an unavailable source)."""
    return cite_info.get("url") or ""


def _citation_available(cite_info: dict[str, Any], cite_url: str) -> bool:
    """Return whether a cited source counts as available (not retracted)."""
    return (
        bool(cite_url)
        and not bool(cite_info.get("is_retracted"))
        and str(cite_info.get("correction_status") or "").lower() != "retracted"
    )


def _persist_one_citation(
    target: _CitationTarget,
    cite_key: str,
    cite_info: dict[str, Any],
    sink: _CitationSink,
) -> None:
    """Persist one hypothesis citation row, classifying and tallying it.

    Routes the citation through the shared classifier rather than hardcoding
    a state, so the four-state citation UI reflects real runs. The target's
    grounding is the claim the citation supports; it is matched against the
    cited paper's abstract (when the source was retrieved), and a source
    with no resolvable URL (e.g. a knowledge-graph statement) falls out as
    "unavailable".

    Mutates the sink's `ev_id_by_title` (a citation may add evidence for its
    source on the fly) and `citation_summary` (running citation-state
    counts) in place.

    Args:
        target: The hypothesis row, its claim text, and the transaction.
        cite_key: The engine's key for this citation.
        cite_info: The engine's raw citation entry.
        sink: The drain's citation lookups, updated in place.
    """
    # "title" is a paper's own field; a non-paper source (knowledge-graph
    # statement, CVE entry, ...) carries no title at all, only "display"
    # (see citations._enrichment_reference_entries) -- falling straight to
    # cite_key would persist an evidence row literally titled "C3".
    cite_title = cite_info.get("title") or cite_info.get("display") or cite_key
    cite_url = _citation_url(cite_info)
    cite_ev_id = _ensure_citation_evidence_id(
        target.run_id,
        cite_title,
        cite_info,
        sink.ev_id_by_title,
        target.conn,
    )
    claim = f"[{cite_key}] cited in hypothesis"
    state = classify_citation(
        CitationRecord(
            url=cite_url,
            abstract=sink.abstract_by_title.get(cite_title, ""),
            claim=_claim_cited_by(target.grounding, cite_key),
            available=_citation_available(cite_info, cite_url),
        )
    )
    sink.citation_summary[state] += 1
    store.add_citation(
        store.NewCitation(
            run_id=target.run_id,
            hypothesis_id=target.hyp_id,
            evidence_id=cite_ev_id,
            claim=claim,
            state=state,
        ),
        conn=target.conn,
    )


def _persist_engine_citations(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    sink: _CitationSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's citations, classifying each via the shared path.

    Mutates the sink's `ev_id_by_title` (a citation may add evidence for its
    source on the fly) and `citation_summary` (running citation-state
    counts) in place; see `_persist_one_citation` for the per-citation
    classification rules.

    Args:
        run_id: Run the hypothesis belongs to.
        hyp_id: Persisted hypothesis row the citations attach to.
        h: The engine's raw hypothesis payload.
        sink: The drain's citation lookups, updated in place.
        conn: Open connection of the caller's transaction.
    """
    target = _CitationTarget(
        run_id, hyp_id, _hypothesis_grounding_text(h), conn
    )
    for cite_key, cite_info in _citation_map(h).items():
        _persist_one_citation(target, cite_key, cite_info, sink)
