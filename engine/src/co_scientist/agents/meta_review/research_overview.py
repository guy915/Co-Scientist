"""Final and interim research overview synthesis with bounded degradation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

from co_scientist.agents.meta_review.research_overview_direction_calls import (
    DirectionWaveContext,
    develop_directions_into,
    format_overview,
)
from co_scientist.agents.meta_review.research_overview_evidence import (
    _build_contact_candidates,
    _format_contact_candidates,
    _format_evidence_corpus,
    _validate_research_contact_groups,
    _validate_research_contacts,
)
from co_scientist.agents.meta_review.research_overview_evidence import (
    _build_evidence_corpus as _build_evidence_corpus,
)
from co_scientist.agents.meta_review.research_overview_knowledge_base import (
    _validate_knowledge_base,
    knowledge_base_is_funded,
)
from co_scientist.agents.meta_review.research_overview_knowledge_base import (
    synthesize_knowledge_base as synthesize_knowledge_base,
)
from co_scientist.agents.meta_review.research_overview_review import (
    OverviewReviewContext as OverviewReviewContext,
)
from co_scientist.agents.meta_review.research_overview_review import (
    review_research_overview as review_research_overview,
)
from co_scientist.agents.node_degradation import (
    durable_retries_remain,
    run_or_degrade,
)
from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    PROGRESS_RESEARCH_OVERVIEW_START,
    RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS,
    RESEARCH_OVERVIEW_MAX_TOKENS,
    RESEARCH_OVERVIEW_TOP_K,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS, short_error_text
from co_scientist.llm import (
    CompletionSpec,
    call_llm_json,
)
from co_scientist.models import (
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
    rank_for_publication,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import (
    PromptRunContext,
    get_research_overview_interim_prompt,
    get_research_overview_prompt,
)
from co_scientist.safety import is_blocking_status
from co_scientist.scheduling.models import TaskType, stacked_task_values
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_INTERIM_MAX_DIRECTIONS as _MAX_DIRECTIONS,
)
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_INTERIM_MAX_QUESTIONS as _MAX_QUESTIONS,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# The node's key in ``llm.structured.validate._ENHANCEMENT_NODE_FALLBACKS``, and
# the label the report reads back as a degraded section.
_OVERVIEW_SCHEMA = "research_overview"

_LOST = (
    "publishing the report without the overview, Specific Aims, knowledge "
    "base and research contacts"
)


def is_interim_firing(state: WorkflowState) -> bool:
    """Whether this is a periodic firing rather than the terminal one.

    The scheduler's own recorded decision is what tells them apart, the
    same value the graph and the durable route table both read: SYNTHESIZE
    returns to the loop point (FIX-6), TERMINATE ends the run.

    Read from ``next_task`` alone this is wrong for the periodic branch's
    *stacked* form (``scheduling.policy.stack_companions``), where the
    primary keeps that field and the overview rides the pass's queue
    actions. A stacked firing read as terminal would buy the accuracy
    review and the knowledge-base calls, emit the run's 95% progress
    marker from the middle of a cycle, and publish a ``research_overview``
    the finished report would then carry -- so the queue actions are part
    of the question, exactly as they are for the routers.
    """
    if str(state.get("next_task") or "") == TaskType.SYNTHESIZE.value:
        return True
    actions = state.get("supervisor_queue_actions") or []
    return TaskType.SYNTHESIZE.value in stacked_task_values(actions)


async def synthesize_or_degrade(
    state: WorkflowState,
    synthesize: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run the overview synthesis, degrading it if the provider fails.

    Args:
        state: The node's workflow state.
        synthesize: The node's own synthesis, called once.

    Returns:
        The synthesis result, or the empty overview the report renders
        without.
    """
    if is_interim_firing(state):
        return await _interim_or_degrade(state, synthesize)
    return await run_or_degrade(
        state,
        synthesize,
        schema_name=_OVERVIEW_SCHEMA,
        fallback=_degraded_overview_result,
        lost=_LOST,
    )


