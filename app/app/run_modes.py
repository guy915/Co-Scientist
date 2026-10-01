"""Faithful run-tier and focus configuration with legacy normalization."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from app.elo import DEFAULT_K_FACTOR
from app.run_modes_attributes import (
    _default_attributes as _default_attributes,
)
from app.run_modes_attributes import (
    attribute_display_strings as attribute_display_strings,
)
from app.run_modes_attributes import (
    attribute_names as attribute_names,
)
from app.run_modes_attributes import clean_attributes_list
from app.run_modes_criteria import (
    _default_criteria as _default_criteria,
)
from app.run_modes_criteria import (
    clean_criteria_list as clean_criteria_list,
)
from app.run_modes_criteria import (
    criteria_display_strings as criteria_display_strings,
)

# Tier controls run size/depth; focus controls ranking emphasis. The
# *_PATTERN regexes are used by the API's pydantic Field validation, so
# invalid values 422 at the edge while None falls through to the defaults.
DEFAULT_RUN_TIER = "standard"
RUN_TIER_PATTERN = "^(express|standard|extended|ultra)$"
DEFAULT_RUN_FOCUS = "balance"
RUN_FOCUS_VALUES: tuple[str, ...] = (
    "prefer_evidence",
    "balance",
    "prefer_novelty",
    "breakthrough",
)
RUN_FOCUS_PATTERN = "^(" + "|".join(RUN_FOCUS_VALUES) + ")$"

# Client-independent planning baseline. The chat UI infers a richer,
# domain-tailored spec and sends it explicitly; when a run is created without
# one (a direct API call, a seeded demo), setup_config falls back to these so
# every run reaches the engine with sensible planning guidance.
DEFAULT_REQUIREMENTS: tuple[str, ...] = (
    "Prioritize mechanistic novelty, plausibility, and direct testability.",
    "Retrieve broader literature evidence and preserve competing mechanisms.",
    "Use tournament ranking and evolution before final synthesis.",
)
# DEFAULT_ATTRIBUTES, clean_attributes_list, attribute_display_strings, and
# attribute_names live in run_modes_attributes (R12-5: the attributes
# field's structured axis shape and back-compat), imported above and
# re-exported for existing importers.
# DEFAULT_CRITERIA, clean_criteria_list, and criteria_display_strings live in
# run_modes_criteria (R12-4: the criteria field's named-setting shape and
# back-compat), imported above and re-exported for existing importers.

# Reconstructed compute envelopes; every knob scales up together from express
# to ultra. Google verifies that deeper tiers do more work, but not these exact
# numbers; provenance records them as reconstructed. resolved_run_config starts
# from the selected tier and lets explicit user overrides raise (never lower)
# these values.
# ``max_llm_calls`` is a runaway backstop, not a work allowance: it is sized
# well above what a healthy run of each tier spends, so it never truncates
# real science, and only fires when a run stops converging. It exists because
# ``max_iterations`` was otherwise the sole termination bound, and iterations
# only advance on work tasks -- a run looping on maintenance work had no
# ceiling at all. Calls (rather than the Budget's wall-clock ceiling) are the
# right meter here: they measure work actually done, so an interrupted run is
# not penalized for the hours it sat wedged, whereas ``elapsed_s`` counts from
# the original ``start_time`` and would terminate a resumed run instantly.
#
# ``max_ideas`` and ``max_matches_per_idea`` are the Supervisor listing's own
# two named loop predicates (``01-supervisor.md`` L17). They were implemented
# in ``scheduling.policy_checks`` from the start and left unset on every real
# run, so the loop actually terminated on ``max_iterations`` -- a predicate
# the listing does not name. Both are sized here from the *same* tier numbers
# they bound, one row above their own steady state:
#   max_ideas            > initial_hypotheses_count
#                          + evolution_max_count * max_iterations
#   max_matches_per_idea > 2 * tournament_pairs * max_iterations
#                          / initial_hypotheses_count
# The doubling is because a judged match increments both participants'
# tallies, and the initial pool is the denominator because it is the smallest
# the run ever divides by (evolution only grows it, which lowers the average).
# Sizing either at or below that steady state is the trap: the ceiling is
# checked *above* every productive task, so an undersized value stops the run
# immediately after its first tournament and reports it as a spent match
# budget rather than as a misconfiguration. Pinned by
# ``tests/test_run_modes_supervisor_budget.py``.
RUN_TIER_DEFAULTS: dict[str, dict[str, int]] = {
    "express": {
        "initial_hypotheses_count": 4,
        "max_iterations": 1,
        "evolution_max_count": 4,
        "tournament_pairs": 6,
        "evidence_count": 4,
        "max_llm_calls": 1200,
        "max_ideas": 12,
        "max_matches_per_idea": 4,
    },
    DEFAULT_RUN_TIER: {
        "initial_hypotheses_count": 8,
        "max_iterations": 2,
        "evolution_max_count": 8,
        "tournament_pairs": 12,
        "evidence_count": 8,
        "max_llm_calls": 2500,
        "max_ideas": 32,
        "max_matches_per_idea": 7,
    },
    "extended": {
        "initial_hypotheses_count": 12,
        "max_iterations": 3,
        "evolution_max_count": 12,
        "tournament_pairs": 20,
        "evidence_count": 12,
        "max_llm_calls": 7000,
        "max_ideas": 60,
        "max_matches_per_idea": 11,
    },
    "ultra": {
        "initial_hypotheses_count": 16,
        "max_iterations": 4,
        "evolution_max_count": 16,
        "tournament_pairs": 32,
        "evidence_count": 16,
        "max_llm_calls": 14000,
        "max_ideas": 96,
        "max_matches_per_idea": 17,
    },
}


# Normalization is deliberately forgiving: unknown or missing values fall
# back to the default rather than raising, so persisted rows from older
# builds and loosely-validated callers keep working.
def normalize_run_tier(tier: str | None = None) -> str:
    """Return a supported run tier, migrating legacy stored tiers.

    Runs created during the two-tier period stored 'advanced' (the deep mode,
    whose envelope matches 'ultra'); map it forward so those rows keep working.
    """
    if tier in RUN_TIER_DEFAULTS:
        return tier
    if tier == "advanced":
        return "ultra"
    if tier == "default":
        return "standard"
    return DEFAULT_RUN_TIER


def normalize_run_focus(focus: str | None = None) -> str:
    """Return a supported research focus, defaulting to balanced."""
    if focus in RUN_FOCUS_VALUES:
        return focus
    return DEFAULT_RUN_FOCUS


def clean_string_list(values: list[str] | None = None) -> list[str]:
    """Trim and drop empty strings from user-authored setup lists."""
    return [value.strip() for value in values or [] if value.strip()]


@dataclasses.dataclass(frozen=True)
class PlanningLists:
    """The user-authored planning lists a run's setup block is built from.

    All three are optional: a caller that omits one (a direct API call, a
    seeded demo) gets the client-independent baseline instead.

    Attributes:
        requirements: What the run's hypotheses must satisfy.
        attributes: The qualities a good hypothesis should show -- either
            the legacy free-prose strings or the structured axis shape
            (see ``clean_attributes_list``).
        criteria: The axes hypotheses are judged on -- either the legacy
            free-prose strings or the ``{"name", "value"}`` pair shape
            (see ``clean_criteria_list``).
    """

    requirements: list[str] | None = None
    attributes: list[Any] | None = None
    criteria: list[Any] | None = None


def setup_config(
    *,
    research_goal: str,
    lists: PlanningLists | None = None,
    focus: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Build the durable setup block persisted inside run config JSON.

    Callers that omit the planning lists (a direct API call, a seeded demo)
    fall back to the client-independent planning baseline so the engine
    always receives guidance regardless of which client created the run.

    Args:
        research_goal: The run's research goal.
        lists: The user-authored requirements/attributes/criteria.
        focus: Requested research focus; normalized, defaulting to balanced.
        tier: Requested run tier; normalized, defaulting to standard.

    Returns:
        The setup block persisted inside the run's config JSON.
    """
    lists = lists or PlanningLists()
    # `or` also covers lists that become empty after cleaning, so a caller
    # sending only blank strings still gets the baseline defaults.
    return {
        "goal": research_goal.strip(),
        "requirements": clean_string_list(lists.requirements)
        or list(DEFAULT_REQUIREMENTS),
        "attributes": clean_attributes_list(lists.attributes)
        or _default_attributes(),
        "criteria": clean_criteria_list(lists.criteria) or _default_criteria(),
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
            "they include a clear validation path."
        )
    if focus == "prefer_novelty":
        return (
            "Prefer novelty: reward hypotheses that introduce distinct "
            "mechanisms or experimental angles while preserving scientific "
            "plausibility and testability."
        )
    if focus == "breakthrough":
        return (
            "Breakthrough: actively explore high-impact, high-risk ideas. "
            "Surface uncertainties explicitly instead of over-penalizing "
            "speculative but testable mechanisms."
        )
    return (
        "Balance: weigh evidence support, novelty, feasibility, and "
        "testability evenly."
    )


