"""Strategy selection and count allocation for the generation coordinator.

Classifies which of the 3-condition generation strategies applies to a run,
allocates per-strategy hypothesis counts, and handles the strategy-dependent
logging plus the generation-start progress emission.
"""

import logging
from dataclasses import dataclass
from typing import Any

from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    PROGRESS_GENERATE_START,
)
from co_scientist.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# Bundles the three-way count split (and the two special-mode flags) so the
# helper functions below can pass one object around instead of five loose
# parameters.
@dataclass
class GenerationCounts:
    """Encapsulates hypothesis count allocation across generation methods."""

    tools_count: int  # hypotheses via tool-based draft/validate flow
    debate_with_lit_count: int  # hypotheses via debate, with lit context
    debate_only_count: int  # hypotheses via debate, no literature at all
    assumptions_count: int = 0  # hypotheses via iterative-assumptions technique
    is_dev_isolation: bool = False  # dev/test: force tools-only allocation
    is_degraded_mode: bool = False  # no literature review was available


def _check_literature_availability(
    articles_with_reasoning: str | None, mcp_available: bool
) -> bool:
    """Determine if literature review is available and valid."""
    # articles_with_reasoning is None before the literature review node has
    # run; it is set to the LITERATURE_REVIEW_FAILED sentinel when that node
    # ran but errored out. mcp_available must also be true here so we do not
    # try to run tool-based generation against a lit review summary that was
    # produced without live MCP tool access.
    return (
        articles_with_reasoning is not None
        and articles_with_reasoning != LITERATURE_REVIEW_FAILED
        and mcp_available
    )


def _classify_generation_strategy(
    state: WorkflowState, has_literature: bool, enable_tool_calling: bool
) -> str:
    """Classify which of the 3-condition generation strategies applies.

    Mirrors the precondition order that _determine_generation_counts,
    _log_generation_strategy, and _emit_start_progress all key off of, so
    each of those stays a plain per-label dispatch.

    Returns:
        One of "dev_isolation", "lit_and_tools" (condition a), "lit_only"
        (condition c), or "no_lit" (condition b).
    """
    # Dev/test escape hatch: route everything through the tool-based path in
    # isolation so its behavior can be exercised without debate generation
    # mixed in. Takes priority over the normal 3-condition strategy below.
    if state.get("dev_test_lit_tools_isolation", False):
        return "dev_isolation"

    # Condition (a): literature review succeeded and tool calling is enabled
    # for generation - split the workload between the two literature-aware
    # strategies so results benefit from both a tool-driven read/validate
    # loop and a debate that has the same literature context.
    if has_literature and enable_tool_calling:
        return "lit_and_tools"

    # Condition (c): literature review succeeded but tool calling is off for
    # generation (e.g. model/config does not support it) - fall back to
    # debate-with-literature for the full count.
    if has_literature:
        return "lit_only"

    # Condition (b): no usable literature review at all - degrade to debate
    # generation from the model's latent knowledge only.
    return "no_lit"


