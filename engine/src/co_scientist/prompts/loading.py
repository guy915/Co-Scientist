import functools
import logging
import re
from pathlib import Path
from typing import Any

from co_scientist.prompts._common import PromptSections
from co_scientist.schemas import get_schema_for_prompt

logger = logging.getLogger(__name__)

# Resolve templates relative to this module for both editable installs and
# wheels.
_PROMPTS_DIR = Path(__file__).parent / "templates"

_VARIABLE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def load_prompt(prompt_name: str, variables: dict[str, Any] | None = None) -> str:
    prompt_template = _read_prompt_template(prompt_name)

    if variables:
        prompt_template = substitute_variables(prompt_template, variables)

    return prompt_template


@functools.cache
def _read_prompt_template(prompt_name: str) -> str:
    """Package templates are immutable; cache their disk reads across repeated
    hypothesis calls.
    """
    prompt_path = _PROMPTS_DIR / f"{prompt_name}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    return prompt_path.read_text()


def load_prompt_with_schema(
    prompt_name: str, variables: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None]:
    """A missing schema intentionally selects free-form output."""
    prompt = load_prompt(prompt_name, variables)
    schema = get_schema_for_prompt(prompt_name)
    return prompt, schema


def substitute_variables(template: str, variables: dict[str, Any]) -> str:
    """Unresolved placeholders stay visible as MISSING sentinels."""

    def replacer(match: "re.Match[str]") -> str:
        var_name = match.group(1).strip()
        value = variables.get(var_name, f"{{{{MISSING:{var_name}}}}}")
        return str(value)

    return _VARIABLE_PATTERN.sub(replacer, template)


def _resolve_default_tool_registry() -> Any | None:
    try:
        from co_scientist.platform.retrieval.config import (
            get_tool_registry,
        )

        return get_tool_registry()
    except Exception:
        return None


def _get_domain_variables(tool_registry: Any | None = None) -> dict[str, str]:
    """Missing registry or domain configuration must yield safe empty
    substitutions.
    """
    # Missing registry/configuration yields safe empty domain substitutions.
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
    """None leaves a placeholder unresolved; an empty string intentionally
    supplies nothing.
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
