"""Run-config to engine-capability translation for the opts boundary.

The five capability opts that decide how much depth a run may buy, plus
the two ablation seams (periodic meta-review, forced generation strategy).
Each resolves a run's durable config against the tier table (and the
literature-review kill switch), and the engine treats every one as a
request it may still refuse. Split from ``opts.py`` on that module's
500-line cap; ``opts.py`` re-exports every name so callers and tests that
import from ``app.engine_adapter.opts`` are unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from app.run_modes import normalize_run_tier


def _resolve_literature_review_toggle(cfg: dict[str, Any]) -> bool:
    """Resolve the per-run literature-review toggle, honoring the kill switch.

    Literature grounding defaults on but is user-controlled per run (the
    PubMed connector toggle in the composer). The engine still degrades
    gracefully to LLM-only if MCP is unreachable, so a down MCP never breaks
    a run. FORCE_LITERATURE_REVIEW=0 is a hard kill switch for tests/dev
    that must run without it, regardless of the per-run setting.
    """
    enable_literature_review = bool(cfg.get("enable_literature_review", True))
    if os.getenv("FORCE_LITERATURE_REVIEW") == "0":
        enable_literature_review = False
    return enable_literature_review


# Tiers whose compute envelope funds the agentic draft path. Tool-calling
# generation spends one LLM round-trip per tool call and carries every
# prior tool result into the next prompt, so a single hypothesis costs
# roughly nine calls on prompts that grow past 12k tokens -- and it runs
# per hypothesis, per cycle. On express and standard that one technique
# outweighed every other phase combined, which is not a trade those tiers
# are offering: they promise a fast, cheap answer. The deep tiers are
# where a scientist has already asked for depth over turnaround.
_TOOL_CALLING_GENERATION_TIERS: frozenset[str] = frozenset(
    {"extended", "ultra"}
)


def _resolve_tool_calling_generation_toggle(cfg: dict[str, Any]) -> bool:
    """Decide whether this run funds the agentic literature-draft path.

    Args:
        cfg: The run's resolved config; ``resolved_run_config`` guarantees
            a normalized ``tier``.

    Returns:
        True only for the deep tiers. The engine treats this as an
        explicit request and still refuses it where the literature tools
        or MCP are unavailable, so a True here is a ceiling, not a
        guarantee.
    """
    return normalize_run_tier(cfg.get("tier")) in (
        _TOOL_CALLING_GENERATION_TIERS
    )


# Tiers whose compute envelope funds an executed simulation review. The
# same reasoning as the agentic draft path above, and the same answer: a
# tool loop runs per hypothesis, so its cost is a product with the pool
# size rather than a fixed addition, and express and standard promise a
# fast cheap answer instead of depth.

# Two things make the per-hypothesis figure a floor rather than the
# cost. A turn that comes back answerless is retried at a raised budget
# and then with thinking off, so one turn can be up to three completions
# (`llm.attempts.escalation.BudgetEscalation`). And the maturity scheduler
# keys on the full review alone, so a hypothesis whose *full* review
# fails re-issues its simulation review -- tool loop included -- on
# every later iteration.
_SIMULATION_EXECUTION_TIERS: frozenset[str] = frozenset({"extended", "ultra"})


def _resolve_simulation_execution_toggle(cfg: dict[str, Any]) -> bool:
    """Decide whether this run's simulation review may execute code.

    Args:
        cfg: The run's resolved config; ``resolved_run_config`` guarantees
            a normalized ``tier``.

    Returns:
        True only for the deep tiers. A ceiling, not a guarantee: the
        engine refuses it for the offline backend, and the review itself
        falls back to mental simulation on a host with no sandbox.
    """
    return normalize_run_tier(cfg.get("tier")) in _SIMULATION_EXECUTION_TIERS


# Tiers whose compute envelope funds an accuracy review of the terminal
# research overview. The same reasoning as the executed simulation review
# above: extra LLM calls on top of a call every run already pays for, so
# the deep tiers only.
_OVERVIEW_REVIEW_TIERS: frozenset[str] = frozenset({"extended", "ultra"})


def _resolve_overview_review_toggle(cfg: dict[str, Any]) -> bool:
    """Decide whether this run's research overview is accuracy-reviewed.

    Args:
        cfg: The run's resolved config; ``resolved_run_config`` guarantees
            a normalized ``tier``.

    Returns:
        True only for the deep tiers. A ceiling, not a guarantee: the
        engine refuses it for the offline backend.
    """
    return normalize_run_tier(cfg.get("tier")) in _OVERVIEW_REVIEW_TIERS


def _resolve_meta_review_toggle(cfg: dict[str, Any]) -> bool:
    """Resolve whether the periodic meta-review cadence may fire.

    Defaults on; only an explicit ``enable_meta_review=False`` in the run
    config disables it, mirroring the ``enable_web_search`` /
    ``enable_literature_review`` connector toggles. Unlike the tier-shaped
    toggles above this has no compute-envelope gate: meta-review is an
    ordinary model call every tier already runs. The engine gates only its
    scheduler cadence check on this
    (``scheduling.policy_cadence._check_meta_review_cadence``); the EVOLVE
    branch still enters the meta_review node, so a False here removes the
    *periodic* system-wide feedback, not the node.

    Args:
        cfg: The run's resolved config.

    Returns:
        Whether the periodic meta-review cadence is enabled for this run.
    """
    return cfg.get("enable_meta_review", True) is not False


def _resolve_generation_strategy(cfg: dict[str, Any]) -> str:
    """Resolve a forced generation-strategy label, or "" to derive the mix.

    An ablation arm may pin the generation strategy rather than let the
    engine derive the debate/tool-based mix from literature/tool
    availability. Passed through verbatim as a string; the engine is the
    validator (``run_setup._resolve_generation_strategy`` honors only a
    known ``coordinator_strategy`` label and refuses a tools-requiring one
    when tool-calling generation is off), so an unknown value degrades to
    deriving rather than erroring here.

    Args:
        cfg: The run's resolved config.

    Returns:
        The requested strategy label, or "" when none was set.
    """
    value = cfg.get("generation_strategy")
    return value if isinstance(value, str) else ""


def _apply_capability_opts(
    initial_opts: dict[str, Any], cfg: dict[str, Any]
) -> None:
    """Set the opts that decide how much depth a run may buy, plus ablations.

    Four are resolved to a yes or no here, because the engine treats
    each as a request it may still refuse. The fifth is the tier itself,
    passed verbatim: which tiers fund the literature review's
    deep-research phase is stated once, in the engine's
    ``research_adapter``, and a second copy of that list on this side is
    how the two drift apart. The last two are ablation seams
    (``evaluations.ablation_driver``): the periodic meta-review gate and a
    forced generation strategy, both defaulting to current behaviour.
    """
    initial_opts["enable_literature_review_node"] = (
        _resolve_literature_review_toggle(cfg)
    )
    initial_opts["enable_tool_calling_generation"] = (
        _resolve_tool_calling_generation_toggle(cfg)
    )
    initial_opts["enable_simulation_execution"] = (
        _resolve_simulation_execution_toggle(cfg)
    )
    initial_opts["enable_overview_review"] = _resolve_overview_review_toggle(
        cfg
    )
    initial_opts["research_tier"] = normalize_run_tier(cfg.get("tier"))
    initial_opts["enable_meta_review"] = _resolve_meta_review_toggle(cfg)
    initial_opts["generation_strategy"] = _resolve_generation_strategy(cfg)
