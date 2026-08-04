"""LangGraph state definition for hypothesis generation workflow.

The state is passed through all nodes and tracks the complete workflow.
"""

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from langgraph.graph import add_messages
from typing_extensions import TypedDict

from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
    merge_metrics,
)

logger = logging.getLogger(__name__)


def _normalized_text(hyp: Hypothesis) -> str:
    """Return a hypothesis's stripped, lowercased text (the exact-dup key)."""
    return hyp.text.strip().lower()


@dataclasses.dataclass(frozen=True)
class AppendHypotheses:
    """Explicit reducer op: append these hypotheses to the pool.

    Producing nodes (Generation, Evolution) return this instead of a bare list
    so the reducer *appends* their output to the existing pool rather than
    replacing it. Items are dropped only when they collide by id or exact
    normalized text with a hypothesis already in the pool (or an earlier item
    in the same batch); this is a deterministic identity check, not the former
    text-overlap heuristic.

    This is what makes an evolved child coexist with its parent: the child has
    a distinct id and (post-refinement) distinct text, so it is appended while
    the parent is left byte-for-byte unchanged (paper invariant SSR §4, §12).
    """

    items: list[Hypothesis]


@dataclasses.dataclass(frozen=True)
class ReplaceHypotheses:
    """Explicit reducer op: replace the pool with exactly these hypotheses.

    Unlike a bare list (where an empty list is treated as "no change"),
    ``ReplaceHypotheses([])`` genuinely sets the pool to empty. The safety
    screen node uses this so a fully-blocked pool is cleared rather than
    silently surviving the empty-list guard.
    """

    items: list[Hypothesis]


# Explicit reducer op payloads a node may return for the "hypotheses" channel.
# A bare ``list[Hypothesis]`` means REPLACE (set the pool to exactly this list).
HypothesisUpdate = list[Hypothesis] | AppendHypotheses | ReplaceHypotheses


