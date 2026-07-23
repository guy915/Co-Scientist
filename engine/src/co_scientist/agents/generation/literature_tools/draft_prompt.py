"""Draft-prompt assembly for Phase 1 of tool-based generation.

Gathers the workflow-state context the draft agent needs and assembles the
Phase 1 draft prompt from it. The draft LLM call itself stays in draft.py so
its call_llm_with_tools seam remains monkeypatchable on that namespace.
"""

import logging
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from co_scientist.constants import corpus_slug
from co_scientist.prompts import (
    DraftPromptRequest,
    PromptRunContext,
    get_draft_prompt_with_tools,
)
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry

logger = logging.getLogger(__name__)


def _log_lit_review_context(
    articles_with_reasoning: str | None, articles: list[Any]
) -> None:
    """Log whether warm-started literature-review context is available.

    Args:
        articles_with_reasoning: lit review summary text, if any.
        articles: articles already fetched by the literature review (used to
            report the warm-start paper count).
    """
    if articles_with_reasoning:
        logger.info("Including lit review summary as context for drafting")
        logger.info(
            "Warm start: corpus already populated with %s papers"
            " from literature review",
            len(articles),
        )
    else:
        logger.warning(
            "No lit review summary available"
            " - agent will examine papers directly"
        )


class _DraftStateContext(NamedTuple):
    """Workflow-state values needed to assemble the Phase 1 draft prompt."""

    research_goal: str
    supervisor_guidance: dict[str, Any]
    meta_review: Any
    articles_with_reasoning: str | None
    preferences: Any
    attributes: Any
    user_hypotheses: Any
    articles: list[Any]
    run_setup_guidance: Any
    run_focus_guidance: Any


def _gather_draft_state_context(state: WorkflowState) -> _DraftStateContext:
    """Extract and log the workflow-state values the draft prompt needs.

    Also logs the shared corpus slug (reused by the validation phase for
    warm-start) and the lit-review-context diagnostics.

    Args:
        state: Current workflow state.

    Returns:
        The bundled state values the draft prompt is built from.
    """
    articles_with_reasoning = state.get("articles_with_reasoning")
    articles = state.get("articles") or []

    # Shared slug for corpus (reuse lit review slug for warm start); the
    # validation phase derives the same slug from the research goal.
    shared_slug = corpus_slug(state["research_goal"])
    logger.info("Using shared corpus slug: %s", shared_slug)

    _log_lit_review_context(articles_with_reasoning, articles)

    return _DraftStateContext(
        research_goal=state["research_goal"],
        supervisor_guidance=state.get("supervisor_guidance", {}),
        meta_review=state.get("meta_review"),
        articles_with_reasoning=articles_with_reasoning,
        preferences=state.get("preferences"),
        attributes=state.get("attributes"),
        user_hypotheses=state.get("starting_hypotheses"),
        articles=articles,
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )


def _invoke_draft_prompt_builder(
    count: int,
    max_iterations: int,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
    ctx: _DraftStateContext,
) -> str:
    """Call the draft prompt template with the gathered state context.

    Args:
        count: Number of hypotheses to draft.
        max_iterations: Iteration budget for this draft call.
        tool_registry: Resolved ToolRegistry for tool selection.
        reference_index: Optional `[C*]` citation reference index.
        ctx: State values from _gather_draft_state_context.

    Returns:
        The assembled draft prompt text.
    """
    ref_text = reference_index.text if reference_index else ""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal=ctx.research_goal,
            hypotheses_count=count,
            articles=ctx.articles,
            articles_with_reasoning=ctx.articles_with_reasoning,
            preferences=ctx.preferences,
            attributes=ctx.attributes,
            user_hypotheses=ctx.user_hypotheses,
            max_iterations=max_iterations,
            reference_list=ref_text,
            context=PromptRunContext(
                supervisor_guidance=ctx.supervisor_guidance,
                meta_review=ctx.meta_review,
                tool_registry=tool_registry,
                run_setup_guidance=ctx.run_setup_guidance,
                run_focus_guidance=ctx.run_focus_guidance,
            ),
        )
    )

    return prompt


def _build_draft_prompt(
    state: WorkflowState,
    count: int,
    max_iterations: int,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> str:
    """Assemble the Phase 1 draft prompt from workflow state and context.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        max_iterations: Iteration budget already computed for this draft
            call.
        tool_registry: Resolved ToolRegistry for config-driven tool
            selection.
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        The assembled draft prompt text.
    """
    ctx = _gather_draft_state_context(state)
    return _invoke_draft_prompt_builder(
        count, max_iterations, tool_registry, reference_index, ctx
    )
