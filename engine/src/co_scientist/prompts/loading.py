"""Prompt loading, variable substitution, and shared prompt assembly.

All prompt templates are stored as markdown files in the templates/
subdirectory of this package.
"""

import functools
import logging
import re
from pathlib import Path
from typing import Any

from co_scientist.prompts._common import PromptSections
from co_scientist.schemas import get_schema_for_prompt

logger = logging.getLogger(__name__)

# Resolved relative to this module's own location so it works whether the
# package is installed editable (pip install -e) or from a built wheel; the
# templates/ directory is also declared as package-data for the latter case.
_PROMPTS_DIR = Path(__file__).parent / "templates"

# Matches a "{{variable}}" template placeholder; compiled once here rather
# than on every substitute_variables() call (one per rendered prompt).
_VARIABLE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def load_prompt(
    prompt_name: str, variables: dict[str, Any] | None = None
) -> str:
    """Load a prompt from a markdown file and substitute variables.

    Args:
        prompt_name: Name of the prompt file (without .md extension)
        variables: Dictionary of variables to substitute
            (e.g., {"research_goal": "..."})

    Returns:
        Formatted prompt string with variables substituted

    Example:
        >>> load_prompt(
        ...     "generation",
        ...     {"research_goal": "Cure cancer", "hypotheses_count": 5})
    """
    prompt_template = _read_prompt_template(prompt_name)

    # Substitute variables if provided
    # Placeholders use {{name}} syntax (see substitute_variables below);
    # prompts with no variables (e.g. static instruction blocks) simply
    # skip this step.
    if variables:
        prompt_template = substitute_variables(prompt_template, variables)

    return prompt_template


@functools.cache
def _read_prompt_template(prompt_name: str) -> str:
    """Read a bundled prompt template, cached for the process lifetime.

    Template files are immutable package data, and prompt getters run once
    per hypothesis / tournament pair inside gathered loops — the cache keeps
    that to one disk read per file instead of one per LLM call.
    """
    prompt_path = _PROMPTS_DIR / f"{prompt_name}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    return prompt_path.read_text()


def load_prompt_with_schema(
    prompt_name: str, variables: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Load a prompt and its associated JSON schema.

    Args:
        prompt_name: Name of the prompt file (without .md extension)
        variables: Dictionary of variables to substitute
            (e.g., {"research_goal": "..."})

    Returns:
        Tuple of (formatted prompt string, JSON schema dict or None)

    Example:
        >>> prompt, schema = load_prompt_with_schema(
        ...     "generation", {"research_goal": "Cure cancer"})
    """
    prompt = load_prompt(prompt_name, variables)
    # get_schema_for_prompt does a name-keyed lookup (see schemas.py) and
    # returns None for prompt names with no registered schema; callers pass
    # that None straight through to the LLM call to request a schema-less
    # (free-form or conversational) response.
    schema = get_schema_for_prompt(prompt_name)
    return prompt, schema


def substitute_variables(template: str, variables: dict[str, Any]) -> str:
    """Substitute {{variable}} placeholders in a template string.

    Args:
        template: Template string with {{variable}} placeholders
        variables: Dictionary mapping variable names to values

    Returns:
        Template with all variables substituted

    Example:
        >>> substitute_variables("Hello {{name}}", {"name": "World"})
        "Hello World"
    """

    def replacer(match: "re.Match[str]") -> str:
        var_name = match.group(1).strip()
        # Unresolved variables render as a visible {{MISSING:name}} marker
        # rather than silently collapsing to an empty string, so a typo'd
        # or forgotten variable is obvious in the saved/logged prompt text.
        value = variables.get(var_name, f"{{{{MISSING:{var_name}}}}}")
        return str(value)

    # Replace {{variable}} patterns
    return _VARIABLE_PATTERN.sub(replacer, template)


# Domain variable injection from YAML config
# Lets a deployment's tools config (e.g. config/*.yaml, see the
# domain-customization docs) inject domain-specific wording into prompts
# without changing the .md templates themselves; every domain_* variable
# below is a template placeholder used by one or more of the getters
# further down this file.


def _resolve_default_tool_registry() -> Any | None:
    """Resolve the process-default tool registry, or None if unavailable."""
    try:
        from co_scientist.config import (
            get_tool_registry,
        )

        return get_tool_registry()
    except Exception:
        return None


def _get_domain_variables(tool_registry: Any | None = None) -> dict[str, str]:
    """Get domain-specific prompt variables from tool registry config.

    Returns dict with domain_context, domain_generation_guidance,
    domain_review_guidance, domain_evolution_guidance.
    All default to empty string if no config is available.
    """
    # Safe fallback: any missing registry, config plumbing failure, or
    # absent domain config yields all-empty strings so callers can splice
    # these into a template unconditionally without None-checking.
    empty = {
        "domain_context": "",
        "domain_generation_guidance": "",
        "domain_review_guidance": "",
        "domain_evolution_guidance": "",
        "domain_reflection_guidance": "",
    }

    if tool_registry is None:
        tool_registry = _resolve_default_tool_registry()

    if tool_registry is None:
        return empty

    try:
        prompts_config = tool_registry.get_prompts_config()
    except Exception:
        return empty

    return {
        "domain_context": prompts_config.domain_context,
        "domain_generation_guidance": prompts_config.generation_guidance,
        "domain_review_guidance": prompts_config.review_guidance,
        "domain_evolution_guidance": prompts_config.evolution_guidance,
        "domain_reflection_guidance": prompts_config.reflection_guidance,
    }


def _build_prompt(
    prompt_name: str,
    base_variables: dict[str, Any],
    *,
    sections: PromptSections | None = None,
    tool_registry: Any | None = None,
    include_domain: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """Assemble a prompt's variables and load it with its schema.

    Reproduces the shared getter skeleton: ``base_variables`` (copied, not
    mutated) plus the optional pre-formatted guidance/context blocks and
    the domain-variable injection most node prompts share. Each optional
    block is added only when the caller passes a non-``None`` value (an
    empty string still adds the key), so a template placeholder the caller
    intentionally omits still renders as the ``{{MISSING:...}}`` sentinel
    (matching pre-consolidation behavior) rather than an empty string.
    For supervisor guidance the caller selects the correct
    ``_format_supervisor_guidance_for_*`` helper. ``include_domain=False``
    skips the five ``domain_*`` variables (and the ``tool_registry``
    forward to ``_get_domain_variables``) for prompts that never inject
    them (e.g. proximity).

    Args:
        prompt_name: Template file stem under ``templates/``.
        base_variables: The template variables the calling builder owns.
        sections: Pre-formatted shared context blocks; omitted fields stay
            unset, as documented on ``PromptSections``.
        tool_registry: Tool registry used to resolve the ``domain_*``
            variables.
        include_domain: Whether to inject the ``domain_*`` variables.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or ``None``).
    """
    blocks = sections or PromptSections()
    variables: dict[str, Any] = dict(base_variables)
    if blocks.supervisor_guidance is not None:
        variables["supervisor_guidance"] = blocks.supervisor_guidance
    if blocks.meta_review_context is not None:
        variables["meta_review_context"] = blocks.meta_review_context
    if blocks.run_guidance is not None:
        variables["run_guidance"] = blocks.run_guidance
    if include_domain:
        variables.update(_get_domain_variables(tool_registry))
    return load_prompt_with_schema(prompt_name, variables)
