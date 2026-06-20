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

LEGACY_RUN_MODE_ALIASES = {
    None: CANONICAL_RUN_MODE,
    "": CANONICAL_RUN_MODE,
    "default": CANONICAL_RUN_MODE,
    "standard": CANONICAL_RUN_MODE,
    "advanced": CANONICAL_RUN_MODE,
}

RUN_MODE_DEFAULTS: dict[str, dict[str, int]] = {
    CANONICAL_RUN_MODE: {
        "initial_hypotheses_count": 8,
        "max_iterations": 2,
        "evolution_max_count": 8,
        "tournament_pairs": 12,
        "evidence_count": 8,
    },
}


def normalize_run_mode(run_mode: str | None = None) -> str:
    """Return the canonical run mode for current and legacy labels."""
    return LEGACY_RUN_MODE_ALIASES.get(run_mode, CANONICAL_RUN_MODE)


def resolved_run_config(
    run_mode: str | None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Resolve run config defaults plus user-provided numeric overrides."""
    base = dict(RUN_MODE_DEFAULTS[normalize_run_mode(run_mode)])
    if overrides:
        for key, raw_value in overrides.items():
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
    base.setdefault("k_factor", DEFAULT_K_FACTOR)
    return base
