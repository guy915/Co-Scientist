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

    @property
    def strategy_counts(self) -> dict[str, int]:
        """Hypothesis counts in canonical strategy order, including zeroes."""
        return {
            "tools": self.tools_count,
            "debate_lit": self.debate_with_lit_count,
            "debate_only": self.debate_only_count,
            "assumptions": self.assumptions_count,
        }


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


# Generation strategy labels, including the
# only values an ablation caller may force via state["generation_strategy"]
# (validated upstream in run_setup._resolve_generation_strategy). Named here
# so the resolver and the classifier share one source of truth.
GENERATION_STRATEGY_LABELS: frozenset[str] = frozenset(
    {"dev_isolation", "lit_and_tools", "lit_only", "no_lit"}
)

# The forced labels that route hypotheses into the tool-based draft path, so
# they require tool-calling generation to be enabled. run_setup refuses these
# when it is not.
TOOLS_REQUIRING_STRATEGIES: frozenset[str] = frozenset(
    {"dev_isolation", "lit_and_tools"}
)


def _forced_generation_strategy(state: WorkflowState) -> str | None:
    """Return an ablation-forced strategy label, or None to derive it.

    Upstream validates the label; an unexpected value derives the ordinary
    strategy instead of forcing an unsupported allocation.
    """
    forced = state.get("generation_strategy")
    if isinstance(forced, str) and forced in GENERATION_STRATEGY_LABELS:
        return forced
    return None


def _determine_generation_counts(
    state: WorkflowState,
    total_count: int,
    has_literature: bool,
    enable_tool_calling: bool,
) -> GenerationCounts:
    """Allocate the batch once, honoring validated ablation overrides."""
    strategy = _forced_generation_strategy(state)
    if strategy is None:
        if state.get("dev_test_lit_tools_isolation", False):
            strategy = "dev_isolation"
        elif has_literature:
            strategy = "lit_and_tools" if enable_tool_calling else "lit_only"
        else:
            strategy = "no_lit"
    if strategy == "dev_isolation":
        return GenerationCounts(
            tools_count=total_count,
            debate_with_lit_count=0,
            debate_only_count=0,
            is_dev_isolation=True,
        )
    # Small batches stay intact; larger batches reserve a quarter for the
    # assumptions technique before splitting the remaining literature work.
    assumptions = total_count // 4 if total_count >= 4 else 0
    remaining = total_count - assumptions
    tools = max(1, remaining // 2) if strategy == "lit_and_tools" else 0
    debate = remaining - tools
    return GenerationCounts(
        tools_count=tools,
        debate_with_lit_count=debate if strategy != "no_lit" else 0,
        debate_only_count=debate if strategy == "no_lit" else 0,
        assumptions_count=assumptions,
        is_degraded_mode=strategy == "no_lit",
    )


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
