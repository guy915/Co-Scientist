"""Research-contact candidates for the terminal synthesis.

The overview names people a reader could approach, and a model asked for
names invents them. So the node never asks for a name: it offers a pool
built from the authors of papers the run actually retrieved, and keeps only
the entries that match one exactly. Split out of ``research_overview`` when
that module passed the file-size budget.
"""

import itertools
from collections.abc import Iterator
from typing import Any, Final

from co_scientist.models import Article

_MAX_CONTACT_CANDIDATES: Final = 30
"""Verified authors offered to the model as possible research contacts."""

_MAX_RESEARCH_CONTACTS: Final = 5
"""Grounded contacts kept from the model's response."""


def _build_contact_candidates(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build a bounded expert pool exclusively from retrieved-paper authors."""
    candidates: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()
    for article_index, article in enumerate(articles or []):
        if not article.used_in_analysis:
            continue
        for author_index, raw_name in enumerate(article.authors):
            name = raw_name.strip()
            normalized = name.casefold()
            if (
                not name
                or normalized in seen_names
                or len(candidates) >= _MAX_CONTACT_CANDIDATES
            ):
                continue
            candidate_id = f"author-{article_index + 1}-{author_index + 1}"
            candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "name": name,
                "source_id": article.source_id or "",
                "source_title": article.title,
                "source_url": article.url or "",
                "source": article.source,
            }
            seen_names.add(normalized)
    return candidates


def _format_or_placeholder(
    records: dict[str, dict[str, Any]], template: str, empty_message: str
) -> str:
    """Render bounded records as bullet lines, or a placeholder when empty.

    Args:
        records: Bounded records keyed by a stable id.
        template: A str.format template applied to each record's fields.
        empty_message: Returned verbatim when there are no records.

    Returns:
        Newline-joined bullet lines, or empty_message.
    """
    if not records:
        return empty_message
    return "\n".join(template.format(**record) for record in records.values())


def _format_contact_candidates(
    candidates: dict[str, dict[str, Any]],
) -> str:
    """Format the verified candidate pool for the synthesis prompt."""
    return _format_or_placeholder(
        candidates,
        (
            "- {candidate_id}: {name}; paper={source_title}; "
            "source_id={source_id}; url={source_url}"
        ),
        "No verified literature authors available.",
    )


def _valid_candidate_id(raw: Any, seen: set[str]) -> str | None:
    """Return raw's candidate id if it is an unseen, well-formed reference.

    Args:
        raw: One raw contact entry from the model response.
        seen: Candidate ids already accepted in this validation pass.

    Returns:
        The candidate id, or None if raw is malformed or already used.
    """
    if not isinstance(raw, dict):
        return None
    candidate_id = raw.get("candidate_id")
    if not isinstance(candidate_id, str) or candidate_id in seen:
        return None
    return candidate_id


def _matching_candidate(
    candidate_id: str,
    raw: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the verified candidate if raw's name matches it exactly."""
    candidate = candidates.get(candidate_id)
    if candidate is None:
        return None
    if raw.get("name") != candidate["name"]:
        return None
    return candidate


def _iter_matching_contacts(
    raw_contacts: list[Any],
    candidates: dict[str, dict[str, Any]],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (raw, candidate) for each unseen exact candidate match."""
    seen: set[str] = set()
    for raw in raw_contacts:
        candidate_id = _valid_candidate_id(raw, seen)
        if candidate_id is None:
            continue
        candidate = _matching_candidate(candidate_id, raw, candidates)
        if candidate is None:
            continue
        seen.add(candidate_id)
        yield raw, candidate


def _validate_research_contacts(
    raw_contacts: Any,
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only exact candidate matches and attach immutable provenance."""
    if not isinstance(raw_contacts, list):
        return []
    matches = itertools.islice(
        _iter_matching_contacts(raw_contacts, candidates),
        _MAX_RESEARCH_CONTACTS,
    )
    return [
        {
            **candidate,
            "expertise": str(raw.get("expertise") or "").strip(),
            "justification": str(raw.get("justification") or "").strip(),
            "research_direction": str(
                raw.get("research_direction") or ""
            ).strip(),
        }
        for raw, candidate in matches
    ]
