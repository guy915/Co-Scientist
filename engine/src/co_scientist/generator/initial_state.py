"""Initial workflow-state assembly for the hypothesis generator.

Builds the initial ``WorkflowState`` for a generation run out of four
fragments: generator configuration (supplied by the caller), empty runtime
tracking fields, run identity/system availability, and user inputs plus
literature-review output placeholders.
"""

from collections.abc import Awaitable, Callable
from typing import Any, cast

from co_scientist.models import ExecutionMetrics
from co_scientist.state import WorkflowState


def _initial_runtime_fields() -> dict[str, Any]:
    """Builds the empty runtime-state fragment of the initial state.

    Returns:
        State fields that track workflow progress and results, all
        starting at their empty/zero values.
    """
    return {
        "hypotheses": [],
        "current_iteration": 0,
        "supervisor_guidance": {},
        "meta_review": {},
        "research_overview": None,
        "removed_duplicates": [],
        "tournament_matchups": [],
        "evolution_details": [],
        "metrics": ExecutionMetrics(),
        "messages": [],
    }


def _initial_run_identity_fields(
    *,
    research_goal: str,
    start_time: float,
    run_id: str,
    progress_callback: None
    | (Callable[[str, dict[str, Any]], Awaitable[None]]),
    mcp_available: bool,
    pubmed_available: bool,
    enable_tool_calling_generation: bool,
    dev_test_lit_tools_isolation: bool,
) -> dict[str, Any]:
    """Builds the run-identity/system-availability state fragment.

    Args:
        research_goal: The research question or goal.
        start_time: Wall-clock start time (``time.time()``) for the run.
        run_id: Unique identifier for this run.
        progress_callback: Async callback for progress updates.
        mcp_available: Whether the MCP server is available.
        pubmed_available: Whether PubMed is available via MCP.
        enable_tool_calling_generation: Whether tool-calling generation
            is enabled for this run.
        dev_test_lit_tools_isolation: Whether dev lit-tools isolation
            mode is enabled for this run.

    Returns:
        State fields identifying this run and the system capabilities
        available to it.
    """
    return {
        "research_goal": research_goal,
        "start_time": start_time,
        "run_id": run_id,
        "progress_callback": progress_callback,
        # System availability flags
        "mcp_available": mcp_available,
        "pubmed_available": pubmed_available,
        "enable_tool_calling_generation": enable_tool_calling_generation,
        "dev_test_lit_tools_isolation": dev_test_lit_tools_isolation,
    }


def _initial_user_and_literature_fields(
    *,
    opts: dict[str, Any],
    user_inputs: dict[str, Any],
) -> dict[str, Any]:
    """Builds the user-input and literature-review-output fragment.

    Args:
        opts: Caller-supplied generation options.
        user_inputs: The ``user_inputs`` sub-dict of opts.

    Returns:
        State fields for optional user preferences/inputs, plus the
        (initially empty) literature review outputs populated later by
        downstream nodes.
    """
    return {
        # Optional user preferences and inputs
        "preferences": opts.get("preferences"),
        "attributes": opts.get("attributes"),
        "constraints": opts.get("constraints"),
        "criteria": opts.get("criteria"),
        "run_focus_guidance": opts.get("run_focus_guidance"),
        "run_setup_guidance": opts.get("run_setup_guidance"),
        "starting_hypotheses": user_inputs.get("starting_hypotheses"),
        "literature": user_inputs.get("literature"),
        # Literature review outputs (populated by downstream nodes)
        "articles_with_reasoning": None,
        "literature_review_queries": None,
        "articles": None,
        "debate_transcripts": None,
        "context_enrichment_sources": None,
    }


def _build_initial_state(
    *,
    config_fields: dict[str, Any],
    research_goal: str,
    start_time: float,
    run_id: str,
    progress_callback: None
    | (Callable[[str, dict[str, Any]], Awaitable[None]]),
    opts: dict[str, Any],
    user_inputs: dict[str, Any],
    mcp_available: bool,
    pubmed_available: bool,
    enable_tool_calling_generation: bool,
    dev_test_lit_tools_isolation: bool,
) -> WorkflowState:
    """Assembles the initial workflow state dict for a generation run.

    Args:
        config_fields: Generator-config state fragment (model names,
            iteration/count knobs, and the tool registry), as built by
            ``HypothesisGenerator._initial_config_fields``.
        research_goal: The research question or goal.
        start_time: Wall-clock start time (``time.time()``) for the run.
        run_id: Unique identifier for this run.
        progress_callback: Async callback for progress updates.
        opts: Caller-supplied generation options.
        user_inputs: The ``user_inputs`` sub-dict of opts.
        mcp_available: Whether the MCP server is available.
        pubmed_available: Whether PubMed is available via MCP.
        enable_tool_calling_generation: Whether tool-calling generation
            is enabled for this run.
        dev_test_lit_tools_isolation: Whether dev lit-tools isolation
            mode is enabled for this run.

    Returns:
        The initial workflow state (including "start_time" and "run_id"
        keys).
    """
    identity_fields = _initial_run_identity_fields(
        research_goal=research_goal,
        start_time=start_time,
        run_id=run_id,
        progress_callback=progress_callback,
        mcp_available=mcp_available,
        pubmed_available=pubmed_available,
        enable_tool_calling_generation=enable_tool_calling_generation,
        dev_test_lit_tools_isolation=dev_test_lit_tools_isolation,
    )
    user_and_literature_fields = _initial_user_and_literature_fields(
        opts=opts, user_inputs=user_inputs
    )
    return cast(
        WorkflowState,
        {
            **config_fields,
            **_initial_runtime_fields(),
            **identity_fields,
            **user_and_literature_fields,
        },
    )
