"""Environment-variable substitution for YAML tool configurations.

The registry merges its YAML tiers as raw dicts and then walks the merged
tree with ``substitute_env_vars()`` so every string leaf may reference
``${VAR}`` / ``${VAR:-default}`` placeholders. ``parse_bool_env()`` turns
the string flags such substitution produces (and ``COSCIENTIST_*``
environment flags elsewhere in the engine) into real booleans.
"""

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


def _substitute_env_vars_in_string(value: str) -> str:
    """Replace ${VAR} / ${VAR:-default} references in a single string.

    Args:
        value: String possibly containing ${VAR} or ${VAR:-default}
            placeholders.

    Returns:
        value with each placeholder replaced by the environment variable's
        value, its default, or an empty string (with a warning logged) when
        neither is available.
    """
    # Pattern: ${VAR} or ${VAR:-default}
    pattern = r"\$\{([^}:]+)(?::-([^}]*))?\}"

    def replacer(match: "re.Match[str]") -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        if default is not None:
            return default
        # Return empty string if no env var and no default
        logger.warning(
            "environment variable %s not set and no default provided", var_name
        )
        return ""

    return re.sub(pattern, replacer, value)


def _substitute_env_vars_in_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Recurse substitute_env_vars into every value of a dict."""
    return {k: substitute_env_vars(v) for k, v in value.items()}


def _substitute_env_vars_in_list(value: list[Any]) -> list[Any]:
    """Recurse substitute_env_vars into every item of a list."""
    return [substitute_env_vars(item) for item in value]


def substitute_env_vars(value: Any) -> Any:
    """Substitute environment variables in a value.

    Supports formats:
    - ${VAR} - required env var
    - ${VAR:-default} - env var with default

    Args:
        value: Value to process (string, dict, list, or other)

    Returns:
        Value with environment variables substituted
    """
    # Recurse into nested dicts/lists so ${VAR} substitution reaches every
    # string leaf in the merged YAML tree, not just top-level keys.
    if isinstance(value, str):
        return _substitute_env_vars_in_string(value)
    if isinstance(value, dict):
        return _substitute_env_vars_in_dict(value)
    if isinstance(value, list):
        return _substitute_env_vars_in_list(value)
    return value


def parse_bool_env(value: str) -> bool:
    """Parse a string value as boolean."""
    # Shared boolean-flag parser: used by the registry for `enabled` fields
    # that became plain strings when their YAML value was a substituted
    # ${VAR} (see ToolRegistry._parse_enabled_values in registry.py), and
    # imported by the cache package, prompts/loading.py, and
    # agents/generation/literature_review/run_config.py for
    # COSCIENTIST_* env flags. Anything not in this allowlist, including an
    # empty string, parses as False.
    return value.lower() in ("true", "1", "yes", "on")


def parse_timeout_env(env_var: str, default: float) -> float | None:
    """Parse a wall-clock-ceiling env var into seconds.

    Shared by the LLM and MCP per-call ceilings so the disable and
    fallback semantics cannot drift between them. Read from the
    environment on every call rather than cached, so tests and operators
    can change a ceiling without restarting the process.

    Args:
        env_var: Name of the environment variable to read.
        default: Ceiling to use when the variable is unset or invalid.

    Returns:
        The timeout in seconds, or None when it is disabled (a value of
        zero or less).
    """
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return default
    try:
        seconds = float(raw)
    except ValueError:
        logger.warning(
            "ignoring non-numeric %s=%r; using default %ss",
            env_var,
            raw,
            default,
        )
        return default
    return seconds if seconds > 0 else None


def parse_list_env(env_var: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse a comma-separated env var into a tuple, or fall back to default.

    Shared shape with ``parse_timeout_env``: read from the environment on
    every call rather than cached, so a preference list can be retuned in
    production without a restart.

    Args:
        env_var: Name of the environment variable to read.
        default: Tuple to use when the variable is unset.

    Returns:
        The trimmed, non-empty comma-separated items, in order. An
        explicitly empty (or whitespace-only) value is a deliberate
        opt-out -- it returns an empty tuple rather than ``default``, so a
        caller can turn a preference off without unsetting the variable.
    """
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())
