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

_MAX_RESEARCH_CONTACT_GROUPS: Final = 5
"""Groups kept from the model's response (R14-6) -- bounded like the
contacts themselves, since there cannot usefully be more groups than
there are contacts to put in them."""

_MAX_GROUP_EXAMPLE_HYPOTHESES: Final = 2
"""Example hypotheses kept per group, matching the published exemplar's
two "Example Hypothesis Titles" per research direction (R14-6)."""


def _build_contact_candidates(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build a bounded expert pool exclusively from retrieved-paper authors."""
    candidates: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()
    for article_index, article in enumerate(articles or []):
        if not article.used_in_analysis:
            continue
        for author_index, raw_name in enumerate(article.authors or []):
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


def _resolve_example_hypothesis_ids(
    raw_indices: Any, hypothesis_by_index: dict[int, str]
) -> list[str]:
    """Resolve a group's example-hypothesis indices to real hypothesis ids.

    R14-6: the model refers to a hypothesis by the same 1-based position
    used in the numbered top-k summary it was shown, never by echoing
    the hypothesis's own text -- a schema that echoes input scales
    output with the pool and truncates identically on every retry (see
    AGENTS.md). An index outside the pool, a non-integer entry, or a
    repeat is dropped rather than guessed at; the caller renders titles
    from the resolved ids, never from anything the model wrote itself.
    """
    if not isinstance(raw_indices, list):
        return []
    ids: list[str] = []
    for raw in itertools.islice(raw_indices, _MAX_GROUP_EXAMPLE_HYPOTHESES):
        hyp_id = hypothesis_by_index.get(raw) if isinstance(raw, int) else None
        if hyp_id is not None and hyp_id not in ids:
            ids.append(hyp_id)
    return ids


def _validate_research_contact_group(
    raw: Any, hypothesis_by_index: dict[int, str]
) -> dict[str, Any] | None:
    """Validate one research-contact group, or None when unnamed."""
    if not isinstance(raw, dict):
        return None
    direction = str(raw.get("research_direction") or "").strip()
    if not direction:
        return None
    return {
        "research_direction": direction,
        "rationale": str(raw.get("rationale") or "").strip(),
        "example_hypothesis_ids": _resolve_example_hypothesis_ids(
            raw.get("example_hypothesis_indices"), hypothesis_by_index
        ),
    }


def _validate_research_contact_groups(
    raw_groups: Any, hypothesis_by_index: dict[int, str]
) -> list[dict[str, Any]]:
    """Keep only well-formed groups, capped and stripped of raw indices.

    Unlike ``_validate_research_contacts``, a group's ``research_direction``
    is not checked against a verified pool -- it is free text the model
    is asked to copy from its own ``research_contacts`` response (MO-7's
    comment on that field: a direction label is not an invented fact the
    way a name or affiliation would be). The renderer matches a group to
    its contacts by that text, so a group whose text does not match any
    contact simply renders no contacts under it.
    """
    if not isinstance(raw_groups, list):
        return []
    validated = (
        _validate_research_contact_group(raw, hypothesis_by_index)
        for raw in raw_groups
    )
    return list(
        itertools.islice(
            (group for group in validated if group is not None),
            _MAX_RESEARCH_CONTACT_GROUPS,
        )
    )
