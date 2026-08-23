"""Accuracy review/revise loop for the drafted research overview.

Split out of ``research_overview.py`` to keep that module under the
line-count ceiling; ``research_overview.py`` re-exports
``review_research_overview`` so the two modules share one namespace for
callers and tests.

The reviewer checks the drafted overview against this run's own
material -- the top hypotheses and evidence corpus it was synthesized
from -- for an unsupported claim, a contradiction, an overstated
confidence, or a citation that does not say what the prose claims. It
never grades tone, style, or length. Its accept case costs one call and
its schema never echoes the overview text back (see
``schemas.synthesis.RESEARCH_OVERVIEW_REVIEW_SCHEMA``); a rejection
carries located notes for the reviser, which regenerates the whole
overview in the same schema the initial synthesis uses.

The loop is capped at ``_MAX_OVERVIEW_REVISION_ROUNDS`` rounds so it
terminates whatever the models do: if the reviewer still objects after
the cap, the last revision publishes anyway, with no further review
call to spend on a verdict that cannot change the outcome.
"""

from dataclasses import dataclass
from typing import Any, Final

from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    RESEARCH_OVERVIEW_MAX_TOKENS,
)
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.prompts import (
    OverviewReviewMaterial,
    OverviewRevisionRequest,
    get_research_overview_review_prompt,
    get_research_overview_revise_prompt,
)
from co_scientist.state import WorkflowState

_MAX_OVERVIEW_REVISION_ROUNDS: Final = 2
"""Hard cap on reviewer/reviser rounds; the last revision always publishes."""


@dataclass(frozen=True)
class OverviewReviewContext:
    """Run material the reviewer and reviser check the draft against.

    Bundled into one object so the loop functions below stay under the
    five-parameter limit.

    Attributes:
        state: Current workflow state (supplies the supervisor model).
        research_goal: The run's research goal.
        hypotheses_summary: Formatted top-Elo hypothesis summary.
        contact_candidates_text: Formatted verified-author candidates.
        evidence_corpus_text: Formatted verified evidence corpus.
    """

    state: WorkflowState
    research_goal: str
    hypotheses_summary: str
    contact_candidates_text: str
    evidence_corpus_text: str

    @property
    def material(self) -> OverviewReviewMaterial:
        """The subset of run material both prompt builders share."""
        return OverviewReviewMaterial(
            research_goal=self.research_goal,
            hypotheses_summary=self.hypotheses_summary,
            evidence_corpus=self.evidence_corpus_text,
        )


async def review_research_overview(
    context: OverviewReviewContext, draft_response: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Runs the accuracy review/revise cycle over a drafted overview.

    Args:
        context: The run material to check the draft against.
        draft_response: The raw, pre-validation overview response from
            the initial synthesis call.

    Returns:
        Tuple of (final raw response, review metadata with ``reviewed``
        and ``rounds`` keys, total LLM calls this cycle spent).
    """
    current = draft_response
    calls = 0
    for round_index in range(_MAX_OVERVIEW_REVISION_ROUNDS):
        verdict = await _call_reviewer(context, current)
        calls += 1
        if _accepted(verdict):
            return current, _review_meta(round_index), calls
        current = await _call_reviser(
            context, current, verdict.get("notes") or []
        )
        calls += 1
    return current, _review_meta(_MAX_OVERVIEW_REVISION_ROUNDS), calls


def _review_meta(rounds: int) -> dict[str, Any]:
    """Builds the reported review metadata for a given revision count."""
    return {"reviewed": rounds > 0, "rounds": rounds}


def _accepted(verdict: dict[str, Any]) -> bool:
    """True unless the reviewer explicitly rejected the draft."""
    return bool(verdict.get("accept", True))


async def _call_supervisor(
    context: OverviewReviewContext,
    prompt: str,
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Runs one schema-constrained supervisor call for this review cycle."""
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=context.state["supervisor_model_name"],
            max_tokens=RESEARCH_OVERVIEW_MAX_TOKENS,
            temperature=MEDIUM_TEMPERATURE,
            json_schema=schema,
        ),
    )


async def _call_reviewer(
    context: OverviewReviewContext, draft_response: dict[str, Any]
) -> dict[str, Any]:
    """Calls the supervisor model for one accuracy-review verdict."""
    prompt, schema = get_research_overview_review_prompt(
        context.material, _format_overview_for_review(draft_response)
    )
    return await _call_supervisor(context, prompt, schema)


async def _call_reviser(
    context: OverviewReviewContext,
    draft_response: dict[str, Any],
    notes: list[Any],
) -> dict[str, Any]:
    """Calls the supervisor model to regenerate the overview from notes."""
    prompt, schema = get_research_overview_revise_prompt(
        OverviewRevisionRequest(
            material=context.material,
            contact_candidates=context.contact_candidates_text,
            drafted_overview=_format_overview_for_review(draft_response),
            review_notes=_format_review_notes(notes),
        )
    )
    return await _call_supervisor(context, prompt, schema)


def _format_overview_for_review(response: dict[str, Any]) -> str:
    """Renders a raw overview response as text the reviewer can read."""
    overview = response.get("overview") or {}
    aims = response.get("nih_specific_aims") or {}
    lines = [f"Summary: {overview.get('summary', '')}"]
    for index, direction in enumerate(
        overview.get("research_directions") or []
    ):
        lines.append(
            f"Direction {index + 1} - {direction.get('title', '')}: "
            f"{direction.get('importance', '')}"
        )
    lines.append(f"Aims introduction: {aims.get('introduction', '')}")
    for index, aim in enumerate(aims.get("aims") or []):
        lines.append(
            f"Aim {index + 1} - {aim.get('aim', '')}: "
            f"{aim.get('rationale', '')}"
        )
    lines.append(f"Aims impact: {aims.get('impact', '')}")
    lines.extend(_format_knowledge_base_for_review(response))
    return "\n".join(lines)


def _format_knowledge_base_for_review(response: dict[str, Any]) -> list[str]:
    """Renders the drafted knowledge-base topics for the reviewer."""
    lines = []
    for topic in response.get("knowledge_base") or []:
        evidence_ids = ", ".join(topic.get("evidence_ids") or [])
        lines.append(
            f"Knowledge-base topic '{topic.get('title', '')}' "
            f"(evidence: {evidence_ids}): {topic.get('summary', '')} "
            f"{topic.get('detail', '')}"
        )
    return lines


def _format_review_notes(notes: list[Any]) -> str:
    """Renders the reviewer's located notes for the reviser prompt."""
    lines = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        evidence_id = note.get("evidence_id")
        suffix = f" (evidence_id: {evidence_id})" if evidence_id else ""
        lines.append(
            f"- {note.get('location', '')}: {note.get('issue', '')}{suffix}"
        )
    return "\n".join(lines) if lines else "No specific notes."