async def _interim_or_degrade(
    state: WorkflowState,
    synthesize: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Draft the interim overview, or leave the next cycle without one.

    Deliberately records no degradation: ``degraded_nodes`` names a blank
    section of the finished report, and this firing writes no document --
    the terminal firing still can, so labelling the section here would
    mark an overview that came out fine.

    It shares the task's retry budget with the terminal firing, so it
    spends it the same way (``node_degradation.durable_retries_remain``):
    a retry declined here is one the run does not get back.
    """
    try:
        return await synthesize()
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:
        if durable_retries_remain(state):
            raise
        logger.error(
            "Interim research overview could not reach the provider (%s); "
            "the next generate cycle runs without one",
            short_error_text(exc),
        )
        return {}


def _degraded_overview_result() -> dict[str, Any]:
    """The state delta a failed terminal synthesis publishes instead.

    The same empty ``research_overview`` the node already returns when the
    publication gates withhold every hypothesis, so the report renderer
    needs no new branch. No metrics delta: the requests that failed were
    already counted by ``llm.admission.call_budget.record_provider_request``,
    and this produced no overview to attribute a successful call to.
    """
    return {
        "research_overview": {},
        "messages": phase_message(
            "research_overview",
            "Research overview synthesis could not reach the provider; "
            "the report is published without it",
        ),
    }


# The two caps above are the single source both ends of the edge read:
# an interim firing's own schema (RESEARCH_OVERVIEW_INTERIM_SCHEMA) bounds
# the ask to exactly what this module renders, so the model is never
# asked to write a title or question this block then discards.

_HEADER: Final = (
    "## Interim research overview (this run's own synthesis so far)\n\n"
    "The system synthesized the ideas produced so far into the directions"
    " and open questions below. Push into what they leave open: prefer a"
    " mechanism, model system or intervention these do not already cover,"
    " and do not re-derive a direction already named here.\n"
)


def build_interim_overview(response: dict[str, Any]) -> str:
    """Render a drafted overview response as the block generation reads.

    Args:
        response: The raw research-overview synthesis response.

    Returns:
        The formatted block, or an empty string when the response carries
        neither a direction nor an open question.
    """
    overview = response.get("overview")
    directions = (
        overview.get("research_directions")
        if isinstance(overview, dict)
        else None
    )
    lines = _titled_lines(directions, "Directions", _MAX_DIRECTIONS)
    lines += _question_lines(response.get("open_questions"))
    return f"{_HEADER}\n" + "\n".join(lines) + "\n" if lines else ""


def _titled_lines(raw: Any, header: str, limit: int) -> list[str]:
    """Render up to ``limit`` titled entries as one bulleted block."""
    if not isinstance(raw, list):
        return []
    bullets = [
        f"- {str(item.get('title') or '').strip()}"
        for item in raw[:limit]
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    return [f"**{header}:**", *bullets, ""] if bullets else []


def _question_lines(raw: Any) -> list[str]:
    """Render up to ``_MAX_QUESTIONS`` open questions as a bulleted block."""
    if not isinstance(raw, list):
        return []
    bullets = [
        f"- {str(item).strip()}"
        for item in raw[:_MAX_QUESTIONS]
        if str(item).strip()
    ]
    return ["**Open questions:**", *bullets, ""] if bullets else []


def format_interim_overview(state: WorkflowState) -> str:
    """Return the interim overview block, or "" before the first firing.

    Args:
        state: The workflow state the generate node was entered with.

    Returns:
        The block written by the most recent periodic firing, or an empty
        string when this run has not had one.
    """
    return str(state.get("interim_overview") or "").strip()


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


# Bounds on what the terminal synthesis prompt offers the model and accepts
# back. The offered pools are capped so a large run's article set cannot grow
# the prompt without limit; the acceptance caps bound the sections a reader is
# handed.
_UNREVIEWED_OVERVIEW: Final = {"reviewed": False, "rounds": 0}

"""Stamped on ``overview_review`` when this run did not fund a review, or
the review loop failed and the drafted overview published unchanged.
"""


async def _emit_and_synthesize_overview(
    state: WorkflowState,
    summary: str,
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
    hypothesis_by_index: dict[int, str],
) -> dict[str, Any]:
    """Runs interim or full overview synthesis with its progress emissions.

    Before the progress emission: those percentages describe the run's
    terminal synthesis, and a mid-run firing announcing 95% would drive
    the reader's progress bar to the end and back again.
    """
    if _is_interim_firing(state):
        return await _interim_overview_result(state, summary, evidence_corpus)

    await emit_progress(
        state,
        "research_overview_start",
        "Synthesizing research overview...",
        PROGRESS_RESEARCH_OVERVIEW_START,
    )

    research_overview, llm_calls = await _synthesize_research_overview(
        state, summary, contact_candidates, evidence_corpus, hypothesis_by_index
    )

    await emit_progress(
        state,
        "research_overview_complete",
        "Research overview ready",
        PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    )
    logger.info("Research overview complete")
    return _build_research_overview_result(research_overview, llm_calls)


async def research_overview_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesize the top-k hypotheses into an overview + NIH Specific Aims.

    Only hypotheses the publication gates release are offered to the model:
    the pool is filtered before the LLM call, because prose synthesized
    from a blocked idea cannot be unlabeled afterwards.

    Args:
        state: The current workflow state.

    Returns:
        A state delta carrying the research overview, metrics, and a message.
    """
    hypotheses = state.get("hypotheses", [])
    publishable = _publishable_hypotheses(hypotheses)
    if not publishable:
        # Nothing survived to this terminal node (e.g. an earlier failure
        # or all hypotheses were pruned), or the publication gates
        # withheld every remaining hypothesis; skip the LLM call rather
        # than synthesizing an overview from an empty or excluded pool.
        if hypotheses:
            logger.warning(
                "Research overview skipped: publication gates withheld all "
                "%d hypotheses; nothing to synthesize",
                len(hypotheses),
            )
        return {"research_overview": {}}

    articles = state.get("articles")
    summary, hypothesis_by_index = _summarize_top_hypotheses(publishable)
    contact_candidates = _build_contact_candidates(articles)
    evidence_corpus = _build_evidence_corpus(articles)

    # A provider that cannot be reached at this terminal node used to
    # take the whole run's output with it: the task spent its durable
    # attempts, the run settled `failed`, and `engine.finalize` -- only
    # ever enqueued as this node's `None` successor -- never existed, so
    # nothing wrote the report the other 146 tasks had earned.
    return await synthesize_or_degrade(
        state,
        lambda: _emit_and_synthesize_overview(
            state,
            summary,
            contact_candidates,
            evidence_corpus,
            hypothesis_by_index,
        ),
    )


async def _interim_overview_result(
    state: WorkflowState,
    summary: str,
    evidence_corpus: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Draft an overview for the next generate cycle, and publish nothing.

    One call, on its own lean schema: neither the accuracy-review loop
    nor the deep knowledge-base synthesis is bought here, and unlike the
    terminal call this one is never asked for the NIH Specific Aims page,
    the contacts, or the knowledge base either -- only the direction
    titles and open questions ``build_interim_overview`` renders.
    ``research_overview`` stays untouched so the live UI and the
    finished report keep reading the terminal firing's own output.
    """
    prompt, schema = build_interim_synthesis_prompt(
        state, summary, evidence_corpus
    )
    response = await _call_research_overview_llm(
        state, prompt, schema, max_tokens=RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS
    )
    logger.info("Interim research overview ready for the next cycle")
    return {
        "interim_overview": build_interim_overview(response),
        "metrics": create_metrics_update(deltas=MetricDeltas(llm_calls=1)),
        "messages": phase_message(
            "research_overview",
            "Synthesized an interim research overview",
        ),
    }


def _publishable_hypotheses(
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Filter to the hypotheses the final report would publish.

    Mirrors the report's exclusions on engine-side state: the tournament's
    rankability test (``Hypothesis.is_rankable``) plus the blocking safety
    outcomes. Ideas needing revision publish, as do undermined ones
    (demoted, not withheld); duplicates are pruned upstream.

    Args:
        hypotheses: The hypothesis pool at the terminal node.

    Returns:
        The publishable hypotheses, in pool order.
    """
    return [
        h
        for h in hypotheses
        if h.is_rankable() and not is_blocking_status(h.safety_status)
    ]


def _summarize_top_hypotheses(
    hypotheses: list[Hypothesis],
) -> tuple[str, dict[int, str]]:
    """Ranks hypotheses for publication and formats the top-k summary.

    Re-ranks defensively (does not assume the incoming list is already
    sorted) and keeps only the strongest ``RESEARCH_OVERVIEW_TOP_K``
    hypotheses so the synthesis prompt stays a bounded size.
    ``rank_for_publication``, not plain Elo: an undermined idea publishes
    but must not headline the synthesis, and its Elo -- won before the
    verdict doubting it -- is what would put it there.

    Args:
        hypotheses: The publishable hypothesis pool.

    Returns:
        A tuple of (newline-joined, numbered summary of the top-k
        hypotheses; a 1-based index -> hypothesis id map, the same
        numbering the summary text uses, for resolving a research-
        contact-group's ``example_hypothesis_indices`` (R14-6) back to a
        real hypothesis without letting the model echo invented text).
    """
    ranked = rank_for_publication(hypotheses)
    top = ranked[:RESEARCH_OVERVIEW_TOP_K]
    summary = "\n".join(
        f"{i + 1}. (Elo {h.elo_rating}) {h.text}" for i, h in enumerate(top)
    )
    hypothesis_by_index = {i + 1: h.id for i, h in enumerate(top)}
    return summary, hypothesis_by_index


async def _synthesize_research_overview(
    state: WorkflowState,
    summary: str,
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
    hypothesis_by_index: dict[int, str],
) -> tuple[dict[str, Any], int]:
    """Builds the research-overview prompt, calls the LLM, and formats it.

    When this run funds it, the raw response is checked for
    scientific accuracy against its own material before validation
    formats it -- a revision replaces the whole raw response, so
    grounding validation must run once, last, on whatever the review
    loop settles on.

    Args:
        state: Current workflow state.
        summary: Top-k hypotheses summary from _summarize_top_hypotheses.
        contact_candidates: Verified authors keyed by a stable candidate id.
        evidence_corpus: Analyzed sources keyed by a stable evidence id.
        hypothesis_by_index: Same 1-based numbering as ``summary``, for
            resolving research-contact-group example hypotheses.

    Returns:
        Tuple of (the formatted research_overview dict, LLM calls spent).
        "overview" and "nih_specific_aims" default to empty so consumers
        always see a well-formed research_overview shape.
    """
    prompt, schema = build_synthesis_prompt(
        state, summary, contact_candidates, evidence_corpus
    )
    response = await _call_research_overview_llm(state, prompt, schema)
    response, review_meta, review_calls = await _maybe_review_overview(
        state, summary, contact_candidates, evidence_corpus, response
    )
    formatted = _format_research_overview_response(
        response, contact_candidates, evidence_corpus, hypothesis_by_index
    )
    formatted["overview_review"] = review_meta
    wave = DirectionWaveContext(
        state=state,
        hypotheses_summary=summary,
        evidence_corpus_text=_format_evidence_corpus(evidence_corpus),
    )
    direction_calls = await develop_directions_into(
        wave, formatted, call_llm_json
    )
    deep_calls = await _deepen_knowledge_base(
        state, summary, evidence_corpus, formatted
    )
    return formatted, 1 + review_calls + direction_calls + deep_calls


async def _deepen_knowledge_base(
    state: WorkflowState,
    summary: str,
    evidence_corpus: dict[str, dict[str, Any]],
    formatted: dict[str, Any],
) -> int:
    """Replace the flat knowledge base with the deep synthesis (F8).

    Only where the run's declared ceiling funds the extra call, and only
    when it comes back with grounded sections: the overview call's own
    topics are already in ``formatted`` and stand wherever this does not.

    Returns:
        LLM calls spent, which is 0 wherever the call was not made.
    """
    if not knowledge_base_is_funded(state):
        return 0
    topics, calls = await synthesize_knowledge_base(
        state,
        summary,
        evidence_corpus,
        evidence_corpus_text=_format_evidence_corpus(evidence_corpus),
    )
    if topics:
        formatted["knowledge_base"] = topics
    return calls


async def _maybe_review_overview(
    state: WorkflowState,
    summary: str,
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
    response: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Runs the accuracy review/revise cycle when this run funds it.

    Skipped entirely where the run never requested it (the fast tiers,
    and the offline backend regardless of request -- both settled
    upstream in run_setup, so this only reads the resolved flag).
    Degrades to the original draft on any failure: a report that fails
    to publish is worse than one carrying a noted weakness, the same
    principle ``_validate_knowledge_base`` follows for a malformed
    citation.

    Returns:
        Tuple of (final raw response, review metadata, LLM calls spent
        reviewing -- 0 when skipped or degraded).
    """
    if not state.get("enable_overview_review"):
        return response, dict(_UNREVIEWED_OVERVIEW), 0
    context = OverviewReviewContext(
        state=state,
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        contact_candidates_text=_format_contact_candidates(contact_candidates),
        evidence_corpus_text=_format_evidence_corpus(evidence_corpus),
    )
    try:
        return await review_research_overview(context, response)
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception:
        logger.error(
            "Research overview review failed; publishing the drafted "
            "overview unchanged",
            exc_info=True,
        )
        return response, dict(_UNREVIEWED_OVERVIEW), 0


async def _call_research_overview_llm(
    state: WorkflowState,
    prompt: str,
    schema: dict[str, Any] | None,
    max_tokens: int = RESEARCH_OVERVIEW_MAX_TOKENS,
) -> dict[str, Any]:
    """Calls the supervisor model to synthesize the research overview.

    Budgeted above the thinking floor: the multi-paragraph strategy
    document and the chain of thought must share one allowance.
    ``max_tokens`` defaults to the terminal document's own ceiling; the
    interim caller passes its own, much smaller one, since its schema
    asks for a handful of titles and questions rather than ten sections.
    """
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["supervisor_model_name"],
            max_tokens=max_tokens,
            temperature=MEDIUM_TEMPERATURE,
            json_schema=schema,
        ),
    )


def _format_research_overview_response(
    response: dict[str, Any],
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
    hypothesis_by_index: dict[int, str],
) -> dict[str, Any]:
    """Formats and validates the raw LLM response into the overview shape."""
    return {
        "overview": format_overview(response.get("overview", {})),
        "nih_specific_aims": response.get("nih_specific_aims", {}),
        "research_contacts": _validate_research_contacts(
            response.get("research_contacts"), contact_candidates
        ),
        "research_contact_groups": _validate_research_contact_groups(
            response.get("research_contact_groups"), hypothesis_by_index
        ),
        "knowledge_base": _validate_knowledge_base(
            response.get("knowledge_base"), evidence_corpus
        ),
        "open_questions": response.get("open_questions", []),
        "clear_patterns": response.get("clear_patterns", []),
        "unexpected_patterns": response.get("unexpected_patterns", []),
        "unexpected_research_directions": response.get(
            "unexpected_research_directions", []
        ),
    }


def _build_research_overview_result(
    research_overview: dict[str, Any], llm_calls: int = 1
) -> dict[str, Any]:
    """Assembles the research_overview_node return dict.

    Args:
        research_overview: Assembled research_overview dict.
        llm_calls: LLM calls this node spent -- the synthesis call plus
            any accuracy-review/revise rounds.

    Returns:
        Dict with updated state fields (research_overview, metrics,
        messages).
    """
    # Only the delta is passed here; merge_metrics (models/metrics.py) adds it
    # to the existing cumulative totals in state.
    metrics = create_metrics_update(deltas=MetricDeltas(llm_calls=llm_calls))
    # research_overview has no reducer annotation in the state package, so this
    # is a plain overwrite -- appropriate since this node runs once, terminally.
    return {
        "research_overview": research_overview,
        "metrics": metrics,
        "messages": phase_message(
            "research_overview",
            "Synthesized research overview and Specific Aims",
        ),
    }


_is_interim_firing = is_interim_firing