def _setup_field_lines(title: str, values: list[str]) -> list[str]:
    """Render one setup list field as bullet lines, or nothing if empty.

    Args:
        title: Human-readable label for the field, e.g. 'Requirements'.
        values: The field's already-cleaned display strings.

    Returns:
        Bullet-point lines for the field, or an empty list when there are
        no values to show.
    """
    if not values:
        return []
    lines = [f"- {title}:"]
    lines.extend(f"  - {value}" for value in values)
    return lines


# Attributes and criteria each get their own back-compat-aware coercion
# since their stored shape may be the legacy free-prose list or a later
# structured shape (R12-5, R12-4); requirements is always plain strings and
# falls through to the generic branch below.
_SETUP_DISPLAY_COERCIONS: dict[str, Callable[[Any], list[str]]] = {
    "attributes": attribute_display_strings,
    "criteria": criteria_display_strings,
}


def _setup_field_values(setup: dict[str, Any], key: str) -> list[str]:
    """Return one setup list field's raw JSON value as display strings."""
    coerce = _SETUP_DISPLAY_COERCIONS.get(key)
    if coerce is not None:
        return coerce(setup.get(key))
    return clean_string_list([str(v) for v in setup.get(key) or []])


def setup_guidance(setup: dict[str, Any] | None) -> str:
    """Render durable setup fields as prompt-ready run guidance."""
    # Setup blocks come from persisted config JSON, so shape is not
    # guaranteed; a non-dict just contributes no guidance.
    if not isinstance(setup, dict):
        return ""
    focus = focus_guidance(str(setup.get("focus") or ""))
    tier = normalize_run_tier(str(setup.get("tier") or ""))
    lines = [
        "Run setup:",
        f"- Focus: {focus}",
        f"- Run type: {tier}",
    ]
    for title, key in (
        ("Requirements", "requirements"),
        ("Attributes", "attributes"),
        ("Criteria", "criteria"),
    ):
        lines.extend(_setup_field_lines(title, _setup_field_values(setup, key)))
    return "\n".join(lines)


