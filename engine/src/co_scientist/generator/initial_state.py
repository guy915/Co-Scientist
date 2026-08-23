"""Initial workflow-state assembly for the hypothesis generator.

Builds the initial ``WorkflowState`` for a generation run out of four
fragments: generator configuration (supplied by the caller), empty runtime
tracking fields, run identity/system availability, and user inputs plus
literature-review output placeholders.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from co_scientist.models import ExecutionMetrics
from co_scientist.retrieval_degradation import (
    resolve_retrieval_degradation,
)
from co_scientist.state import WorkflowState

ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]] | None


@dataclass(frozen=True)
class RunCallbacks:
    """Async hooks a caller can attach to a generation run.

    Attributes:
        progress: Async ``(phase_name, data)`` hook called as the run
            advances through phases.
        checkpoint: Async ``(node_name, full_state)`` hook called after
            each node in streaming mode, for persisting a resumable
            checkpoint. Ignored when ``stream`` is False.
    """

    progress: ProgressCallback = None
    checkpoint: ProgressCallback = None


@dataclass(frozen=True)
class RunIdentity:
    """Who this run is and where its progress is reported.

    Attributes:
        research_goal: The research question or goal.
        start_time: Wall-clock start time (``time.time()``) for the run.
        run_id: Unique identifier for this run.
        progress_callback: Async callback for progress updates.
    """

    research_goal: str
    start_time: float
    run_id: str
    progress_callback: ProgressCallback = None


@dataclass(frozen=True)
class RunCapabilities:
    """The system capabilities and modes resolved for one run.

    Attributes:
        mcp_available: Whether the MCP server is available.
        pubmed_available: Whether PubMed is available via MCP.
        enable_tool_calling_generation: Whether tool-calling generation is
            enabled for this run. Resolved upstream (see
            ``run_setup._resolve_tool_calling_generation``): opt-in,
            enabled only when the caller explicitly requests it and
            literature tools are available. The dataclass default
            stays False so a capabilities
            value assembled without that resolution never silently turns
            the agentic path on.
        enable_simulation_execution: Whether the simulation review may
            build and run a model of the mechanism instead of stepping
            through it mentally. Resolved upstream (see
            ``run_setup._resolve_simulation_execution``): opt-in, and a
            request rather than a guarantee -- the review falls back to
            mental simulation on a host that cannot confine a command.
        dev_test_lit_tools_isolation: Whether dev lit-tools isolation is
            enabled for this run.
        dev_mode: Whether dev mode (reduced literature budget) is enabled for
            this run.
        enable_overview_review: Whether the terminal research overview
            is checked for scientific accuracy against this run's own
            material before it publishes. Resolved upstream (see
            ``run_setup._resolve_overview_review``): opt-in, and
            refused for the offline backend the same way
            ``enable_simulation_execution`` is.
        research_tier: Which tier's ceilings the literature review's deep
            research runs under, or "" for none. Resolved upstream (see
            ``run_setup._resolve_research_tier``): opt-in, and refused
            where the run has no literature tools to search with.
        local_corpus_dir: Where the group's own papers sit for this run,
            or "" when it has none or may not read them. Resolved
            upstream (see ``run_setup._resolve_local_corpus_dir``), which
            is also where the audience decision is read, so a node
            holding a non-empty value here may search it without asking
            anything further.
    """

    mcp_available: bool = False
    pubmed_available: bool = False
    enable_tool_calling_generation: bool = False
    enable_simulation_execution: bool = False
    enable_overview_review: bool = False
    dev_test_lit_tools_isolation: bool = False
    dev_mode: bool = False
    research_tier: str = ""
    local_corpus_dir: str = ""


def _initial_runtime_fields() -> dict[str, Any]:
    """Builds the empty runtime-state fragment of the initial state.

    Returns:
        State fields that track workflow progress and results, all
        starting at their empty/zero values.
    """
    return {
        "hypotheses": [],
        "current_iteration": 0,
        # Adaptive orchestration (Milestone 2): the task ledger and the
        # scheduler's routing/bookkeeping start empty; the orchestrator seeds
        # its bookkeeping on the first loop-point decision.
        "task_history": [],
        "next_task": None,
        "termination_reason": None,
        # "budget" is supplied by the generator config fields, not here.
        "orchestrator_state": {},
        "supervisor_guidance": {},
        "meta_review": {},
        "research_overview": None,
        "removed_duplicates": [],
        "proximity_graph": {},
        "tournament_matchups": [],
        "evolution_details": [],
        # Per-hypothesis safety screen (pre-ranking gate): the audit trail and
        # the manual-review hold start empty so they are always present lists,
        # including across a checkpoint restore.
        "safety_decisions": [],
        "held_for_review": [],
        # Enhancement nodes served a placeholder fallback append their schema
        # names here (progress.record_schema_degradation) so the final report
        # can explain a blank section instead of showing silence.
        "degraded_nodes": [],
        "metrics": ExecutionMetrics(),
        "messages": [],
    }


def _initial_run_identity_fields(
    identity: RunIdentity, capabilities: RunCapabilities
) -> dict[str, Any]:
    """Builds the run-identity/system-availability state fragment.

    Args:
        identity: Who this run is and where its progress is reported.
        capabilities: The system capabilities and modes resolved for it.

    Returns:
        State fields identifying this run and the system capabilities
        available to it.
    """
    return {
        "research_goal": identity.research_goal,
        "start_time": identity.start_time,
        "run_id": identity.run_id,
        "progress_callback": identity.progress_callback,
        "mcp_available": capabilities.mcp_available,
        "pubmed_available": capabilities.pubmed_available,
        "enable_tool_calling_generation": (
            capabilities.enable_tool_calling_generation
        ),
        "enable_simulation_execution": (
            capabilities.enable_simulation_execution
        ),
        "dev_test_lit_tools_isolation": (
            capabilities.dev_test_lit_tools_isolation
        ),
        "dev_mode": capabilities.dev_mode,
        "enable_overview_review": capabilities.enable_overview_review,
        "research_tier": capabilities.research_tier,
        "local_corpus_dir": capabilities.local_corpus_dir,
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
        # High-priority durable steering waiting at run start (SSR §5); the
        # orchestrator consumes it at the next safe boundary and clears it.
        "pending_steering": bool(opts.get("pending_steering")),
        "attributes": opts.get("attributes"),
        "constraints": opts.get("constraints"),
        # Lab constraints elicited by the app's goal interview (K5); the
        # generation and evolution feasibility prompts render them.
        "lab_constraints": opts.get("lab_constraints"),
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
        "context_enrichment_sources": opts.get("context_enrichment_sources"),
    }


def _build_initial_state(
    *,
    config_fields: dict[str, Any],
    identity: RunIdentity,
    capabilities: RunCapabilities,
    opts: dict[str, Any],
    user_inputs: dict[str, Any],
) -> WorkflowState:
    """Assembles the initial workflow state dict for a generation run.

    Args:
        config_fields: The generator-config fragment of the initial state.
        identity: Who this run is and where its progress is reported.
        capabilities: The system capabilities and modes resolved for it.
        opts: Caller-supplied generation options.
        user_inputs: The ``user_inputs`` sub-dict of opts.

    Returns:
        The initial workflow state.
    """
    return cast(
        WorkflowState,
        {
            **config_fields,
            **_initial_runtime_fields(),
            **_initial_run_identity_fields(identity, capabilities),
            **_initial_user_and_literature_fields(
                opts=opts, user_inputs=user_inputs
            ),
            "retrieval_degradation": resolve_retrieval_degradation(
                mcp_available=bool(capabilities.mcp_available),
                private_sources=opts.get("context_enrichment_sources"),
                local_corpus=bool(capabilities.local_corpus_dir),
            ),
        },
    )
