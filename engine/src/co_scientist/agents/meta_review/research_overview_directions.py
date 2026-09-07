"""Defensive formatting for the overview's research-direction sub-topics.

``overview.research_directions`` itself passes from the raw LLM response
straight through to the report: ``title``/``importance``/
``suggested_experiments`` have always relied on ``report_markdown_overview``'s
readable-text flattening for defense, not engine-side validation, and that
convention is left alone here. The two fields this restores (MO-1's nested
``sub_topics`` layer, MO-12's ``recent_findings``) get the same defensive
treatment ``research_overview_contacts.py`` already applies to a missing
field (``raw.get(...) or ""``), plus a defensive slice: json_object mode
does not enforce the schema's ``maxItems`` server-side, so a
non-conforming response is capped here rather than trusted -- the same
reason ``_validate_knowledge_base`` slices to its own max.
"""

from typing import Any

from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_MAX_DIRECTIONS,
    RESEARCH_OVERVIEW_MAX_SUB_TOPIC_QUESTIONS,
    RESEARCH_OVERVIEW_MAX_SUB_TOPICS,
)


def _validate_specific_questions(raw_questions: Any) -> list[Any]:
    """Cap a sub-topic's questions, or default to empty when malformed."""
    if not isinstance(raw_questions, list):
        return []
    return raw_questions[:RESEARCH_OVERVIEW_MAX_SUB_TOPIC_QUESTIONS]


def _validate_sub_topic(raw: Any) -> dict[str, Any] | None:
    """Format one sub-topic, or None when raw is not even a dict."""
    if not isinstance(raw, dict):
        return None
    return {
        "title": raw.get("title") or "",
        "why": raw.get("why") or "",
        "what": raw.get("what") or "",
        # F7: the exemplar's "Example idea" block, read the same
        # defensive way its why/what siblings are -- json_object mode
        # omits required fields, and an absent example must degrade to a
        # sub-topic without one, not to a raised response.
        "example_idea": raw.get("example_idea") or "",
        "specific_questions": _validate_specific_questions(
            raw.get("specific_questions")
        ),
    }


def _validate_sub_topics(raw_sub_topics: Any) -> list[dict[str, Any]]:
    """Cap and format a direction's sub-topics, dropping malformed entries."""
    if not isinstance(raw_sub_topics, list):
        return []
    sliced = raw_sub_topics[:RESEARCH_OVERVIEW_MAX_SUB_TOPICS]
    formatted = (_validate_sub_topic(raw) for raw in sliced)
    return [sub_topic for sub_topic in formatted if sub_topic is not None]


def _validate_research_direction(raw: Any) -> Any:
    """Add MO-1/MO-12's two new fields to one direction, defensively.

    Every other field is left exactly as the model returned it -- their
    established convention is the render-layer's own flattening, not
    validation here. A non-dict direction is returned unchanged so the
    existing pass-through fields still see whatever malformed shape they
    always tolerated.
    """
    if not isinstance(raw, dict):
        return raw
    return {
        **raw,
        "recent_findings": raw.get("recent_findings") or "",
        "sub_topics": _validate_sub_topics(raw.get("sub_topics")),
    }


def _validate_research_directions(raw_directions: Any) -> Any:
    """Cap the directions list and add the new per-direction fields.

    F5 raised the asked-for direction count, which raises the response's
    size with it. This node's budget already sits at the escalation
    ladder's own ceiling, so an over-producing response is sliced here
    rather than trusted -- the same reason the sub-topic layer above is,
    and for the same reason: json_object mode does not enforce the
    schema's ``maxItems`` server-side.
    """
    if not isinstance(raw_directions, list):
        return raw_directions
    sliced = raw_directions[:RESEARCH_OVERVIEW_MAX_DIRECTIONS]
    return [_validate_research_direction(raw) for raw in sliced]


def format_overview(raw_overview: Any) -> Any:
    """Format the raw ``overview`` sub-object for the report.

    Only touches ``research_directions``, and only when the model
    actually returned that key -- everything else (a missing/malformed
    ``overview`` entirely, ``summary``, and every existing per-direction
    field) passes through exactly as before this module existed.

    Args:
        raw_overview: The response's raw ``overview`` value, any shape.

    Returns:
        The same value, with ``research_directions`` (if present) run
        through ``_validate_research_directions``.
    """
    has_directions = (
        isinstance(raw_overview, dict) and "research_directions" in raw_overview
    )
    if not has_directions:
        return raw_overview
    return {
        **raw_overview,
        "research_directions": _validate_research_directions(
            raw_overview["research_directions"]
        ),
    }
