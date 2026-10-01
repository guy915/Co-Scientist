"""Report section resolving a hypothesis's [C*] citation keys to References.

The generation prompt (``prompts/generation_debate.py``) instructs the model
to cite ``[C1]``/``[C2]``/... keys inline in ``literature_grounding``
(rendered as the hypothesis's Mechanism), keyed against a per-hypothesis
reference index the engine builds
(``co_scientist.agents.generation.citations.ReferenceIndex``) and resolves
onto each hypothesis's own ``citation_map``
(``citations.resolve_citation_keys``). The drain
(``engine_adapter/drain/citations.py``) already persists that map into the
``citations``/``evidence`` tables -- one row per key, joined to the cited
source's title/url/authors/year -- but nothing read it back out, so the
report printed bare ``[C1]`` markers with nothing to resolve them against.

A citation row carries its key as a fixed prefix on its ``claim`` column
(``"[C1] cited in hypothesis"``), rather than a dedicated column --
written by ``drain.citations._persist_one_citation`` and pinned by two
literal assertions in ``test_engine_drain_citations.py``, so a format change
there breaks loudly rather than silently starving this parse. That claim
text is filler for the NOT NULL column, never meant for a reader, so it
must never leak into the rendered line itself.
"""

from __future__ import annotations

import re
from typing import Any

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
    """Group a run's citation rows into per-hypothesis (key, evidence) lists.

    A row this function cannot positively resolve -- an unparseable claim
    prefix, or an evidence_id with no matching row -- is dropped rather than
    printed as a broken or guessed-at entry: a reader must never see a
    citation that resolves to nothing, or a fabricated one.

    Args:
        citations: A run's citation rows (``store.list_citations``).
        evidence: The same run's evidence rows (``store.list_evidence``).

    Returns:
        hypothesis_id -> its resolvable (key, evidence row) pairs, ordered
        by the key's numeric suffix.
    """
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
