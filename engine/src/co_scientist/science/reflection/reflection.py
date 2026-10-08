import asyncio
import dataclasses
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.core.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_REFLECTION_COMPLETE,
    PROGRESS_REFLECTION_START,
)
from co_scientist.core.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.domains.research_state.models import Hypothesis, phase_message
from co_scientist.domains.research_state.state import WorkflowState
from co_scientist.platform.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    indexed_prompt_name,
)
from co_scientist.platform.telemetry.progress import emit_progress
from co_scientist.science.prompts import PromptRunContext, get_reflection_prompt
from co_scientist.science.scheduling.funnel import finalists
from co_scientist.science.schemas.review import (
    REFLECTION_MAX_POSITIVE_OBSERVATIONS,
)

logger = logging.getLogger(__name__)


_STRENGTHS_HEADER = "Confirmed strengths (positive observations):"


def clean_positive_observations(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:REFLECTION_MAX_POSITIVE_OBSERVATIONS]


def _format_confirmed_strengths(positives: list[str]) -> str:
    if not positives:
        return ""
    lines = [_STRENGTHS_HEADER]
    lines.extend(f"- {item}" for item in positives)
    return "\n".join(lines)


def apply_observation_result(hypothesis: Hypothesis, result: dict[str, Any] | None) -> None:
    """Ranking parses the Classification suffix; preserve it even on failure.
    Absent strengths retain the legacy no-finding record shape."""
    if result is None:
        hypothesis.reflection_notes = "Analysis failed\n\nClassification: neutral"
        return

    classification = str(result.get("classification", "neutral"))
    reasoning = str(result.get("reasoning", ""))
    positives = clean_positive_observations(result.get("positive_observations"))

    notes = reasoning
    strengths = _format_confirmed_strengths(positives)
    if strengths:
        notes = f"{notes}\n\n{strengths}" if notes else strengths
    hypothesis.reflection_notes = f"{notes}\n\nClassification: {classification}"

    observation: dict[str, Any] = {
        "classification": classification,
        "reasoning": reasoning,
    }
    if positives:
        observation["positive_observations"] = positives
    hypothesis.enrichments["observation"] = observation


@dataclasses.dataclass(frozen=True)
class _ReflectionContext:
    articles_with_reasoning: str
    model_name: str
    run_id: str | None = None
    tool_registry: Any | None = None
    meta_review: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class _ReflectionCall:
    prompt: str
    schema: dict[str, Any] | None


async def observe_hypothesis(
    state: WorkflowState,
    hypothesis: Hypothesis,
    *,
    hypothesis_index: int = 1,
    total_count: int = 1,
) -> dict[str, Any] | None:
    context = _ReflectionContext(
        articles_with_reasoning=state.get("articles_with_reasoning") or "",
        model_name=state["model_name"],
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
    )
    return await analyze_single_hypothesis(hypothesis, hypothesis_index, total_count, context)


async def analyze_single_hypothesis(
    hypothesis: Hypothesis,
    hypothesis_index: int,
    total_count: int,
    context: _ReflectionContext,
) -> dict[str, Any] | None:
    logger.debug("\n→ analyzing hypothesis %s/%s", hypothesis_index, total_count)
    call = await _prepare_reflection_call(hypothesis, context, hypothesis_index)
    return await _run_reflection_llm_or_none(call, context, hypothesis_index, total_count)


async def _run_reflection_llm_or_none(
    call: _ReflectionCall,
    context: _ReflectionContext,
    hypothesis_index: int,
    total_count: int,
) -> dict[str, Any] | None:
    """One failed observation must not prevent peer hypotheses receiving
    their reviews."""
    try:
        response = await call_llm_json(
            prompt=call.prompt,
            spec=CompletionSpec(
                role="reflection",
                model_name=context.model_name,
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
                json_schema=call.schema,
            ),
            options=LLMCallOptions(
                run_id=context.run_id,
                prompt_name=indexed_prompt_name("reflection", hypothesis_index),
            ),
        )
        return _format_reflection_result(response, hypothesis_index)
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        logger.error("Reflection failed for hypothesis %s: %s", hypothesis_index, e)
        return None


