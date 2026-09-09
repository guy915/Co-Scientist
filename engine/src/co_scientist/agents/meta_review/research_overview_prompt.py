"""Prompt/schema builders for both research-overview firings (FIX-6).

Split from ``research_overview.py`` at its 500-line cap. Owns turning run
state into the ``(prompt, schema)`` pair each firing calls the LLM with --
the terminal document's ten-section ask and the periodic firing's lean
two-field one (``RESEARCH_OVERVIEW_INTERIM_SCHEMA``) -- so the node itself
only orchestrates the call and the result.
"""

from typing import Any

from co_scientist.agents.meta_review.research_overview_contacts import (
    _format_contact_candidates,
)
from co_scientist.agents.meta_review.research_overview_evidence import (
    _format_evidence_corpus,
)
from co_scientist.prompts import (
    PromptRunContext,
    get_research_overview_interim_prompt,
    get_research_overview_prompt,
)
from co_scientist.state import WorkflowState


def _run_prompt_context(state: WorkflowState) -> PromptRunContext:
    """Run-scoped guidance both firings' prompts read the same way."""
    return PromptRunContext(
        meta_review=state.get("meta_review"),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )


def build_synthesis_prompt(
    state: WorkflowState,
    summary: str,
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """Builds the terminal research-overview synthesis prompt and schema.

    Uses the supervisor model (strategic synthesis, not a worker task);
    meta_review and the durable run guidance steer it toward the same
    strategic themes used elsewhere in the workflow.
    """
    return get_research_overview_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        contact_candidates=_format_contact_candidates(contact_candidates),
        evidence_corpus=_format_evidence_corpus(evidence_corpus),
        context=_run_prompt_context(state),
    )


def build_interim_synthesis_prompt(
    state: WorkflowState,
    summary: str,
    evidence_corpus: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """Builds a periodic firing's own lean prompt and schema.

    No ``contact_candidates``: an interim firing's schema never asks for
    ``research_contacts``, so there is nothing here for that formatted
    block to feed.
    """
    return get_research_overview_interim_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        evidence_corpus=_format_evidence_corpus(evidence_corpus),
        context=_run_prompt_context(state),
    )