def _apply_numeric_override(
    base: dict[str, Any], key: str, raw_value: Any
) -> None:
    """Coerce and merge a numeric knob override into `base`, in place.

    Non-coercible values are dropped rather than failing run creation.
    Overrides may only raise a tier baseline, never lower it, so picking a
    bigger tier is never undone by a small knob.

    Args:
        base: The run config being assembled; mutated with the resolved key.
        key: The numeric knob's key, e.g. 'max_iterations'.
        raw_value: The raw override value, as received from the caller.
    """
    if raw_value is None:
        return
    try:
        value = int(raw_value)
    except (ValueError, TypeError):
        return
    base[key] = max(base[key], value) if key in base else value


def _apply_verbatim_override(
    base: dict[str, Any], key: str, raw_value: Any
) -> None:
    """Carry an override through verbatim, in place."""
    base[key] = raw_value


def _apply_bool_override(
    base: dict[str, Any], key: str, raw_value: Any
) -> None:
    """Coerce a connector/feature toggle to bool and merge it, in place."""
    base[key] = bool(raw_value)


def _apply_tier_override(
    unused_base: dict[str, Any], unused_key: str, unused_raw_value: Any
) -> None:
    """No-op: tier is resolved once, before overrides are applied.

    The final tier assignment in `resolved_run_config` always wins, so this
    skips the numeric path (`int("standard")` would raise anyway).
    """


def _apply_focus_override(
    base: dict[str, Any], unused_key: str, raw_value: Any
) -> None:
    """Normalize and merge the focus override into `base`, in place."""
    base["focus"] = normalize_run_focus(
        raw_value if isinstance(raw_value, str) else None
    )


# Valid explicit values for the "llm_backend" override; any other raw value
# (including None) resolves to None, letting offline_mode() decide at run
# time -- see _apply_llm_backend_override.
_LLM_BACKEND_VALUES = ("offline", "real")


def _apply_llm_backend_override(
    base: dict[str, Any], unused_key: str, raw_value: Any
) -> None:
    """Normalize and merge the LLM backend override into `base`, in place.

    A caller (e.g. the demo seeder) may pin a run to "offline" or "real",
    bypassing the process-level ``offline_mode()`` predicate for that run.
    An unrecognized or absent value resolves to None, the "let the caller
    decide at run time" default.
    """
    base["llm_backend"] = (
        raw_value if raw_value in _LLM_BACKEND_VALUES else None
    )