async def _prepare_reflection_call(
    hypothesis: Hypothesis,
    context: _ReflectionContext,
    hypothesis_index: int,
) -> _ReflectionCall:
    prompt, schema = get_reflection_prompt(
        articles_with_reasoning=context.articles_with_reasoning,
        hypothesis_text=hypothesis.text,
        context=PromptRunContext(
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
        ),
    )
    return _ReflectionCall(prompt=prompt, schema=schema)


def _format_reflection_result(
    response: dict[str, Any],
    hypothesis_index: int,
) -> dict[str, Any]:
    # Schema-optional keys may be absent even after validation.
    classification = response.get("classification", "neutral")
    reasoning = response.get("reasoning", "")

    logger.debug("hypothesis %s classification: %s", hypothesis_index, classification)

    return {
        "classification": classification,
        "reasoning": reasoning,
        "positive_observations": response.get("positive_observations", []),
    }


async def reflection_node(state: WorkflowState) -> dict[str, Any]:
    logger.debug("\n=== reflection node ===")
    logger.info("Analyzing hypotheses against literature observations")

    # No successful literature review means no observation evidence; leave notes
    # unset and let hypotheses proceed to their independent peer review.
    inputs = _extract_reflection_inputs(state)
    if inputs is None:
        return {}
    articles_with_reasoning, hypotheses = inputs

    logger.debug("analyzing %s hypotheses against literature", len(hypotheses))

    await _run_reflection_phase(state, hypotheses, articles_with_reasoning)

    logger.info("Completed reflection analysis for %s hypotheses", len(hypotheses))

    # A bare list replaces the pool; return all of it, not just the observed.
    return _build_reflection_result(state["hypotheses"], observed=len(hypotheses))


async def _run_reflection_phase(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    articles_with_reasoning: str,
) -> None:
    await emit_progress(
        state,
        "reflection_start",
        f"Analyzing {len(hypotheses)} hypotheses against literature...",
        PROGRESS_REFLECTION_START,
        hypotheses_count=len(hypotheses),
    )

    logger.info("Running %s reflection analyses in parallel", len(hypotheses))
    analysis_results = await _run_reflection_analysis(state, hypotheses, articles_with_reasoning)

    _apply_reflection_results(hypotheses, analysis_results)

    await emit_progress(
        state,
        "reflection_complete",
        "Reflection analysis complete",
        PROGRESS_REFLECTION_COMPLETE,
        hypotheses_count=len(hypotheses),
    )


async def _run_reflection_analysis(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    articles_with_reasoning: str,
) -> list[dict[str, Any] | None]:
    """gather preserves input order so positional hypothesis/result pairing
    stays valid."""
    analysis_tasks = _build_analysis_tasks(state, hypotheses, articles_with_reasoning)
    return await asyncio.gather(*analysis_tasks)


def _build_reflection_result(hypotheses: list[Hypothesis], *, observed: int) -> dict[str, Any]:
    """These are the same mutated objects; the hypothesis reducer treats full
    text overlap as replacement rather than appending another pool."""
    return {
        "hypotheses": hypotheses,
        "messages": phase_message(
            "reflection",
            f"completed reflection analysis for {observed} hypotheses",
        ),
    }


def _extract_reflection_inputs(
    state: WorkflowState,
) -> tuple[str, list[Hypothesis]] | None:
    articles_with_reasoning = state.get("articles_with_reasoning")
    if not articles_with_reasoning:
        logger.warning("No articles_with_reasoning in state, skipping reflection")
        return None

    # Observations are depth: only finalists without notes pay for them, so a
    # first cycle, before any match, observes nothing.
    hypotheses = [h for h in finalists(state) if not h.reflection_notes]
    if not hypotheses:
        logger.info("No finalist lacks observations, skipping reflection")
        return None

    return articles_with_reasoning, hypotheses


def _build_analysis_tasks(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    articles_with_reasoning: str,
) -> list[Coroutine[Any, Any, dict[str, Any] | None]]:
    """Only initial generation reaches reflection; evolved ideas re-enter
    review, so meta-review is normally absent here."""
    return [
        observe_hypothesis(
            state,
            hyp,
            hypothesis_index=i + 1,
            total_count=len(hypotheses),
        )
        for i, hyp in enumerate(hypotheses)
    ]


def _apply_reflection_results(
    hypotheses: list[Hypothesis],
    analysis_results: list[dict[str, Any] | None],
) -> None:
    for hypothesis, result in zip(hypotheses, analysis_results, strict=True):
        apply_observation_result(hypothesis, result)
