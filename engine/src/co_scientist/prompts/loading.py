"""Prompt loading, variable substitution, and shared prompt assembly.

All prompt templates are stored as markdown files in the templates/
subdirectory of this package.
"""
# pylint: disable=inconsistent-quotes

import functools
import logging
import os
import re
from pathlib import Path
from typing import Any

from co_scientist.config.registry import parse_bool_env
from co_scientist.schemas import get_schema_for_prompt

logger = logging.getLogger(__name__)

# Resolved relative to this module's own location so it works whether the
# package is installed editable (pip install -e) or from a built wheel; the
# templates/ directory is also declared as package-data for the latter case.
_PROMPTS_DIR = Path(__file__).parent / "templates"

# Helper functions for saving prompts to disk
# These are a debugging aid only (writing the fully-rendered prompt text
# under .coscientist_prompts/) and are not part of the load_prompt() render
# path itself.


def get_prompt_save_path(run_id: str, prompt_name: str) -> Path:
    """Get path for saving a filled-in prompt to disk for debugging.

    Ensures the output directory exists and returns the full path.

    Args:
        run_id: unique run identifier (from state)
        prompt_name: descriptive name for the prompt file (e.g.,
            "review_batch", "literature_synthesis")

    Returns:
        Path object for the prompt file location

    example:
        path = get_prompt_save_path("abc123", "review_batch")
        # Returns Path(".coscientist_prompts/abc123/review_batch.txt")
    """
    prompts_dir = Path(".coscientist_prompts") / run_id
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Ensure .txt extension
    if not prompt_name.endswith(".txt"):
        prompt_name = f"{prompt_name}.txt"

    return prompts_dir / prompt_name


def save_prompt_to_disk(run_id: str,
                        prompt_name: str,
                        content: str,
                        metadata: dict[str, Any] | None = None) -> bool:
    """Save a filled-in prompt to disk for debugging.

    Args:
        run_id: unique run identifier
        prompt_name: descriptive name for the prompt file
        content: the filled-in prompt content
        metadata: optional dict of metadata to append (e.g., token counts,
            config)

    Returns:
        True if saved successfully, False otherwise
    """
    # One synchronous file write per LLM call adds up over a run; deployments
    # that don't need the debug artifacts can turn them off globally here.
    if not parse_bool_env(os.getenv("COSCIENTIST_SAVE_PROMPTS", "true")):
        return False

    try:
        path = get_prompt_save_path(run_id, prompt_name)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

            # Append metadata if provided
            if metadata:
                f.write("\n\n=== METADATA (by save_prompt_to_disk) ===\n")
                for key, value in metadata.items():
                    f.write(f"{key}: {value}\n")

        logger.debug("Saved prompt to: %s", path)
        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to save prompt to disk: %s", e)
        return False


def load_prompt(prompt_name: str,
                variables: dict[str, Any] | None = None) -> str:
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


@functools.lru_cache(maxsize=None)
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
    prompt_name: str,
    variables: dict[str, Any] | None = None
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
    return re.sub(r"\{\{([^}]+)\}\}", replacer, template)


# Domain variable injection from YAML config
# Lets a deployment's tools config (e.g. config/*.yaml, see the
# domain-customization docs) inject domain-specific wording into prompts
# without changing the .md templates themselves; every domain_* variable
# below is a template placeholder used by one or more of the getters
# further down this file.


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
        try:
            from co_scientist.config import get_tool_registry  # pylint: disable=import-outside-toplevel
            tool_registry = get_tool_registry()
        except Exception:  # pylint: disable=broad-exception-caught
            return empty

    if tool_registry is None:
        return empty

    try:
        prompts_config = tool_registry.get_prompts_config()
    except Exception:  # pylint: disable=broad-exception-caught
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
    supervisor_guidance: str | None = None,
    meta_review_context: str | None = None,
    run_guidance: str | None = None,
    tool_registry: Any | None = None,
    include_domain: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """Assemble a prompt's variables and load it with its schema.

    Reproduces the shared getter skeleton: a caller-provided base of
    template-specific variables, plus the optional guidance/context blocks
    and the domain-variable injection that most node prompts share. Each
    optional block is added to the variables dict only when the caller
    passes a non-``None`` value, so a template placeholder the caller
    intentionally omits still renders as the ``{{MISSING:...}}`` sentinel
    (matching pre-consolidation behavior) rather than an empty string.

    Args:
        prompt_name: Prompt file stem passed to ``load_prompt_with_schema``.
        base_variables: Always-present, template-specific variables. Copied,
            not mutated.
        supervisor_guidance: Pre-formatted supervisor-guidance block (the
            caller selects the correct ``_format_supervisor_guidance_for_*``
            helper). Added under ``"supervisor_guidance"`` only when not
            ``None``; an empty string still adds the key.
        meta_review_context: Pre-formatted meta-review block. Added under
            ``"meta_review_context"`` only when not ``None``.
        run_guidance: Pre-formatted run setup/focus block. Added under
            ``"run_guidance"`` only when not ``None``.
        tool_registry: Tool registry forwarded to ``_get_domain_variables``
            when ``include_domain`` is true.
        include_domain: Whether to merge the five ``domain_*`` variables.
            Set false for prompts that never inject them (e.g. proximity).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or ``None``).
    """
    variables: dict[str, Any] = dict(base_variables)
    if supervisor_guidance is not None:
        variables["supervisor_guidance"] = supervisor_guidance
    if meta_review_context is not None:
        variables["meta_review_context"] = meta_review_context
    if run_guidance is not None:
        variables["run_guidance"] = run_guidance
    if include_domain:
        variables.update(_get_domain_variables(tool_registry))
    return load_prompt_with_schema(prompt_name, variables)