# Per-key override handlers; any key without a dedicated handler is a
# numeric knob and falls back to `_apply_numeric_override`. Every handler
# shares `_apply_numeric_override`'s (base, key, raw_value) signature so the
# dispatcher below can call whichever one it finds uniformly.
_OVERRIDE_HANDLERS: dict[str, Callable[[dict[str, Any], str, Any], None]] = {
    "setup": _apply_verbatim_override,
    "tier": _apply_tier_override,
    "focus": _apply_focus_override,
    # Provider flag of a bring-your-own-key run (the provider name only,
    # never the key). Must survive every config round-trip verbatim:
    # resolve_offline_backend reads it to keep the run real-backed, and
    # the numeric fallback would silently drop a string value.
    "byok_provider": _apply_verbatim_override,
    "enable_literature_review": _apply_bool_override,
    "llm_backend": _apply_llm_backend_override,
    "enable_web_search": _apply_bool_override,
    # Ablation seams (evaluations.ablation_driver). enable_meta_review gates
    # the engine's periodic meta-review cadence; generation_strategy is a
    # string label carried verbatim (the numeric fallback would int() it and
    # drop it silently), validated engine-side.
    "enable_meta_review": _apply_bool_override,
    "generation_strategy": _apply_verbatim_override,
    # A discovery run's whole specification: what to optimize, how to
    # measure it, and the program to start from. Verbatim because it is a
    # dict -- the numeric fallback cannot coerce one and would drop it
    # silently, which turns "start a discovery run" into an ordinary
    # hypothesis run with no error anywhere.
    "discovery": _apply_verbatim_override,
}


def _apply_run_config_override(
    base: dict[str, Any], key: str, raw_value: Any
) -> None:
    """Merge one (key, raw_value) override pair into `base`, in place.

    Args:
        base: The run config being assembled; mutated with the resolved key.
        key: The override key, e.g. 'focus' or a numeric knob name.
        raw_value: The raw override value, as received from the caller.
    """
    handler = _OVERRIDE_HANDLERS.get(key, _apply_numeric_override)
    handler(base, key, raw_value)


def _resolve_tier_override(overrides: dict[str, Any] | None) -> str:
    """Resolve the run tier from an explicit override or the setup block.

    A top-level 'tier' key wins; otherwise fall back to the tier recorded
    in the durable setup block, then to the default.
    """
    tier = None
    if overrides:
        tier = overrides.get("tier")
        setup = overrides.get("setup")
        if tier is None and isinstance(setup, dict):
            tier = setup.get("tier")
    return normalize_run_tier(tier if isinstance(tier, str) else None)


def _ensure_focus_default(base: dict[str, Any]) -> None:
    """Guarantee a focus key in `base`, in place.

    Prefers the explicit override (already applied by the caller), then the
    setup block's focus, then the global default.
    """
    if "focus" in base:
        return
    setup = base.get("setup")
    if isinstance(setup, dict):
        base["focus"] = normalize_run_focus(setup.get("focus"))
    else:
        base["focus"] = DEFAULT_RUN_FOCUS


def resolved_run_config(
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve run config defaults plus user-provided numeric overrides."""
    # Resolve the tier first since it selects the numeric baseline.
    tier = _resolve_tier_override(overrides)
    # Copy so tier defaults are never mutated across runs.
    base: dict[str, Any] = dict(RUN_TIER_DEFAULTS[tier])
    if overrides:
        for key, raw_value in overrides.items():
            _apply_run_config_override(base, key, raw_value)
    base["tier"] = tier
    _ensure_focus_default(base)
    # Elo K-factor and literature review are always present in the final
    # config so downstream consumers need no fallbacks of their own.
    base.setdefault("k_factor", DEFAULT_K_FACTOR)
    base.setdefault("enable_literature_review", True)
    # "offline" | "real" | None; None means "let offline_mode() decide at run
    # time" (resolved by sync_engine_llm_backend on the durable bootstrap), so
    # a plain dict without this key still reads correctly.
    base.setdefault("llm_backend", None)
    # Web search is on by default, matching the literature stack. It is a
    # no-op unless the MCP server actually offers the tool.
    base.setdefault("enable_web_search", True)
    # Periodic meta-review on by default; an ablation arm sets it False.
    base.setdefault("enable_meta_review", True)
    return base
