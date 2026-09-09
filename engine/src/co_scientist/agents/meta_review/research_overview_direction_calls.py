"""One provider call per drafted research direction.

Google's published overviews enumerate six main research directions
(cf-PICI) and five (protein assemblies), each developed to 800-1,000
words: a multi-point argument for the area, the baseline of what is
already known, concrete experiments, and named sub-topics carrying their
own reasoning, worked example and questions. Ours asked for four, and
the reason was arithmetic rather than taste -- the draft call had to
write every direction's body inside its own answer, and six at that
density is ~13.9k tokens on top of the ~9.9k the rest of the overview
costs. That is the whole 24000-token ceiling with nothing left for the
chain of thought sharing it, and 643-881s of generation at the 27-37
tokens per second this deployment measures, against a 600s per-call
bound. The clock said no, not the budget.

So the draft names the six and argues each in a paragraph, and each
direction is developed here on its own call, concurrently -- the shape
the Knowledge Base already uses
(``research_overview_knowledge_base_calls``), and the shape the
published document itself has: a "Main Research Directions" list, then
"Detailed Description of Each Main Research Direction". A failing call
costs one direction its depth, not all six theirs, and that direction's
drafted title and argument still publish.

Two rules keep the wave honest:

* The calls dispatch through the seam handed in by the node, so the
  research-overview node has one provider surface rather than two.
* A direction the draft already developed is not re-bought. The draft is
  asked to leave the body empty, but a model that ignores that and
  writes sub-topics anyway has done the work, and paying for it twice on
  a free chain capped near 100 requests per model per day is the waste
  this split exists to avoid.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.meta_review.research_overview_directions import (
    format_overview,
)
from co_scientist.agents.meta_review.research_overview_evidence import (
    prompt_context,
)
from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import CompletionSpec, LLMCallOptions
from co_scientist.llm_telemetry import scoped_telemetry_phase
from co_scientist.prompts import (
    DirectionWritingMaterial,
    get_research_overview_direction_prompt,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

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
