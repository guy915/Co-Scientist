"""Format evidence and domain context for comprehensive reflection."""

from __future__ import annotations

import json
from dataclasses import asdict

from co_scientist.agents.reflection.evidence_context import (
    EvidenceCaps,
    build_evidence_context,
    showable_articles,
)
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Article, Hypothesis
from co_scientist.prompts import build_tool_instructions
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.state import WorkflowState

# How many sources one review prompt carries. Public papers and private
# scientist-supplied sources are capped separately so a full run corpus
# cannot squeeze the private context out of the prompt entirely.
_MAX_REVIEW_ARTICLES = 12
_MAX_REVIEW_PRIVATE_SOURCES = 4


# What the simulation review is told when nothing was run. Stated
# rather than left blank: an empty section reads as a simulation that
# ran and observed nothing, which is a different claim from one that
# never ran.
_NO_EXECUTION_NOTE = (
    "No simulation was executed for this review. Step through the "
    "mechanism yourself."
)


def _prompt_variables(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
    targeted_articles: list[Article] | None = None,
    observations: str | None = None,
) -> dict[str, str]:
    """Build disclosed scientific and tool context for one review task."""
    registry = state.get("tool_registry")
    tool_ids = registry.get_tools_for_workflow("reflection") if registry else []
    tool_instructions = build_tool_instructions(tool_ids, registry)
    hypothesis_text = hypothesis.text
    if review_type is ReviewType.RECURRENT:
        hypothesis_text += _recurrent_review_suffix(state, hypothesis)
    domain_context = _build_domain_context(state, targeted_articles)
    return {
        "research_goal": state["research_goal"],
        "hypothesis_text": hypothesis_text,
        "domain_context": (
            "Evidence available to this review:\n" + domain_context
            if domain_context
            else "No retrieved evidence is available to this review."
        ),
        "tool_instructions": tool_instructions,
        "execution_observations": (
            "A simulation of this mechanism was built and run. What it "
            "reported:\n\n" + observations
            if observations
            else _NO_EXECUTION_NOTE
        ),
    }


def _recurrent_review_suffix(
    state: WorkflowState, hypothesis: Hypothesis
) -> str:
    """Builds the tournament + meta-review context for a recurrent review."""
    tournament = {
        "elo_rating": hypothesis.elo_rating,
        "match_count": hypothesis.total_matches,
        "reviews": [asdict(review) for review in hypothesis.reviews],
    }
    return (
        "\n\nRecurrent-review context from the growing tournament:\n"
        + json.dumps(tournament, indent=2)
        + "\n\nCross-agent feedback:\n"
        + _format_meta_review_context(state.get("meta_review"))
    )


def _build_domain_context(
    state: WorkflowState, targeted_articles: list[Article] | None
) -> str:
    """Formats retrieved public and private evidence for a review prompt.

    Bounds the block by source count rather than by total length: a review
    weighs a handful of papers in depth, so it is the number of voices that
    has to stay reviewable, not the character budget.
    """
    evidence = [
        # The run corpus and this review's own targeted retrieval are
        # filtered separately because only the former has been marked
        # analyzed; both are then capped as one list, so a full corpus
        # crowds out the targeted sources exactly as it did before.
        *showable_articles(state.get("articles")),
        *showable_articles(targeted_articles, require_analyzed=False),
    ]
    return build_evidence_context(
        evidence,
        private_sources=state.get("context_enrichment_sources"),
        caps=EvidenceCaps(
            articles=_MAX_REVIEW_ARTICLES,
            private_sources=_MAX_REVIEW_PRIVATE_SOURCES,
        ),
        require_analyzed=False,
    )
