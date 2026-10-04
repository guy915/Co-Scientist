"""Meta-review synthesis and normalization of recurring critique themes."""

import dataclasses
import json
import logging
from typing import Any

from co_scientist.agents.node_degradation import run_or_degrade
from co_scientist.agents.reflection.review_gate import (
    mature_review_summary,
)
from co_scientist.agents.safety import (
    monitor_research_direction,
)
from co_scientist.constants import (
    PROGRESS_META_REVIEW_COMPLETE,
    PROGRESS_META_REVIEW_START,
    THINKING_MAX_TOKENS,
    truncate,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import (
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import PromptRunContext, get_meta_review_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def normalize_recurring_themes(
    recurring_themes: list[Any],
) -> list[dict[str, Any]]:
    """Coerce every entry into a uniform nested taxonomy node.

    Args:
        recurring_themes: The model's ``recurring_themes`` array, of any
            shape.

    Returns:
        One ``{theme, description, frequency, sub_themes}`` dict per
        entry, with ``sub_themes`` itself normalized.
    """
    return [_normalize_theme(entry) for entry in recurring_themes]


def _normalize_theme(entry: Any) -> dict[str, Any]:
    """Normalize one top-level theme.

    A non-dict entry keeps its text as ``theme`` with everything else
    empty, rather than being dropped: the flattening this replaced already
    tolerated a bare string, and a model that ignores the schema at the
    top level has still said something worth reporting.
    """
    if not isinstance(entry, dict):
        return _theme_node(str(entry), "", "", [])
    return _theme_node(
        str(entry.get("theme", "")),
        str(entry.get("description", "")),
        # A lax provider returns frequency as a bare integer even though
        # the schema declares it a string.
        str(entry.get("frequency", "")),
        _normalize_sub_themes(entry.get("sub_themes")),
    )


def _theme_node(
    theme: str,
    description: str,
    frequency: str,
    sub_themes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one theme node, so its key set is written down once."""
    return {
        "theme": theme,
        "description": description,
        "frequency": frequency,
        "sub_themes": sub_themes,
    }


def _normalize_sub_themes(sub_themes: Any) -> list[dict[str, Any]]:
    """Normalize a theme's sub-theme list, tolerating a non-list value."""
    if not isinstance(sub_themes, list):
        return []
    return [_normalize_sub_theme(entry) for entry in sub_themes]


def _normalize_sub_theme(entry: Any) -> dict[str, Any]:
    """Normalize one critique point under a theme.

    ``points`` is the taxonomy's third level and the published artifact's
    last: a list of plain guidance sentences, with nothing nested below
    them.
    """
    if not isinstance(entry, dict):
        return {"theme": str(entry), "description": "", "points": []}
    return {
        "theme": str(entry.get("theme", "")),
        "description": str(entry.get("description", "")),
        "points": _normalize_points(entry.get("points")),
    }


def _normalize_points(points: Any) -> list[str]:
    """Coerce a sub-theme's guidance points to strings."""
    if not isinstance(points, list):
        return []
    return [str(point) for point in points]


async def meta_review_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesizes insights from all reviews across all hypotheses.

    This node analyzes all the reviews collectively to identify:
    - Common strengths and weaknesses
    - Promising research directions
    - Areas needing improvement
    - Strategic guidance for evolution

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (meta_review)
    """
    hypotheses = state["hypotheses"]
    logger.info("Synthesizing meta-review from %s hypotheses", len(hypotheses))
    return await _run_meta_review_phase(state, hypotheses)


async def _run_meta_review_phase(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> dict[str, Any]:
    """Later reviews must not erase earlier feedback failure patterns."""
    await emit_progress(
        state,
        "meta_review_start",
        "Synthesizing insights from all reviews...",
        PROGRESS_META_REVIEW_START,
    )

    all_reviews = _collect_feedback_records(
        hypotheses, state.get("tournament_matchups", [])
    )
    if not all_reviews:
        logger.warning("No reviews available for meta-review")
        return _empty_meta_review_result()

    # An unreachable provider degrades to the same empty synthesis the
    # no-reviews branch above already returns, rather than failing the
    # task: this node is not terminal, but a task that spends its durable
    # attempts settles the whole run, so the report is lost either way.
    return await run_or_degrade(
        state,
        lambda: _synthesize_and_monitor(state, all_reviews),
        schema_name="meta_review",
        fallback=_degraded_meta_review_result,
        lost="evolution and ranking continue without cross-hypothesis "
        "guidance for this cycle",
    )


async def _synthesize_and_monitor(
    state: WorkflowState,
    all_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    meta_review = await _synthesize_meta_review(state, all_reviews)

    await emit_progress(
        state,
        "meta_review_complete",
        "Meta-review synthesis complete",
        PROGRESS_META_REVIEW_COMPLETE,
        strengths_count=len(meta_review["common_strengths"]),
        recommendations_count=len(meta_review["strategic_recommendations"]),
    )

    # The overview is the run's own account of where its ideas are heading,
    # which is what makes it the thing to monitor (J6). Empty for a run the
    # monitor does not halt, so a healthy synthesis returns exactly what it
    # always did. Screened here rather than outside the degrade wrapper
    # because the screen is deterministic policy matching, not a call --
    # and a degraded synthesis carries no direction to halt on.
    halt = await monitor_research_direction(state, meta_review)
    return {**_build_meta_review_result(meta_review), **halt}


async def _synthesize_meta_review(
    state: WorkflowState,
    all_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt, schema = get_meta_review_prompt(
        research_goal=state["research_goal"],
        all_reviews=json.dumps(all_reviews, indent=2),
        preferences=state.get("preferences"),
        context=PromptRunContext(
            supervisor_guidance=state.get("supervisor_guidance"),
            tool_registry=state.get("tool_registry"),
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
        ),
    )
    response = await _call_meta_review_llm(state, prompt, schema)
    meta_review = _build_meta_review(response)
    _log_meta_review_summary(meta_review)
    return meta_review


async def _call_meta_review_llm(
    state: WorkflowState,
    prompt: str,
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Supervisor-model synthesis steers cross-hypothesis evolution."""
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["supervisor_model_name"],
            max_tokens=THINKING_MAX_TOKENS,
            json_schema=schema,
        ),
        options=LLMCallOptions(
            run_id=state.get("run_id"),
            prompt_name="meta_review",
        ),
    )


def _build_meta_review_result(meta_review: dict[str, Any]) -> dict[str, Any]:
    """Assembles the meta_review_node return dict.

    Args:
        meta_review: Assembled meta_review dict.

    Returns:
        Dict with updated state fields (meta_review, metrics, messages).
    """
    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(deltas=MetricDeltas(llm_calls=1))

    return {
        "meta_review": meta_review,
        "metrics": metrics,
        "messages": phase_message(
            "meta_review",
            "Synthesized meta-review from all hypotheses",
            themes=len(meta_review.get("emerging_themes", [])),
        ),
    }


def _empty_meta_review_result() -> dict[str, Any]:
    """Builds the fallback return value when no hypothesis has a review.

    Returns:
        Dict with a minimal meta_review, matching the shape downstream
        readers (evolve, ranking prompts) expect via dict.get() with
        defaults.
    """
    return {
        "meta_review": {
            "summary": "No reviews available",
            "common_strengths": [],
            "common_weaknesses": [],
            "strategic_recommendations": [],
        }
    }


def _degraded_meta_review_result() -> dict[str, Any]:
    """The same empty shape, said truthfully for a failed synthesis.

    ``summary`` renders into the finished report
    (``app.report.markdown.meta_review``), and "No reviews available" is
    a statement about the run: true of the branch above, false of a run
    whose reviews were all present and whose model could not be reached.
    """
    result = _empty_meta_review_result()
    result["meta_review"]["summary"] = (
        "Meta-review synthesis was unavailable for this cycle"
    )
    return result


def _log_meta_review_summary(meta_review: dict[str, Any]) -> None:
    """Logs a summary of the completed meta-review.

    One record, not three: each is an open-write-close against the app's
    single SQLite writer and competes for a readable window of the newest
    hundred, so a node's completion is worth one line carrying its counts.

    Args:
        meta_review: assembled meta_review dict.
    """
    logger.info(
        "Meta-review complete: %s common strengths,"
        " %s strategic recommendations",
        len(meta_review["common_strengths"]),
        len(meta_review["strategic_recommendations"]),
    )


def _collect_review_summaries(
    hypotheses: list[Hypothesis],
) -> list[dict[str, Any]]:
    """Build complete per-hypothesis review histories for the LLM.

    Every review is retained in chronological order, plus current tournament
    standing and verification status, so recurring critiques remain visible.

    Indices are 1-based. The model quotes them straight back into the
    strategic recommendations a scientist reads ("Fluspirilene (Hypothesis
    1)"), so this number is user-facing prose, not an internal offset, and a
    0-based one reads as an off-by-one to everyone outside the code.

    Args:
        hypotheses: hypotheses to summarize.

    Returns:
        List of review summary dicts, one per reviewed hypothesis
        (hypotheses with no reviews are skipped).
    """
    all_reviews = []
    for i, hyp in enumerate(hypotheses, start=1):
        if not hyp.reviews:
            continue

        review_data = {
            "record_type": "review_history",
            "hypothesis_index": i,
            "hypothesis_text": truncate(hyp.text),
            "reviews": [dataclasses.asdict(review) for review in hyp.reviews],
            "elo_rating": hyp.elo_rating,
            "win_loss_record": f"{hyp.win_count}W-{hyp.loss_count}L",
            "deep_verification_verdict": hyp.deep_verification_verdict,
        }
        # The mature Reflection cascade's full/simulation/recurrent
        # findings join the synthesis under the same omit-when-absent
        # convention (audit E1): they are review output like the rest.
        mature_reviews = mature_review_summary(hyp.enrichments)
        if mature_reviews is not None:
            review_data["mature_reviews"] = mature_reviews
        all_reviews.append(review_data)
    return all_reviews


def _collect_debate_records(
    matchups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return every tournament debate and its full turn transcript.

    ``match_index`` is 1-based for the same reason ``hypothesis_index`` is:
    the model may cite a match number in prose a scientist reads.
    """
    return [
        {
            "record_type": "ranking_debate",
            "match_index": index,
            "hypothesis_a_id": matchup.get("hypothesis_a_id"),
            "hypothesis_b_id": matchup.get("hypothesis_b_id"),
            "hypothesis_a": matchup.get("hypothesis_a"),
            "hypothesis_b": matchup.get("hypothesis_b"),
            "winner_id": matchup.get("winner_id"),
            "winner": matchup.get("winner"),
            "reasoning": matchup.get("reasoning"),
            "confidence": matchup.get("confidence"),
            "debate_turns": matchup.get("debate_turns", 1),
            "debate_transcript": matchup.get("debate_transcript", []),
        }
        for index, matchup in enumerate(matchups, start=1)
    ]


def _collect_feedback_records(
    hypotheses: list[Hypothesis],
    matchups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine all review histories and ranking debates for meta-analysis."""
    return [
        *_collect_review_summaries(hypotheses),
        *_collect_debate_records(matchups),
    ]


def _build_meta_review(response: dict[str, Any]) -> dict[str, Any]:
    """Assembles the meta_review state dict from the LLM response.

    This dict becomes state["meta_review"], consumed downstream by the
    evolve node (to steer refinement), by ranking's judge_matchup
    (included in the tournament-judging prompt), and -- via
    ``prompts._common._format_meta_review_context`` -- by every generation
    strategy's next cycle (debate, assumptions, tool-based drafting, and
    literature-review query/synthesis), so its shape is a de facto
    cross-node contract.

    ``potential_connections`` is kept alongside the strengths/weaknesses/
    recommendations fields already threaded into generation: it is the
    field closest to the paper's "areas already covered / directions
    flagged as open" feedback (I2), and reusing this periodic synthesis
    call is what keeps that feedback bounded -- no extra LLM call is
    added to carry it forward (see the terminal, unconsumed
    research_overview by contrast).

    Args:
        response: raw LLM JSON response from the meta-review call.

    Returns:
        The assembled meta_review dict.
    """
    # Schema returns recurring_themes as a nested taxonomy: {theme,
    # description, frequency, sub_themes[{theme, description, points}]}
    # Recurring-theme normalization preserves the taxonomy (MO-2).
    # emerging_themes stays the flat list of TOP-LEVEL theme names only:
    # it feeds every downstream prompt through
    # prompts._common._format_meta_review_context and the safety monitor,
    # both of which want a short list of area names, so folding sub-theme
    # names into it would multiply that per-cycle context for readers that
    # cannot use the depth. The full taxonomy travels under
    # recurring_themes, read only by the report renderer.
    recurring_themes = normalize_recurring_themes(
        response.get("recurring_themes", [])
    )
    emerging_themes = [theme["theme"] for theme in recurring_themes]

    return {
        "summary": response.get("meta_review_summary", ""),
        "common_strengths": response.get("strengths", []),
        "common_weaknesses": response.get("weaknesses", []),
        "emerging_themes": emerging_themes,
        "recurring_themes": recurring_themes,
        "strategic_recommendations": response.get(
            "strategic_recommendations", []
        ),
        "potential_connections": response.get("potential_connections", []),
        # R12-9: the published report's per-idea comparison table and its
        # comparison against existing solutions -- see
        # schemas/meta_review_schema.py for the domain-aware axes/values
        # shape and report/markdown/meta_review.py for the render.
        "candidate_comparison": response.get("candidate_comparison", {}),
        "existing_solutions_comparison": response.get(
            "existing_solutions_comparison", {}
        ),
        # R14-27: the ranking document's own "Main Research Directions"
        # narrative -- see schemas/meta_review_schema.py.
        "main_research_directions": response.get(
            "main_research_directions", ""
        ),
    }