def _dedup_by_id(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return hypotheses with later same-id entries dropped (first wins).

    Identity is the stable ``id``. Curating nodes (ranking, proximity, review)
    return an authoritative pool; this only guards against a node accidentally
    listing the same id twice, without the old text-overlap collapsing.

    Args:
        hypotheses: The pool to deduplicate by id.

    Returns:
        The pool with duplicate ids removed, order preserved.
    """
    seen: set[str] = set()
    result: list[Hypothesis] = []
    for hyp in hypotheses:
        if hyp.id not in seen:
            seen.add(hyp.id)
            result.append(hyp)
    return result


def _append_hypotheses(
    existing: list[Hypothesis], incoming: list[Hypothesis]
) -> list[Hypothesis]:
    """Append `incoming` to `existing`, dropping id/exact-text collisions.

    An incoming hypothesis is dropped when its id, or its exact normalized
    text, already appears in the existing pool or earlier in the same batch.
    This preserves the anti-duplicate safety net at the one place genuinely
    new content enters the pool (Generation/Evolution) while leaving the
    dedup of near-duplicates to the Proximity agent.

    Args:
        existing: The current hypothesis pool (left unchanged).
        incoming: Hypotheses a producing node wants to append.

    Returns:
        `existing` followed by the accepted `incoming` items.
    """
    seen_ids = {hyp.id for hyp in existing}
    seen_texts = {_normalized_text(hyp) for hyp in existing}
    result = list(existing)
    for hyp in incoming:
        text_key = _normalized_text(hyp)
        if hyp.id in seen_ids or text_key in seen_texts:
            logger.debug(
                "append: skipped duplicate hypothesis (id/text): %s...",
                hyp.text[:80],
            )
            continue
        seen_ids.add(hyp.id)
        seen_texts.add(text_key)
        result.append(hyp)
    return result


# This is the LangGraph reducer wired to WorkflowState.hypotheses (see
# `Annotated[list[Hypothesis], deduplicate_hypotheses]` below): every node
# that returns a "hypotheses" key in its state update triggers this function,
# with `existing` the current cumulative pool and `new` the value just
# returned by that node. `new` is either a bare list (REPLACE the pool with
# exactly that list) or an AppendHypotheses op (APPEND to the pool).
def deduplicate_hypotheses(
    existing: list[Hypothesis], new: HypothesisUpdate
) -> list[Hypothesis]:
    """State reducer combining a node's hypotheses update with the pool.

    Explicit, deterministic operations replace the former identity/text
    heuristic:

    - ``AppendHypotheses(items)`` — append items, dropping id/exact-text
      collisions. Used by Generation and Evolution so an evolved child cannot
      replace its parent.
    - a bare ``list[Hypothesis]`` — REPLACE: the pool becomes exactly this
      list (deduplicated by id). Used by every curating node (ranking,
      proximity, review, reflection, deep_verification), which already return
      the full or intentionally pruned pool. An empty bare list is treated as
      "no change" so a node that reports nothing cannot wipe the pool.

    Args:
        existing: Existing hypotheses in state.
        new: The node's update — an append op or a replacement list.

    Returns:
        The combined hypothesis pool.
    """
    if isinstance(new, AppendHypotheses):
        return _append_hypotheses(existing, new.items)
    if isinstance(new, ReplaceHypotheses):
        return _dedup_by_id(new.items)
    # Bare list => REPLACE. An empty list means "no update" (never a wipe).
    if not new:
        return existing
    return _dedup_by_id(new)


def accumulate_matchups(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """State reducer keeping every tournament's matchups, not just the last.

    The ranking node runs once per cycle and returns only the matchups it
    just judged. Under last-write-wins each tournament erased the record of
    the ones before it, so a multi-cycle run persisted a single cycle's
    matches and the earlier Elo history simply vanished from the matches
    table. The hypotheses' own win/loss tallies carried forward, which is
    why the loss stayed invisible.

    Deduplicated on the matchup's identity -- the two hypotheses and the
    ratings they came in with -- so a replayed or resumed ranking task
    cannot double-count a match it already committed, while a genuine
    rematch in a later cycle (necessarily at different ratings) is kept.

    Args:
        existing: Matchups already accumulated this run.
        new: Matchups the ranking node just judged.

    Returns:
        The combined matchup list in judging order.
    """
    if not new:
        return existing
    combined = list(existing)
    seen = {_matchup_identity(item) for item in existing}
    for item in new:
        identity = _matchup_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        combined.append(item)
    return combined


def _matchup_identity(matchup: dict[str, Any]) -> tuple[Any, ...]:
    """Identity of one judged matchup: the pair plus its pre-match ratings."""
    return (
        matchup.get("hypothesis_a_id"),
        matchup.get("hypothesis_b_id"),
        matchup.get("winner_elo_before"),
        matchup.get("loser_elo_before"),
    )


# Fields wrapped in Annotated[T, reducer] use `reducer` to combine a node's
# returned value with the prior state instead of the TypedDict default of
# last-write-wins; unannotated fields (e.g. current_iteration) are always
# overwritten outright by whichever node returns them.
class WorkflowState(TypedDict):
    """Complete state for the hypothesis generation workflow.

    This state is passed through all nodes in the LangGraph workflow.
    Each node reads from and writes to this state.
    """

    # Input
    research_goal: str
    """The research question to generate hypotheses for."""

    # Configuration
    model_name: str
    """LLM model to use (litellm format) for worker nodes."""

    supervisor_model_name: str
    """LLM model to use for supervisor and meta-review nodes (falls back to
    model_name if not set).
    """

    max_iterations: int
    """Number of refinement iterations to run."""

    initial_hypotheses_count: int
    """Number of initial hypotheses to generate."""

    evolution_max_count: int
    """Number of top hypotheses to evolve each iteration."""

    tournament_pairs: int
    """Number of pairwise Elo comparisons to run in each ranking pass."""

    elo_k_factor: int
    """Rating sensitivity applied sequentially to each committed matchup."""

    literature_review_papers_count: int
    """Number of papers to read/analyze during literature review."""

    # Workflow State
    hypotheses: Annotated[list[Hypothesis], deduplicate_hypotheses]
    """Current list of hypotheses being processed (auto-deduplicated)."""

    current_iteration: int
    """Current iteration number (0-indexed)."""

    resume: bool | None
    """Set by checkpoint restore (Milestone 4): when True, the graph's
    conditional entry routes to the orchestrator to continue the run rather
    than re-running from the supervisor. Absent/None for a fresh run.
    """

    # --- Adaptive orchestration (Milestone 2) ---
    task_history: list[dict[str, Any]]
    """Append-only ledger of scheduled tasks: each entry is a serialized
    ``scheduling.TaskRecord`` (task_type, status, reason, iteration). The
    Supervisor records a reason for every scheduled task and the final stop.
    """

    next_task: str | None
    """The scheduler's chosen next task at the loop point (a ``TaskType``
    value), consumed by the graph's conditional edge. None before the first
    orchestrator decision.
    """

    next_task_priority: int
    """Supervisor-assigned durable priority for the selected next task."""

    durable_task_queue: list[dict[str, Any]]
    """Live same-run queue snapshot available to the Supervisor."""

    supervisor_queue_actions: list[dict[str, Any]]
    """Validated queue mutations requested with the latest allocation."""

    termination_reason: str | None
    """Why the workflow stopped (a ``TerminationReason`` value), set by the
    orchestrator when it decides to terminate.
    """

    budget: dict[str, Any] | None
    """Serialized ``scheduling.Budget``: the compute budget and its
    termination limits (calls/tasks/time/iterations). None uses the default
    derived from ``max_iterations``.
    """

    orchestrator_state: dict[str, Any]
    """Orchestrator bookkeeping carried across loop-point decisions (previous
    top Elo, rank-stability counter, pool sizes at the last proximity/decision,
    last work task). Internal to the scheduler; not part of the public API.
    """

    supervisor_decision_provenance: str | None
    """Latest allocation source: model, hard invariant, or fallback."""

    pending_steering: bool | None
    """True when durable high-priority user steering is waiting to be
    incorporated (SSR §5). The orchestrator treats it as a high-priority
    request to GENERATE anew (see ``scheduling.policy``) and clears it once
    seen, so a steering message is consumed at the next safe boundary rather
    than only folded into the initial context.
    """

    supervisor_guidance: dict[str, Any]
    """Supervisor's research plan and workflow guidance."""

    meta_review: dict[str, Any]
    """Meta-review insights for guiding evolution."""

    research_overview: dict[str, Any] | None
    """Terminal research overview plus NIH Specific Aims synthesis."""

    removed_duplicates: list[dict[str, Any]]
    """Tracking removed duplicate hypotheses."""

    proximity_graph: dict[str, Any]
    """Persisted weighted proximity graph (Milestone 3): edges between
    similar hypotheses with a similarity score plus method/model/version/goal/
    update-time provenance. Refreshed by the proximity node as the pool grows;
    consumed by the tournament matchmaker, reports, and API/UI.
    """

    tournament_matchups: Annotated[list[dict[str, Any]], accumulate_matchups]
    """List of tournament matchups with reasoning."""

    pending_ranking_matchups: list[dict[str, Any]]
    """Current durable tournament's sequentially committed match outcomes."""

    evolution_details: list[dict[str, Any]]
    """List of evolution transformations with reasoning."""

    safety_decisions: list[dict[str, Any]]
    """Audit trail of per-hypothesis safety decisions (blocked + uncertain).
    Accumulated across safety screen passes (initial + each evolution cycle).
    """

    held_for_review: list[dict[str, Any]]
    """Full hypothesis dicts for UNCERTAIN outcomes, preserved for manual
    review by the app layer. Distinct from the hypothesis pool (which no
    longer contains them) so they are genuinely paused, not just hidden.
    """

    # Metrics
    metrics: Annotated[ExecutionMetrics, merge_metrics]
    """Execution metrics for the workflow (auto-merged from concurrent updates).
    """

    start_time: float
    """Workflow start timestamp."""

    run_id: str
    """Unique identifier for this run (used for logging)."""

    # Progress Callback
    progress_callback: None | (Callable[[str, dict[str, Any]], Awaitable[None]])
    """Optional async callback for progress updates."""

    # Messages (for LangSmith tracing)
    # add_messages is LangGraph's own builtin reducer (id-based append/
    # merge), unlike the two custom reducers above.
    messages: Annotated[list[dict[str, Any]], add_messages]
    """Message history for LangSmith observability."""

    # Optional User Preferences and Inputs
    preferences: str | None
    """Optional: Desired approach or focus for hypothesis generation."""

    attributes: list[str] | None
    """Optional: Key qualities to prioritize in hypotheses."""

    constraints: list[str] | None
    """Optional: Requirements or boundaries for hypothesis generation."""

    criteria: list[str] | None
    """Optional: Explicit success criteria for judging hypotheses."""

    run_focus_guidance: str | None
    """Prompt-ready guidance for the selected run focus."""

    run_setup_guidance: str | None
    """Prompt-ready summary of the durable run setup fields."""

    starting_hypotheses: list[str] | None
    """Optional: User-provided starting hypotheses to build upon."""

    literature: list[str] | None
    """Optional: User-provided literature references to incorporate."""

    articles_with_reasoning: str | None
    """Literature review results with analytical reasoning (formatted for
    prompts).
    """

    literature_review_queries: list[str] | None
    """Generated search queries for literature review."""

    articles: list[Article] | None
    """Individual articles extracted from literature review (for hypothesis
    comparison).
    """

    debate_transcripts: list[dict[str, Any]] | None
    """Internal debate transcripts from parallel debates. Each entry:
    {debate_id, transcript, hypothesis_text}
    """

    mcp_available: bool | None
    """Whether MCP server (for literature review tools) is available."""

    pubmed_available: bool | None
    """Whether PubMed API (Entrez) is available."""

    enable_tool_calling_generation: bool | None
    """Enable tool-calling generation where generate node queries literature
    tools directly (requires enable_literature_review_node=True + MCP server,
    default False).
    """

    dev_test_lit_tools_isolation: bool | None
    """Development mode: force cache on lit review, allocate all hypotheses to
    lit tools (no debate).
    """

    dev_mode: bool | None
    """Development mode: read a far smaller literature budget for fast
    iteration, overriding literature_review_papers_count. Resolved once per
    run from opts or COSCIENTIST_DEV_MODE (generator/run_setup.py).
    """

    tool_registry: Any | None
    """Optional ToolRegistry for config-driven tool selection."""

    context_enrichment_sources: list[dict[str, Any]] | None
    """Structured sources returned by context enrichment tools during
    literature review (e.g., INDRA mechanistic statements). Used to build
    [KG1]-style citation keys for hypothesis generation. Domain-agnostic:
    any enrichment tool can populate this.
    """
