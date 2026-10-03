"""Resolve hypothesis citations and render the run bibliography."""

from __future__ import annotations

import re
from typing import Any

from app.citations.metadata import (
    CitationMetadata,
    DateState,
    SourceType,
    classify_date,
    classify_source_type,
)

# Matches the fixed prefix _persist_one_citation writes: "[C1] cited in
# hypothesis". Anchored so a citation row from a different, unrelated
# concern (e.g. a hand-seeded demo citation whose claim is the hypothesis
# statement itself) is recognized as unresolvable rather than mismatched.
_CLAIM_KEY_PREFIX = re.compile(r"^\[(C\d+)\]")

# Matches a trailing "et al."/"et al" credit some curated author fields
# write inline (e.g. "Kim et al.") rather than as a separate authors list
# -- stripped before resolving a first-author surname, or the literal
# "al." reads as the surname.
_ET_AL_SUFFIX = re.compile(r"\s+et\s+al\.?\s*$", re.IGNORECASE)


def _citation_key(claim: str) -> str | None:
    """Extract a citation row's [C*] key from its fixed-format claim prefix.

    Returns None when the claim does not carry a recognizable key -- a row
    from before this drain format, or from a different producer entirely.
    """
    match = _CLAIM_KEY_PREFIX.match(claim)
    return match.group(1) if match else None


def _reference_label(evidence: dict[str, Any]) -> str:
    """Build a reference's display label from its evidence row.

    Mirrors the engine's own short citation label (author/year, or the
    title alone for a source with no authors -- e.g. a knowledge-graph
    statement, whose "title" already carries its full display text; see
    ``drain.citations._ensure_citation_evidence_id``).
    """
    title = str(evidence.get("title") or "").strip()
    authors = evidence.get("authors") or []
    year = evidence.get("year")
    # A curated author credit is sometimes written "Kim et al." rather
    # than a bare surname -- strip that suffix before taking the last
    # word, or the literal "al." resolves as the surname.
    first_author_text = (
        _ET_AL_SUFFIX.sub("", str(authors[0]).strip()) if authors else ""
    )
    first_author = first_author_text.split()[-1] if first_author_text else ""
    if first_author and year:
        prefix = f"{first_author} et al., {year}"
        return f"{prefix} — {title}" if title else prefix
    return title or "Untitled source"


def _render_reference_line(key: str, evidence: dict[str, Any]) -> str:
    """Render one '- **[Ck]** label' line, linked when the source has a URL."""
    label = _reference_label(evidence)
    url = str(evidence.get("url") or "")
    text = f"[{label}]({url})" if url else label
    return f"- **[{key}]** {text}"


def references_by_hypothesis(
    citations: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Group a run's citation rows into per-hypothesis (key, evidence) lists."""
    evidence_by_id = {str(row.get("id")): row for row in evidence}
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for citation in citations:
        key = _citation_key(str(citation.get("claim") or ""))
        source = evidence_by_id.get(str(citation.get("evidence_id") or ""))
        if key is None or source is None:
            continue
        hyp_id = str(citation.get("hypothesis_id") or "")
        grouped.setdefault(hyp_id, []).append((key, source))
    for entries in grouped.values():
        entries.sort(key=lambda pair: int(pair[0][1:]))
    return grouped


def _render_references_markdown(
    entries: list[tuple[str, dict[str, Any]]],
) -> list[str]:
    """Render one hypothesis's 'References' subsection, or nothing when empty.

    Repo convention (unlike the published corpus, which always prints the
    heading): omit the heading along with the body when there is nothing to
    list, rather than showing an empty "References" section.
    """
    if not entries:
        return []
    lines = ["#### References", ""]
    lines.extend(_render_reference_line(key, source) for key, source in entries)
    lines.append("")
    return lines


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
    """Say when a reference's date is missing or cannot be real."""
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
    """Render the run-wide 'References' section, or nothing when empty."""
    deduped = _dedupe_evidence(evidence)
    if not deduped:
        return []
    ordered = sorted(deduped, key=lambda row: _reference_label(row).casefold())
    lines = ["", "## References", ""]
    lines.extend(_render_reference_entry(row) for row in ordered)
    lines.append("")
    return lines
