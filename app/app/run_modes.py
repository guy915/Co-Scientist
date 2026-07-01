"""Run-mode compatibility helpers.

The product now has one canonical run path. Older clients and persisted rows
may still use the former ``standard`` or ``advanced`` profile labels; both map
to the same default run mode.
"""

from __future__ import annotations

from typing import Any

from app.elo import DEFAULT_K_FACTOR

CANONICAL_RUN_MODE = "default"
RUN_MODE_PATTERN = "^(default|standard|advanced)$"
DEFAULT_RUN_TIER = "standard"
RUN_TIER_PATTERN = "^(express|standard|extended|ultra)$"
DEFAULT_RUN_FOCUS = "balance"
RUN_FOCUS_PATTERN = "^(prefer_evidence|balance|prefer_novelty|breakthrough)$"

LEGACY_RUN_MODE_ALIASES = {
    None: CANONICAL_RUN_MODE,
    "": CANONICAL_RUN_MODE,
    "default": CANONICAL_RUN_MODE,
    "standard": CANONICAL_RUN_MODE,
    "advanced": CANONICAL_RUN_MODE,
}

RUN_TIER_DEFAULTS: dict[str, dict[str, int]] = {
    "express": {
        "initial_hypotheses_count": 4,
        "max_iterations": 1,
        "evolution_max_count": 4,
        "tournament_pairs": 6,
        "evidence_count": 4,
        "literature_review_papers_count": 4,
    },
    DEFAULT_RUN_TIER: {
        "initial_hypotheses_count": 8,
        "max_iterations": 2,
        "evolution_max_count": 8,
        "tournament_pairs": 12,
        "evidence_count": 8,
        "literature_review_papers_count": 8,
    },
    "extended": {
        "initial_hypotheses_count": 12,
        "max_iterations": 3,
        "evolution_max_count": 12,
        "tournament_pairs": 20,
        "evidence_count": 12,
        "literature_review_papers_count": 12,
    },
    "ultra": {
        "initial_hypotheses_count": 16,
        "max_iterations": 4,
        "evolution_max_count": 16,
        "tournament_pairs": 32,
        "evidence_count": 16,
        "literature_review_papers_count": 16,
    },
}

RUN_MODE_DEFAULTS: dict[str, dict[str, int]] = {
    CANONICAL_RUN_MODE: RUN_TIER_DEFAULTS[DEFAULT_RUN_TIER],
}


def normalize_run_mode(run_mode: str | None = None) -> str:
    """Return the canonical run mode for current and legacy labels."""
    return LEGACY_RUN_MODE_ALIASES.get(run_mode, CANONICAL_RUN_MODE)


def normalize_run_tier(tier: str | None = None) -> str:
    """Return a supported run tier, defaulting to Standard."""
    if tier in RUN_TIER_DEFAULTS:
        return tier
    return DEFAULT_RUN_TIER


def normalize_run_focus(focus: str | None = None) -> str:
    """Return a supported research focus, defaulting to balanced."""
    if focus in {
            "prefer_evidence", "balance", "prefer_novelty", "breakthrough"
    }:
        return focus
    return DEFAULT_RUN_FOCUS


def clean_string_list(values: list[str] | None = None) -> list[str]:
    """Trim and drop empty strings from user-authored setup lists."""
    return [value.strip() for value in values or [] if value.strip()]


def setup_config(
    *,
    research_goal: str,
    requirements: list[str] | None = None,
    attributes: list[str] | None = None,
    criteria: list[str] | None = None,
    focus: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Build the durable setup block persisted inside run config JSON."""
    return {
        "goal": research_goal.strip(),
        "requirements": clean_string_list(requirements),
        "attributes": clean_string_list(attributes),
        "criteria": clean_string_list(criteria),
        "focus": normalize_run_focus(focus),
        "tier": normalize_run_tier(tier),
    }


def focus_guidance(focus: str | None) -> str:
    """Return prompt guidance for the selected Co-Scientist focus."""
    focus = normalize_run_focus(focus)
    if focus == "prefer_evidence":
        return (
            "Prefer evidence: prioritize literature-grounded, feasible, and "
            "well-supported hypotheses. Penalize speculative leaps unless "
            "they include a clear validation path.")
    if focus == "prefer_novelty":
        return ("Prefer novelty: reward hypotheses that introduce distinct "
                "mechanisms or experimental angles while preserving scientific "
                "plausibility and testability.")
    if focus == "breakthrough":
        return ("Breakthrough: actively explore high-impact, high-risk ideas. "
                "Surface uncertainties explicitly instead of over-penalizing "
                "speculative but testable mechanisms.")
    return ("Balance: weigh evidence support, novelty, feasibility, and "
            "testability evenly.")


def setup_guidance(setup: dict[str, Any] | None) -> str:
    """Render durable setup fields as prompt-ready run guidance."""
    if not isinstance(setup, dict):
        return ""
    lines = [
        "Run setup:",
        f"- Focus: {focus_guidance(str(setup.get('focus') or ''))}",
        f"- Tier: {normalize_run_tier(str(setup.get('tier') or ''))}",
    ]
    for title, key in (
        ("Requirements", "requirements"),
        ("Attributes", "attributes"),
        ("Criteria", "criteria"),
    ):
        values = clean_string_list(
            [str(value) for value in setup.get(key) or []])
        if values:
            lines.append(f"- {title}:")
            lines.extend(f"  - {value}" for value in values)
    return "\n".join(lines)


def resolved_run_config(
    run_mode: str | None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve run config defaults plus user-provided numeric overrides."""
    tier = None
    if overrides:
        tier = overrides.get("tier")
        setup = overrides.get("setup")
        if tier is None and isinstance(setup, dict):
            tier = setup.get("tier")
    tier = normalize_run_tier(tier if isinstance(tier, str) else None)
    base: dict[str, Any] = dict(RUN_TIER_DEFAULTS[tier])
    if overrides:
        for key, raw_value in overrides.items():
            if key == "setup":
                base[key] = raw_value
                continue
            if key == "tier":
                base[key] = normalize_run_tier(
                    raw_value if isinstance(raw_value, str) else None)
                continue
            if key == "focus":
                base[key] = normalize_run_focus(
                    raw_value if isinstance(raw_value, str) else None)
                continue
            if key == "enable_literature_review":
                base[key] = bool(raw_value)
                continue
            if raw_value is None:
                continue
            try:
                value = int(raw_value)
            except (ValueError, TypeError):
                continue
            if key in base and key != "k_factor":
                base[key] = max(base[key], value)
            else:
                base[key] = value
    base["tier"] = tier
    if "focus" not in base:
        setup = base.get("setup")
        if isinstance(setup, dict):
            base["focus"] = normalize_run_focus(setup.get("focus"))
        else:
            base["focus"] = DEFAULT_RUN_FOCUS
    base.setdefault("k_factor", DEFAULT_K_FACTOR)
    base.setdefault("enable_literature_review", True)
    return base
