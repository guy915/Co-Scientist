"""Format and develop the overview research directions with bounded calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.meta_review.research_overview_evidence import (
    prompt_context,
)
from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    scoped_telemetry_phase,
)
from co_scientist.prompts import (
    DirectionWritingMaterial,
    get_research_overview_direction_prompt,
)
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_MAX_DIRECTIONS,
    RESEARCH_OVERVIEW_MAX_SUB_TOPIC_QUESTIONS,
    RESEARCH_OVERVIEW_MAX_SUB_TOPICS,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


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


JsonCall = Callable[..., Awaitable[dict[str, Any]]]

"""The node's own ``call_llm_json`` seam, handed in rather than imported.

The research-overview node dispatches a draft, an accuracy review and
this wave. Routing them through one seam means a caller that stubs the
node's provider access stubs the whole node, with no second path able to
reach a provider that caller thought it had replaced.
"""


_BODY_FIELDS = (
    "importance",
    "recent_findings",
    "suggested_experiments",
    "sub_topics",
)

"""The fields a writing call may contribute to its direction.

Named rather than derived from the response: an undeclared key must not
reach the report through this merge, and ``title`` must never be
overwritten -- the overview's contacts and contact groups cross-reference
a direction by the title the draft gave it.
"""


@dataclass(frozen=True)
class DirectionWaveContext:
    """The run material every direction's writing call is given.

    Bundled so the wave's own functions stay inside the parameter limit,
    and so the six calls provably share one corpus rather than each
    building its own.

    Attributes:
        state: The workflow state at the terminal synthesis node.
        hypotheses_summary: The numbered top-k summary.
        evidence_corpus_text: The pre-formatted evidence corpus.
    """

    state: WorkflowState
    hypotheses_summary: str
    evidence_corpus_text: str


def _needs_writing(direction: Any) -> bool:
    """Whether this direction still has to be bought a writing call.

    Every body field must be there for the call to be skipped, not just
    one of them. A draft that answers a single placeholder sub-topic --
    which a schema-enforcing provider makes it do, since the fields are
    required whatever the prompt asks -- has not developed the direction,
    and reading that as "already written" publishes it shallow.
    """
    if not isinstance(direction, dict):
        return False
    return not all(direction.get(field) for field in _BODY_FIELDS)


def format_direction_titles(directions: list[Any]) -> str:
    """Render every drafted direction's title for the overlap check."""
    return "\n".join(
        f"- {str(direction.get('title') or '').strip()}"
        for direction in directions
        if isinstance(direction, dict)
    )


def _material(
    direction: dict[str, Any], all_directions: str
) -> DirectionWritingMaterial:
    """Bundle one direction's own drafted content for its prompt."""
    return DirectionWritingMaterial(
        title=str(direction.get("title") or "").strip(),
        rationale=str(direction.get("importance") or "").strip(),
        all_directions=all_directions,
    )


async def write_direction_body(
    context: DirectionWaveContext,
    material: DirectionWritingMaterial,
    ask: JsonCall,
) -> dict[str, Any]:
    """Develop one drafted direction to the published exemplar's depth.

    Failures are absorbed rather than raised: the six calls run under one
    ``asyncio.gather``, where a raising sibling cancels the directions
    that were writing perfectly well beside it (the trap ``evolve``
    documents), and a direction that does not answer still publishes with
    its drafted title and argument.

    Args:
        context: The run material every writing call shares.
        material: This direction's title, argument, and the full set of
            titles it must not duplicate.
        ask: The node's JSON-call seam.

    Returns:
        The written body, or empty when this direction did not answer.
    """
    prompt, schema = get_research_overview_direction_prompt(
        research_goal=context.state["research_goal"],
        material=material,
        hypotheses_summary=context.hypotheses_summary,
        evidence_corpus=context.evidence_corpus_text,
        context=prompt_context(context.state),
    )
    try:
        with scoped_telemetry_phase("directions"):
            response = await ask(
                prompt=prompt,
                spec=CompletionSpec(
                    model_name=context.state["supervisor_model_name"],
                    max_tokens=RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS,
                    temperature=MEDIUM_TEMPERATURE,
                    json_schema=schema,
                ),
                options=LLMCallOptions(enable_thinking=False),
            )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception:
        logger.error(
            "Research direction %r was not developed; publishing its "
            "drafted title and argument alone",
            material.title,
            exc_info=True,
        )
        return {}
    return response if isinstance(response, dict) else {}


def _merged(direction: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Overlay a written body onto its drafted direction.

    Only a field the writer actually answered replaces the draft's, so a
    response degraded by the json_object downgrade -- which enforces no
    required field -- costs that field rather than the direction.
    """
    written = {
        field: body[field]
        for field in _BODY_FIELDS
        if isinstance(body, dict) and body.get(field)
    }
    return {**direction, **written}


async def develop_research_directions(
    context: DirectionWaveContext, directions: Any, ask: JsonCall
) -> tuple[Any, int]:
    """Write every drafted direction's body, concurrently.

    Args:
        context: The run material every writing call shares.
        directions: The draft's ``research_directions`` value, already
            capped at the schema bound, any shape.
        ask: The node's JSON-call seam.

    Returns:
        Tuple of (the directions with each body written in, calls spent).
        The value passes through unchanged, at zero calls, when it is not
        a list or nothing needed writing.
    """
    if not isinstance(directions, list):
        return directions, 0
    pending = [index for index, d in enumerate(directions) if _needs_writing(d)]
    if not pending:
        return directions, 0
    titles = format_direction_titles(directions)
    bodies = await asyncio.gather(
        *(
            write_direction_body(
                context, _material(directions[index], titles), ask
            )
            for index in pending
        )
    )
    written = dict(zip(pending, bodies, strict=True))
    return [
        _merged(direction, written[index]) if index in written else direction
        for index, direction in enumerate(directions)
    ], len(pending)


async def develop_directions_into(
    wave: DirectionWaveContext, formatted: dict[str, Any], ask: JsonCall
) -> int:
    """Buy each drafted direction the call that develops it.

    The draft names the directions and argues each; the exemplar's own
    depth beneath them is written one call per direction, because six at
    that depth cannot be generated inside the 600s per-call ceiling in
    one stream (``research_overview_direction_calls``). Runs on the
    formatted overview, so the schema cap has already bounded how many
    calls this can buy, and the written bodies are re-validated by the
    same ``format_overview`` that shaped the drafted ones.

    Args:
        wave: The run material every writing call shares.
        formatted: The formatted overview, updated in place.
        ask: The node's JSON-call seam.

    Returns:
        LLM calls spent, which is 0 when there was nothing to develop.
    """
    overview = formatted.get("overview")
    if not isinstance(overview, dict):
        return 0
    developed, calls = await develop_research_directions(
        wave, overview.get("research_directions"), ask
    )
    formatted["overview"] = format_overview(
        {**overview, "research_directions": developed}
    )
    return calls
