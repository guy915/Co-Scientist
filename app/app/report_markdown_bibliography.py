"""Report section listing every source a run actually retrieved (R12-12).

Google's published MASH report ends with a flat, 3,259-entry ``References``
list (docs/CORPUS-EXTRACTION.md R12-12) -- every distinct source the run's
literature search touched, not just the ones a hypothesis's mechanism text
cites inline. Our own per-hypothesis ``#### References`` subsections
(``report_markdown_references.py``, R14-21) resolve only the ``[C*]`` keys a
hypothesis's mechanism text actually names; this section is the aggregate
the corpus row asks for -- everything ``store.list_evidence`` persisted for
the run, deduplicated once, in one place.

Source of truth: the same ``evidence`` rows every other reader already
gets -- ``store.list_evidence``, read once by ``report_build`` and handed to
the markdown document (``ReportMarkdownInputs.evidence``) and the Learning
tab's own references list (``run_detail_learning_references.tsx``). No new
store read, no parallel path.

Dedup: a run can retrieve the same paper through more than one search
(PubMed and a preprint server, e.g.), each landing its own ``evidence`` row
-- nothing amongst the drain or store dedups them today. A stable identity
is resolved per row, DOI first, then PMID, then URL, then a normalized
title, and the first-persisted row wins when two collide -- ``store.
list_evidence`` orders by ``created_at``, a real per-run fact rather than a
render-time coincidence, so the winner never changes between renders of the
same run.

Placement: last in the document, matching the published MASH report's own
bibliography span (``research-overviews/mash-....md``, directly after the
run's Open Questions / Clear Patterns / Unexpected Connections span at
L746-818, then References at L832; R12-10's own sink is already
``report_markdown_overview.py``). It is a run-wide list (every source the
whole run touched), not a per-idea one, so it belongs beside the other
whole-run sections (Knowledge Base, Data sources) rather than immediately
after any one hypothesis's own per-idea ``#### References`` subsections
(R14-21) -- a second, differently-scoped ``## References`` heading placed
there would collide with those.

Ordering: alphabetically by the same label text the entry renders
(``_reference_label(...).casefold()``), not by retrieval time or insertion
order. A reader can find an entry by its visible text, and retrieval order
depends on search timing that can differ between functionally identical
runs -- an evidence-order list would look shuffled for no reason a reader
could see.
"""

from __future__ import annotations

from typing import Any

from app.citation_metadata import (
    CitationMetadata,
    DateState,
    SourceType,
    classify_date,
    classify_source_type,
)
from app.report_markdown_references import _reference_label


def _normalized_title(title: str) -> str:
    """Collapse whitespace/case for the title-based dedup fallback key."""
    return " ".join(title.strip().lower().split())


