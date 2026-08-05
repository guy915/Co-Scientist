"""Merge-strategy helpers for layering YAML config overlays.

The registry merges the default, user, and custom configuration files as
raw dicts before parsing them into dataclasses. These helpers pick which
merge strategy the overlays declare and classify how a key present in
both dicts should combine under that strategy.
"""

from typing import Any


def _both_dicts(existing: Any, value: Any) -> bool:
    """True if both existing and value are dicts (mergeable, not replaced)."""
    return isinstance(value, dict) and isinstance(existing, dict)


def _both_lists_to_extend(existing: Any, value: Any, strategy: str) -> bool:
    """True if strategy is "extend" and both existing and value are lists."""
    return (
        strategy == "extend"
        and isinstance(value, list)
        and isinstance(existing, list)
    )


def _determine_merge_strategy(
    user: dict[str, Any] | None, custom: dict[str, Any] | None
) -> str:
    """Pick the merge_strategy declared by custom or user config settings.

    The overlay that actually sets settings.merge_strategy wins: custom is
    checked first (and used if present) so a custom config's choice
    overrides a user config's, even though custom is merged in after.

    Args:
        user: Parsed user config dict, or None if absent.
        custom: Parsed custom config dict, or None if absent.

    Returns:
        The declared merge_strategy, or "override" if neither config
        declares one.
    """
    for overlay in (custom, user):
        if overlay and "settings" in overlay:
            strategy: str = overlay["settings"].get(
                "merge_strategy", "override"
            )
            return strategy
    return "override"
