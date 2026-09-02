"""Renders research contacts, grouped by research direction (R14-6).

Google's published exemplar groups ``research_contacts`` under the
research direction that surfaced them, each group carrying one shared
"Why they are best for this direction" rationale paragraph and up to two
"Example Hypothesis Titles" -- richer than MO-7's flat per-contact
``research_direction`` tag. ``research_contact_groups`` (``schemas/
synthesis.py``) is a separate, additive array rather than a restructuring
of ``research_contacts`` itself: the model still emits flat contacts
tagged with ``research_direction``, and this module matches a group to
its contacts by that same free-text tag at render time. A contact whose
direction matches no group -- an old report, or a response that never
populated ``research_contact_groups`` -- renders exactly as MO-7's flat
shape always has, via ``_render_contact_entry``'s defaults.

Split out of ``report_markdown_overview`` to keep that module within the
size cap. Imports only the leaf ``report_markdown_text`` module, never
``report_markdown_overview`` itself, so the two never form a cross-import
cycle; ``report_markdown_overview`` re-exports this module's public names
so its own namespace keeps resolving.
"""

from __future__ import annotations

from typing import Any

from app.report_markdown_text import _readable_text


def _render_contact_evidence_line(contact: dict[str, Any]) -> list[str]:
    """Render a contact's source-evidence line, or nothing when unsourced."""
    title = _readable_text(contact.get("source_title"))
    url = contact.get("source_url")
    if not title:
        return []
    return [f"Evidence: [{title}]({url})\n" if url else f"Evidence: {title}\n"]


def _render_contact_entry(
    contact: dict[str, Any],
    *,
    heading: str = "###",
    show_direction: bool = True,
) -> list[str]:
    """Render one research-contact entry, or nothing when unnamed.

    ``heading``/``show_direction`` let a grouped rendering nest a
    contact one level under its group's own direction heading without
    repeating the direction line that heading already states; the
    defaults reproduce MO-7's original flat shape unchanged, which every
    ungrouped contact still uses.
    """
    if not isinstance(contact, dict) or not contact.get("name"):
        return []
    lines = [f"{heading} {_readable_text(contact['name'])}\n"]
    if show_direction:
        direction = _readable_text(contact.get("research_direction"))
        if direction:
            lines.append(f"**Research direction:** {direction}\n")
    lines += _render_contact_body(contact)
    lines += _render_contact_evidence_line(contact)
    return lines


def _render_contact_body(contact: dict[str, Any]) -> list[str]:
    """Render a contact's expertise and justification lines, or nothing."""
    lines: list[str] = []
    expertise = _readable_text(contact.get("expertise"))
    if expertise:
        lines.append(f"**Relevant expertise:** {expertise}\n")
    justification = _readable_text(contact.get("justification"))
    if justification:
        lines.append(f"{justification}\n")
    return lines


def _direction_key(direction: Any) -> str:
    """Normalize a research-direction tag for group/contact matching."""
    return _readable_text(direction).casefold()


def _render_group_example_titles(
    example_hypothesis_ids: Any, hypothesis_title_by_id: dict[str, str]
) -> list[str]:
    """Render a group's 'Example Hypothesis Titles' bullets, or nothing.

    Titles are looked up by id, never taken from the model's own words --
    index resolution already happened engine-side
    (``research_overview_contacts._resolve_example_hypothesis_ids``), so
    an id this run's report has no title for (an old report, or a
    caller with no title map) simply drops that entry rather than
    inventing one.
    """
    ids = (
        example_hypothesis_ids
        if isinstance(example_hypothesis_ids, list)
        else []
    )
    titles = [
        hypothesis_title_by_id[hid]
        for hid in ids
        if isinstance(hid, str) and hypothesis_title_by_id.get(hid)
    ]
    if not titles:
        return []
    return (
        ["**Example Hypothesis Titles:**\n"]
        + [f"- {title}" for title in titles]
        + [""]
    )


def _render_contact_group(
    group: dict[str, Any],
    contacts: list[dict[str, Any]],
    hypothesis_title_by_id: dict[str, str],
) -> list[str]:
    """Render one direction group: heading, rationale, examples, contacts.

    Nothing renders when the group names no direction, or no contact in
    this report actually matched it (a group the model wrote for a
    direction that has no corresponding contact tag) -- a heading with
    nothing under it is worse than omitting it.
    """
    direction = _readable_text(group.get("research_direction"))
    if not direction or not contacts:
        return []
    lines = [f"### {direction}\n"]
    rationale = _readable_text(group.get("rationale"))
    if rationale:
        lines.append(
            f"**Why they are best for this direction:** {rationale}\n"
        )
    lines += _render_group_example_titles(
        group.get("example_hypothesis_ids"), hypothesis_title_by_id
    )
    for contact in contacts:
        lines += _render_contact_entry(
            contact, heading="####", show_direction=False
        )
    return lines


def _partition_contacts_by_group(
    contacts: list[Any], group_keys: set[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Split contacts into per-group buckets and an ungrouped remainder."""
    by_key: dict[str, list[dict[str, Any]]] = {key: [] for key in group_keys}
    ungrouped: list[dict[str, Any]] = []
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        key = _direction_key(contact.get("research_direction"))
        if key and key in by_key:
            by_key[key].append(contact)
        else:
            ungrouped.append(contact)
    return by_key, ungrouped


def _render_grouped_contacts(
    contacts: list[Any],
    groups: Any,
    hypothesis_title_by_id: dict[str, str],
) -> list[str]:
    """Render every contact, grouped by direction where a group matches.

    A contact whose direction matches no group renders exactly as MO-7's
    flat shape always has, so this is purely additive: an old report, or
    a response that never populates ``research_contact_groups``, looks
    unchanged.
    """
    valid_groups = [g for g in (groups or []) if isinstance(g, dict)]
    group_keys = {
        _direction_key(g.get("research_direction")) for g in valid_groups
    }
    by_key, ungrouped = _partition_contacts_by_group(contacts, group_keys)

    lines: list[str] = []
    for group in valid_groups:
        key = _direction_key(group.get("research_direction"))
        lines += _render_contact_group(
            group, by_key.get(key, []), hypothesis_title_by_id
        )
    for contact in ungrouped:
        lines += _render_contact_entry(contact)
    return lines


def _render_research_contacts_section(
    contacts: Any,
    groups: Any = None,
    hypothesis_title_by_id: dict[str, str] | None = None,
) -> list[str]:
    """Render the 'Research Contacts' section, or nothing when empty."""
    if not isinstance(contacts, list) or not contacts:
        return []
    lines = ["\n## Research Contacts\n"]
    lines += _render_grouped_contacts(
        contacts, groups, hypothesis_title_by_id or {}
    )
    return lines
