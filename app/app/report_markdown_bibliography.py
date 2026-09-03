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
both markdown documents (``ReportMarkdownInputs.evidence``) and the Learning
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

Placement: the Research Overview document, not the Top Ranking Hypotheses
document. Google's own bibliography sits in
``research-overviews/mash-....md`` -- the very document type this repo's
overview document mirrors -- directly after the run's Open Questions /
Clear Patterns / Unexpected Connections span (MASH L746-818, then
References at L832; R12-10's own sink is already
``report_markdown_overview.py``). It is a run-wide list (every source the
whole run touched), not a per-idea one, so it belongs beside the other
whole-run sections (Knowledge Base, Data sources) rather than the ranking
document, which already carries its own per-hypothesis ``#### References``
subsections (R14-21) -- a second, differently-scoped ``## References``
heading there would collide with those. (R14-10's empty ``# References:``
heading on the ranking document is a different fact: it sits between that
document's ranking report and an embedded hypothesis proposal, i.e. the
per-hypothesis L1 form R14-21/R14-26 already describe, not a run-wide
list.)

Ordering: alphabetically by the same label text the entry renders
(``_reference_label(...).casefold()``), not by retrieval time or insertion
order. A reader can find an entry by its visible text, and retrieval order
depends on search timing that can differ between functionally identical
runs -- an evidence-order list would look shuffled for no reason a reader
could see.
"""

from __future__ import annotations

from typing import Any

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


def _render_reference_entry(evidence: dict[str, Any]) -> str:
    """Render one '- label' bullet, linked when the row has a URL."""
    label = (
        _reference_label(evidence)
        + _identifier_suffix(evidence)
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