def _evidence_identity(evidence: dict[str, Any]) -> str:
    """Return one evidence row's dedup identity: DOI > PMID > URL > title.

    Always resolves to something -- ``evidence.title`` is ``NOT NULL`` in
    the schema, so the title fallback never actually fails for real data.
    The row's own id is a last-resort key for a synthetic/test row with
    none of the above, so an unidentifiable row is never merged with
    another one that is equally unidentifiable.
    """
    doi = str(evidence.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    pmid = str(evidence.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    url = str(evidence.get("url") or "").strip()
    if url:
        return f"url:{url}"
    title = _normalized_title(str(evidence.get("title") or ""))
    if title:
        return f"title:{title}"
    return f"id:{evidence.get('id')}"


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a run's evidence rows to one per stable identity.

    First-seen wins -- the caller hands rows in ``store.list_evidence``'s
    own ``created_at`` order, so the survivor is always the earliest-
    persisted copy of a source the run retrieved more than once, not
    whichever the caller's own iteration happens to visit first.
    """
    by_identity: dict[str, dict[str, Any]] = {}
    for row in evidence:
        by_identity.setdefault(_evidence_identity(row), row)
    return list(by_identity.values())


def _identifier_suffix(evidence: dict[str, Any]) -> str:
    """Trailing '(DOI: ...)' / '(PMID: ...)' when the row carries one.

    Same DOI-then-PMID precedence as ``_evidence_identity`` -- whichever
    identifier is authoritative for dedup is also the one shown.
    """
    doi = str(evidence.get("doi") or "").strip()
    if doi:
        return f" (DOI: {doi})"
    pmid = str(evidence.get("pmid") or "").strip()
    if pmid:
        return f" (PMID: {pmid})"
    return ""


def _retracted_suffix(evidence: dict[str, Any]) -> str:
    """Flag a withdrawn source -- the same fact the Learning tab pins (D18).

    A bibliography listing a retracted paper as a plain reference is the
    exact defect the Learning tab's own retracted pill exists to avoid.
    """
    return " (retracted)" if evidence.get("retracted") else ""


# Only the source types a reader would otherwise mistake for a reviewed
# paper are named. A peer-reviewed article is what a bibliography entry
# already reads as, so labelling it adds a word to every line and
# distinguishes nothing; an unclassifiable row says nothing rather than
# claiming a type it does not know.
_SOURCE_TYPE_WORDS = {
    SourceType.PREPRINT: "preprint",
    SourceType.DATABASE: "database record",
    SourceType.WEB: "web page",
    SourceType.DOCUMENT: "attached document",
}


def _row_metadata(evidence: dict[str, Any]) -> CitationMetadata:
    """Read one evidence row back as the citation metadata it describes."""
    return CitationMetadata(
        url=str(evidence.get("url") or ""),
        doi=str(evidence.get("doi") or ""),
        pmid=str(evidence.get("pmid") or ""),
        retracted=bool(evidence.get("retracted")),
        source=str(evidence.get("source") or ""),
        year=evidence.get("year"),
    )


def _row_source_type(evidence: dict[str, Any]) -> SourceType:
    """Resolve one row's source type, persisted value first.

    The drain's classification saw the publisher's declared publication
    type, which this row no longer carries, so it wins where it exists;
    a row predating the column, or evidence that never went through the
    drain, is classified from what it does carry.
    """
    stored = str(evidence.get("source_type") or "")
    if stored in {member.value for member in SourceType}:
        return SourceType(stored)
    return classify_source_type(_row_metadata(evidence))


def _source_type_suffix(source_type: SourceType) -> str:
    """Name a source that is not a peer-reviewed paper."""
    word = _SOURCE_TYPE_WORDS.get(source_type)
    return f" ({word})" if word else ""


def _date_suffix(evidence: dict[str, Any], source_type: SourceType) -> str:
    """Say when a reference's date is missing or cannot be real.

    A *missing* date is only reported for a publication-shaped source: a
    paper with no year has a metadata defect, while a database record or
    an attached document never had a publication date to lose, and
    flagging one would invent a defect on every such row. Without both an
    author and a year the label falls back to the bare title, which is
    what an ordinary title-only entry looks like -- so on a paper the
    absence is invisible unless it is stated. An *implausible* year is
    reported whatever the source: it was stated, and it cannot be true.
    """
    state = classify_date(_row_metadata(evidence))
    if state is DateState.MISSING and source_type.is_publication:
        return " (no date)"
    if state is DateState.IMPLAUSIBLE:
        return " (date not verifiable)"
    return ""


def _render_reference_entry(evidence: dict[str, Any]) -> str:
    """Render one '- label' bullet, linked when the row has a URL."""
    source_type = _row_source_type(evidence)
    label = (
        _reference_label(evidence)
        + _identifier_suffix(evidence)
        + _source_type_suffix(source_type)
        + _date_suffix(evidence, source_type)
        + _retracted_suffix(evidence)
    )
    url = str(evidence.get("url") or "")
    text = f"[{label}]({url})" if url else label
    return f"- {text}"


def _render_references_section(evidence: list[dict[str, Any]]) -> list[str]:
    """Render the run-wide 'References' section, or nothing when empty.

    Every evidence row the run persisted is in scope, including an
    uploaded attachment or a directly fetched corpus paper carrying no
    url/authors/year -- the run consulted it the same as a searched
    paper, so it renders (bare title, unlinked) rather than being
    silently dropped.

    Args:
        evidence: The run's full evidence rows (``store.list_evidence``).

    Returns:
        Markdown lines for the section, or ``[]`` when the run retrieved
        nothing -- omitting the heading along with the body, matching
        this renderer's own convention (R14-23) rather than the
        published corpus's always-print-the-heading one.
    """
    deduped = _dedupe_evidence(evidence)
    if not deduped:
        return []
    ordered = sorted(deduped, key=lambda row: _reference_label(row).casefold())
    lines = ["", "## References", ""]
    lines.extend(_render_reference_entry(row) for row in ordered)
    lines.append("")
    return lines
