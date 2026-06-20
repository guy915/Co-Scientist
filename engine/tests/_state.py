"""Factories for building WorkflowState and Hypothesis values in node tests.

The pipeline nodes read from and write to a large ``WorkflowState`` TypedDict.
``make_state`` returns a complete state populated with inert defaults so a test
only has to override the few fields it exercises.
"""

from typing import Any, cast

from co_scientist.models import Article, ExecutionMetrics, Hypothesis
from co_scientist.state import WorkflowState


def make_article(title: str = "An article", **overrides: Any) -> Article:
    """Build an Article with the given title and field overrides.

    Args:
        title: The article title.
        **overrides: Any Article dataclass fields to override (e.g. ``authors``,
            ``year``, ``source_id``, ``content``).

    Returns:
        An Article instance.
    """
    fields: dict[str, Any] = {"title": title}
    fields.update(overrides)
    return Article(**fields)


def make_hypothesis(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Build a Hypothesis with the given text and field overrides.

    Args:
        text: The hypothesis text.
        **overrides: Any Hypothesis dataclass fields to override (e.g.
            ``elo_rating``, ``score``, ``reviews``).

    Returns:
        A Hypothesis instance.
    """
    fields: dict[str, Any] = {"text": text}
    fields.update(overrides)
    return Hypothesis(**fields)


def make_state(**overrides: Any) -> WorkflowState:
    """Build a complete WorkflowState with inert defaults.

    Args:
        **overrides: WorkflowState keys to override (e.g. ``hypotheses``,
            ``model_name``, ``current_iteration``).

    Returns:
        A WorkflowState with every key populated; overrides applied last.
    """
    base: dict[str, Any] = {
        "research_goal": "test research goal",
        "model_name": "test-model",
        "supervisor_model_name": "test-model",
        "max_iterations": 1,
        "initial_hypotheses_count": 2,
        "evolution_max_count": 2,
        "hypotheses": [],
        "current_iteration": 0,
        "supervisor_guidance": {},
        "meta_review": {},
        "research_overview": None,
        "removed_duplicates": [],
        "tournament_matchups": [],
        "evolution_details": [],
        "metrics": ExecutionMetrics(),
        "start_time": 0.0,
        "run_id": "test-run",
        "progress_callback": None,
        "messages": [],
        "preferences": None,
        "attributes": None,
        "constraints": None,
        "starting_hypotheses": None,
        "literature": None,
        "articles_with_reasoning": None,
        "literature_review_queries": None,
        "articles": None,
        "generation_corpus_slug": None,
        "debate_transcripts": None,
        "mcp_available": False,
        "pubmed_available": False,
        "enable_tool_calling_generation": False,
        "dev_test_lit_tools_isolation": False,
        "tool_registry": None,
        "context_enrichment_sources": None,
    }
    base.update(overrides)
    return cast(WorkflowState, base)
