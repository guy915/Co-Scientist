"""Allocate generation strategies and report their resolved counts."""

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

GENERATION_STRATEGY_LABELS = frozenset(
    {"dev_isolation", "lit_and_tools", "lit_only", "no_lit"}
)
TOOLS_REQUIRING_STRATEGIES = frozenset({"dev_isolation", "lit_and_tools"})


@dataclass
class GenerationCounts:
    """Hypothesis allocation, including serialized durable-run mode flags."""

    tools_count: int
    debate_with_lit_count: int
    debate_only_count: int
    assumptions_count: int = 0
    is_dev_isolation: bool = False
    is_degraded_mode: bool = False

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
    """Require successful literature review and live MCP access."""
    return (
        articles_with_reasoning is not None
        and articles_with_reasoning != LITERATURE_REVIEW_FAILED
        and mcp_available
    )


def _forced_generation_strategy(state: WorkflowState) -> str | None:
    """Use a recognized ablation override, otherwise derive the strategy."""
    forced = state.get("generation_strategy")
    if isinstance(forced, str) and forced in GENERATION_STRATEGY_LABELS:
        return forced
    return None


def _classify_generation_strategy(
    state: WorkflowState, has_literature: bool, enable_tool_calling: bool
) -> str:
    """Resolve isolation, literature with tools, literature, or latent-only."""
    if state.get("dev_test_lit_tools_isolation", False):
        return "dev_isolation"
    if has_literature:
        return "lit_and_tools" if enable_tool_calling else "lit_only"
    return "no_lit"


def _determine_generation_counts(
    state: WorkflowState,
    total_count: int,
    has_literature: bool,
    enable_tool_calling: bool,
) -> GenerationCounts:
    """Reserve assumptions for batches of four, then allocate the remainder."""
    strategy = _forced_generation_strategy(
        state
    ) or _classify_generation_strategy(
        state, has_literature, enable_tool_calling
    )
    if strategy == "dev_isolation":
        return GenerationCounts(total_count, 0, 0, is_dev_isolation=True)

    assumptions = total_count // 4 if total_count >= 4 else 0
    remainder = total_count - assumptions
    tools = max(1, remainder // 2) if strategy == "lit_and_tools" else 0
    return GenerationCounts(
        tools_count=tools,
        debate_with_lit_count=(
            remainder - tools
            if strategy in {"lit_and_tools", "lit_only"}
            else 0
        ),
        debate_only_count=remainder if strategy == "no_lit" else 0,
        assumptions_count=assumptions,
        is_degraded_mode=strategy == "no_lit",
    )


async def _report_generation_start(
    state: WorkflowState, counts: GenerationCounts, total_count: int
) -> None:
    """Log and emit the same resolved allocation once."""
    extra: dict[str, Any] = {}
    if counts.is_dev_isolation:
        logger.info(
            "Dev isolation mode: allocating all hypotheses"
            " to lit tools generation (no debate)"
        )
        message = (
            f"Generating {total_count} hypotheses with lit"
            " tools only (dev isolation mode)..."
        )
        extra = {"dev_isolation_mode": True}
    elif counts.debate_with_lit_count > 0:
        message = _report_literature_start(counts, total_count)
    elif counts.is_degraded_mode:
        logger.warning(
            "No literature review tools available - generating"
            " hypotheses from model latent knowledge only"
        )
        message = (
            f"Generating {counts.debate_only_count} hypotheses"
            " without literature review..."
        )
        extra = {"literature_review_available": False, "degraded_mode": True}
    else:
        # A one-hypothesis lit-and-tools batch has historically emitted
        # no start event; keep that lifecycle contract.
        return
    await emit_progress(
        state, "generation_start", message, PROGRESS_GENERATE_START, **extra
    )


def _report_literature_start(counts: GenerationCounts, total_count: int) -> str:
    """Log the literature-aware mix and return its progress message."""
    if counts.tools_count > 0:
        logger.info(
            "Condition (a): Generating %s hypotheses with literature review "
            "(%s tool-based + %s debate-with-literature)",
            total_count,
            counts.tools_count,
            counts.debate_with_lit_count,
        )
        return (
            f"Generating {total_count} hypotheses"
            f" ({counts.tools_count} tool-based"
            f" + {counts.debate_with_lit_count} debate-with-literature)..."
        )
    logger.info(
        "Condition (c): Generating %s hypotheses with debate-with-literature",
        total_count,
    )
    return f"Generating {total_count} hypotheses with debate-with-literature..."
