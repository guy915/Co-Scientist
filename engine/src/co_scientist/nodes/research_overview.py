"""Research-overview node - terminal synthesis into a roadmap + NIH aims."""

import logging
from typing import Any

from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    PROGRESS_RESEARCH_OVERVIEW_START,
    RESEARCH_OVERVIEW_TOP_K,
    THINKING_MAX_TOKENS,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Article,
    Hypothesis,
    create_metrics_update,
    phase_message,
    rank_by_elo,
)
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_research_overview_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def research_overview_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesize the top-k hypotheses into an overview + NIH Specific Aims.

    Args:
        state: The current workflow state.

    Returns:
        A state delta carrying the research overview, metrics, and a message.
    """
    hypotheses = state.get("hypotheses", [])
    if not hypotheses:
        # Nothing survived to this terminal node (e.g. an earlier failure
        # or all hypotheses were pruned); skip the LLM call rather than
        # synthesizing an overview from an empty pool.
        return {"research_overview": {}}

    summary = _summarize_top_hypotheses(hypotheses)
    contact_candidates = _build_contact_candidates(state.get("articles"))

    await emit_progress(
        state,
        "research_overview_start",
        "Synthesizing research overview...",
        PROGRESS_RESEARCH_OVERVIEW_START,
    )

    research_overview = await _synthesize_research_overview(
        state, summary, contact_candidates
    )

    await emit_progress(
        state,
        "research_overview_complete",
        "Research overview ready",
        PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    )

    logger.info("Research overview complete")

    return _build_research_overview_result(research_overview)


def _summarize_top_hypotheses(hypotheses: list[Hypothesis]) -> str:
    """Ranks hypotheses by Elo and formats the top-k as a numbered summary.

    Re-ranks defensively (does not assume the incoming list is already
    Elo-sorted) and keeps only the strongest RESEARCH_OVERVIEW_TOP_K (10)
    hypotheses so the synthesis prompt stays a bounded size.

    Args:
        hypotheses: The full hypothesis pool.

    Returns:
        A newline-joined, numbered summary of the top-k hypotheses.
    """
    ranked = rank_by_elo(hypotheses)
    top = ranked[:RESEARCH_OVERVIEW_TOP_K]
    return "\n".join(
        f"{i + 1}. (Elo {h.elo_rating}) {h.text}" for i, h in enumerate(top)
    )


async def _synthesize_research_overview(
    state: WorkflowState,
    summary: str,
    contact_candidates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Builds the research-overview prompt, calls the LLM, and formats it.

    Uses the supervisor model (strategic synthesis, not a worker task) and
    the larger THINKING_MAX_TOKENS budget, since the roadmap and Specific
    Aims sections can each be long structured output. meta_review and the
    durable run guidance fields steer the synthesis toward the same
    strategic themes used elsewhere in the workflow.

    Args:
        state: Current workflow state.
        summary: Top-k hypotheses summary from _summarize_top_hypotheses.
        contact_candidates: Verified authors keyed by a stable candidate id.

    Returns:
        Dict with "overview" and "nih_specific_aims" keys, defaulting to
        empty dicts if the LLM omits either section so downstream consumers
        always see a well-formed research_overview shape.
    """
    prompt, schema = get_research_overview_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        contact_candidates=_format_contact_candidates(contact_candidates),
        meta_review=state.get("meta_review"),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )
    response = await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=THINKING_MAX_TOKENS,
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
    )

    return {
        "overview": response.get("overview", {}),
        "nih_specific_aims": response.get("nih_specific_aims", {}),
        "research_contacts": _validate_research_contacts(
            response.get("research_contacts"), contact_candidates
        ),
    }


def _build_contact_candidates(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build a bounded expert pool exclusively from retrieved-paper authors."""
    candidates: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()
    for article_index, article in enumerate(articles or []):
        if not article.used_in_analysis:
            continue
        for author_index, raw_name in enumerate(article.authors):
            name = raw_name.strip()
            normalized = name.casefold()
            if not name or normalized in seen_names or len(candidates) >= 30:
                continue
            candidate_id = f"author-{article_index + 1}-{author_index + 1}"
            candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "name": name,
                "source_id": article.source_id or "",
                "source_title": article.title,
                "source_url": article.url or "",
                "source": article.source,
            }
            seen_names.add(normalized)
    return candidates


def _format_contact_candidates(
    candidates: dict[str, dict[str, Any]],
) -> str:
    """Format the verified candidate pool for the synthesis prompt."""
    if not candidates:
        return "No verified literature authors available."
    return "\n".join(
        (
            "- {candidate_id}: {name}; paper={source_title}; "
            "source_id={source_id}; url={source_url}"
        ).format(**candidate)
        for candidate in candidates.values()
    )


def _validate_research_contacts(
    raw_contacts: Any,
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only exact candidate matches and attach immutable provenance."""
    if not isinstance(raw_contacts, list):
        return []
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_contacts:
        if not isinstance(raw, dict):
            continue
        candidate_id_value = raw.get("candidate_id")
        if not isinstance(candidate_id_value, str):
            continue
        candidate_id = candidate_id_value
        candidate = candidates.get(candidate_id)
        if (
            candidate is None
            or raw.get("name") != candidate["name"]
            or candidate_id in seen
        ):
            continue
        accepted.append(
            {
                **candidate,
                "expertise": str(raw.get("expertise") or "").strip(),
                "justification": str(
                    raw.get("justification") or ""
                ).strip(),
            }
        )
        seen.add(candidate_id)
        if len(accepted) == 5:
            break
    return accepted


def _build_research_overview_result(
    research_overview: dict[str, Any],
) -> dict[str, Any]:
    """Assembles the research_overview_node return dict.

    Args:
        research_overview: Assembled research_overview dict.

    Returns:
        Dict with updated state fields (research_overview, metrics,
        messages).
    """
    # Only the delta (one LLM call) is passed here; merge_metrics (models.py)
    # adds it to the existing cumulative totals in state.
    metrics = create_metrics_update(llm_calls_delta=1)
    # research_overview has no reducer annotation in state.py, so this is a
    # plain overwrite -- appropriate since this node runs once, terminally.
    return {
        "research_overview": research_overview,
        "metrics": metrics,
        "messages": phase_message(
            "research_overview",
            "Synthesized research overview and Specific Aims",
        ),
    }