def _split_tools_and_debate_counts(total_count: int) -> tuple[int, int]:
    """Split total_count 50/50 between tools and debate-with-literature.

    Args:
        total_count: total hypotheses to allocate across the two methods.

    Returns:
        Tuple of (tools_count, debate_with_lit_count). If the 50/50 split
        would leave debate_with_lit_count at zero (total_count=1), the full
        count is routed to tools instead.
    """
    tools_count = max(1, total_count // 2)
    debate_with_lit_count = total_count - tools_count
    if debate_with_lit_count == 0:
        tools_count = total_count
    return tools_count, debate_with_lit_count


def _assumptions_slice(total_count: int) -> int:
    """Reserve a quarter of the batch for the iterative-assumptions technique.

    A small batch (< 4) stays single-technique so one or two hypotheses are
    not fragmented across strategies.

    Args:
        total_count: Total hypotheses to allocate for this generation call.

    Returns:
        The number of hypotheses to route to the assumptions technique.
    """
    return max(1, total_count // 4) if total_count >= 4 else 0


def _dev_isolation_counts(total_count: int) -> GenerationCounts:
    """Route every hypothesis to the tool-based path, for dev isolation."""
    return GenerationCounts(
        tools_count=total_count,
        debate_with_lit_count=0,
        debate_only_count=0,
        is_dev_isolation=True,
    )


def _lit_and_tools_counts(total_count: int) -> GenerationCounts:
    """Allocate condition (a): tools + debate-with-lit + an assumptions slice.

    Reserves a slice for iterative-assumptions (a first-class SSR §4
    technique, not degraded-mode only), then splits the remainder between
    the tool-driven and debate-with-literature paths.
    """
    assumptions_count = _assumptions_slice(total_count)
    tools_count, debate_with_lit_count = _split_tools_and_debate_counts(
        total_count - assumptions_count
    )
    return GenerationCounts(
        tools_count=tools_count,
        debate_with_lit_count=debate_with_lit_count,
        debate_only_count=0,
        assumptions_count=assumptions_count,
    )


def _lit_only_counts(total_count: int) -> GenerationCounts:
    """Allocate condition (c): the remainder to debate-with-literature."""
    assumptions_count = _assumptions_slice(total_count)
    return GenerationCounts(
        tools_count=0,
        debate_with_lit_count=total_count - assumptions_count,
        debate_only_count=0,
        assumptions_count=assumptions_count,
    )


def _no_lit_counts(total_count: int) -> GenerationCounts:
    """Allocate condition (b): the remainder to debate-only, degraded mode.

    Flagged so callers can attach an explicit "no literature" warning to
    every hypothesis. Reserves the same iterative-assumptions slice so the
    LLM-only path uses more than one generation technique (SSR §4).
    """
    assumptions_count = _assumptions_slice(total_count)
    return GenerationCounts(
        tools_count=0,
        debate_with_lit_count=0,
        debate_only_count=total_count - assumptions_count,
        assumptions_count=assumptions_count,
        is_degraded_mode=True,
    )


def _determine_generation_counts(
    state: WorkflowState,
    total_count: int,
    has_literature: bool,
    enable_tool_calling: bool,
) -> GenerationCounts:
    """Determine how many hypotheses to generate with each method."""
    strategy = _classify_generation_strategy(
        state, has_literature, enable_tool_calling
    )
    strategy_counts = {
        "dev_isolation": _dev_isolation_counts,
        "lit_and_tools": _lit_and_tools_counts,
        "lit_only": _lit_only_counts,
        "no_lit": _no_lit_counts,
    }
    return strategy_counts[strategy](total_count)


def _generation_log_case(counts: GenerationCounts) -> str:
    """Classify a resolved GenerationCounts for the log + start-progress steps.

    Shared by _log_generation_strategy and _emit_start_progress so both key
    off the same case label instead of repeating the same count comparisons.
    Derived from the actual counts (not the pre-count strategy) because a
    total_count=1 run of the "lit_and_tools" strategy collapses to
    tools-only, which - like the original if/elif chain - intentionally logs
    and emits nothing (case "none").

    Returns:
        One of "dev_isolation", "mixed" (both tools and debate-with-lit),
        "lit_only" (debate-with-lit alone), "degraded", or "none".
    """
    if counts.is_dev_isolation:
        return "dev_isolation"
    if counts.debate_with_lit_count > 0:
        return "mixed" if counts.tools_count > 0 else "lit_only"
    if counts.is_degraded_mode:
        return "degraded"
    return "none"


def _log_generation_strategy(
    counts: GenerationCounts, total_count: int
) -> None:
    """Log which generation strategy is being used."""
    case = _generation_log_case(counts)
    if case == "dev_isolation":
        logger.info(
            "Dev isolation mode: allocating all hypotheses"
            " to lit tools generation (no debate)"
        )
    elif case == "mixed":
        logger.info(
            "Condition (a): Generating %s hypotheses with literature review "
            "(%s tool-based + %s debate-with-literature)",
            total_count,
            counts.tools_count,
            counts.debate_with_lit_count,
        )
    elif case == "lit_only":
        logger.info(
            "Condition (c): Generating %s hypotheses with"
            " debate-with-literature",
            total_count,
        )
    elif case == "degraded":
        # One record, not the four (a decorative "=" * 80 border logged
        # twice around two message lines) this used to emit: the durable,
        # user-visible log panel renders every WARNING record verbatim.
        logger.warning(
            "No literature review tools available - generating"
            " hypotheses from model latent knowledge only"
        )


def _start_progress_message(
    case: str, counts: GenerationCounts, total_count: int
) -> tuple[str, dict[str, Any]]:
    """Build the generation-start progress message/extra-payload for a case."""
    if case == "dev_isolation":
        return (
            f"Generating {total_count} hypotheses with lit"
            " tools only (dev isolation mode)...",
            {"dev_isolation_mode": True},
        )
    if case == "mixed":
        return (
            f"Generating {total_count} hypotheses"
            f" ({counts.tools_count} tool-based"
            f" + {counts.debate_with_lit_count}"
            " debate-with-literature)...",
            {},
        )
    if case == "lit_only":
        return (
            f"Generating {total_count} hypotheses with"
            " debate-with-literature...",
            {},
        )
    # case == "degraded"
    return (
        f"Generating {counts.debate_only_count} hypotheses"
        " without literature review...",
        {
            "literature_review_available": False,
            "degraded_mode": True,
        },
    )


async def _emit_start_progress(
    state: WorkflowState, counts: GenerationCounts, total_count: int
) -> None:
    """Emit progress callback for generation start."""
    case = _generation_log_case(counts)
    if case == "none":
        return
    message, extra = _start_progress_message(case, counts, total_count)
    await emit_progress(
        state, "generation_start", message, PROGRESS_GENERATE_START, **extra
    )
