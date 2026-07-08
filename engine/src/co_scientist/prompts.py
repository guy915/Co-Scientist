"""Prompt loading and template substitution utilities.

All prompts are stored as markdown files in the prompts/ directory.
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
# prompts/ directory is also declared as package-data for the latter case.
_PROMPTS_DIR = Path(__file__).parent / "prompts"

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
        >>> load_prompt("generation", {"research_goal": "Cure cancer", "hypotheses_count": 5})  # pylint: disable=line-too-long
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
        >>> prompt, schema = load_prompt_with_schema("generation", {"research_goal": "Cure cancer"})  # pylint: disable=line-too-long
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


# Convenience functions for common prompts
# One getter per prompt template; each names the template file stem it
# renders (prompts/<name>.md) and is called by exactly one node module.


# Renders prompts/review.md for the single-hypothesis review path in
# nodes/review.py (used when the batch is too large for comparative review).
def get_review_prompt(
    research_goal: str,
    hypothesis_text: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the hypothesis review prompt and schema."""
    return _build_prompt(
        "review",
        {
            "research_goal": research_goal,
            "hypothesis_text": hypothesis_text
        },
        supervisor_guidance=_format_supervisor_guidance_for_review(
            supervisor_guidance),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/deep_verification.md for nodes/deep_verification.py, run
# once per top-Elo hypothesis. Deliberately takes no guidance/context
# blocks: probing should challenge the hypothesis on its own terms.
def get_deep_verification_prompt(
    research_goal: str,
    hypothesis_text: str,
    tool_registry: Any | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the deep-verification (probing questions) prompt and schema."""
    return _build_prompt(
        "deep_verification",
        {
            "research_goal": research_goal,
            "hypothesis_text": hypothesis_text,
        },
        tool_registry=tool_registry,
    )


# Renders prompts/review_batch.md for the comparative batch review path in
# nodes/review.py; hypotheses_list is a pre-formatted text block, not a
# Python list.
def get_review_batch_prompt(
    research_goal: str,
    hypotheses_list: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the comparative batch hypothesis review prompt and schema."""
    return _build_prompt(
        "review_batch",
        {
            "research_goal": research_goal,
            "hypotheses_list": hypotheses_list
        },
        supervisor_guidance=_format_supervisor_guidance_for_review(
            supervisor_guidance),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/ranking.md for each pairwise tournament match in
# nodes/ranking.py. Beyond the two hypothesis texts, the prompt aggregates
# every per-hypothesis signal available at match time: review scores,
# reflection notes, and (from the second tournament onward) deep-
# verification probes.
def get_ranking_prompt(
    research_goal: str,
    hypothesis_a: str,
    hypothesis_b: str,
    supervisor_guidance: dict[str, Any] | None = None,
    review_a: dict[str, Any] | None = None,
    review_b: dict[str, Any] | None = None,
    reflection_notes_a: str | None = None,
    reflection_notes_b: str | None = None,
    deep_verification_a: dict[str, Any] | None = None,
    deep_verification_b: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the ranking (and tournament) comparison prompt and schema."""
    variables = {
        "research_goal": research_goal,
        "hypothesis_a": hypothesis_a,
        "hypothesis_b": hypothesis_b,
    }

    # Add review context if available
    variables["review_context"] = _format_review_context(review_a, review_b)

    # Add reflection notes if available
    variables["hypothesis_a_reflection_notes"] = (
        reflection_notes_a or "No reflection notes available.")
    variables["hypothesis_b_reflection_notes"] = (
        reflection_notes_b or "No reflection notes available.")

    # Add deep-verification probes if available (blank before the first
    # deep_verification pass has run on the leaders).
    dv_a = deep_verification_a or {}
    dv_b = deep_verification_b or {}
    variables["hypothesis_a_deep_verification"] = (
        _format_deep_verification_context(dv_a.get("probes"),
                                          dv_a.get("verdict"), "A"))
    variables["hypothesis_b_deep_verification"] = (
        _format_deep_verification_context(dv_b.get("probes"),
                                          dv_b.get("verdict"), "B"))

    return _build_prompt(
        "ranking",
        variables,
        supervisor_guidance=_format_supervisor_guidance_for_ranking(
            supervisor_guidance),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/meta_review.md for nodes/meta_review.py; all_reviews is
# the JSON dump of every review collected so far, synthesized once per
# iteration into cross-hypothesis feedback.
def get_meta_review_prompt(
    research_goal: str,
    all_reviews: str,
    supervisor_guidance: dict[str, Any] | None = None,
    instructions: str | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the meta-review synthesis prompt and schema."""
    return _build_prompt(
        "meta_review",
        {
            "research_goal": research_goal,
            "all_reviews": all_reviews,
            "instructions": instructions or "",
        },
        supervisor_guidance=_format_supervisor_guidance_for_meta_review(
            supervisor_guidance),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/research_overview.md for nodes/research_overview.py, the
# terminal synthesis over the top-Elo hypotheses.
def get_research_overview_prompt(
    research_goal: str,
    hypotheses_summary: str,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the research-overview + NIH Specific Aims prompt and schema."""
    return _build_prompt(
        "research_overview",
        {
            "research_goal": research_goal,
            "hypotheses_summary": hypotheses_summary,
        },
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Renders prompts/proximity.md for nodes/proximity.py. The hypothesis texts
# are passed as a JSON array; include_domain=False because similarity
# clustering is domain-neutral by design.
def get_proximity_prompt(
    hypotheses: list[Any],
    supervisor_guidance: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Get the proximity/similarity analysis prompt and schema."""
    import json  # pylint: disable=import-outside-toplevel

    return _build_prompt(
        "proximity",
        {
            "hypotheses":
                json.dumps([
                    h["text"] if isinstance(h, dict) else h for h in hypotheses
                ],
                           indent=2)
        },
        supervisor_guidance=_format_supervisor_guidance_for_proximity(
            supervisor_guidance),
        include_domain=False,
    )


# Renders prompts/supervisor.md for nodes/supervisor.py, the planning call
# at the head of the graph. Every user-supplied run input (preferences,
# constraints, seed hypotheses/literature, count knobs) is normalized to a
# "None provided"/"not specified" string so the template never renders a
# raw Python None.
def get_supervisor_prompt(
    research_goal: str,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    constraints: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
    user_literature: list[str] | None = None,
    initial_hypotheses_count: int | None = None,
    max_iterations: int | None = None,
    evolution_max_count: int | None = None,
    mcp_available: bool = False,
    pubmed_available: bool = False,
    tool_registry: Any | None = None,
    criteria: list[str] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """get the supervisor research planning prompt and schema."""

    # Build pipeline description based on available tools
    lit_review_description = ""
    if pubmed_available or mcp_available:
        lit_review_description = (
            "literature review will search pubmed for relevant papers"
            " and analyze them")
    else:
        lit_review_description = (
            "literature review is not available (no pubmed access)")

    variables = {
        "research_goal": research_goal,
        "preferences": preferences or "None provided",
        "attributes": ", ".join(attributes) if attributes else "None provided",
        "constraints": ("\n".join(
            f"- {c}" for c in constraints) if constraints else "None provided"),
        "criteria": ("\n".join(
            f"- {c}" for c in criteria) if criteria else "None provided"),
        "user_hypotheses": ("\n".join(f"- {h}" for h in user_hypotheses)
                            if user_hypotheses else "None provided"),
        "user_literature": ("\n".join(f"- {lit}" for lit in user_literature)
                            if user_literature else "None provided"),
        "initial_hypotheses_count": initial_hypotheses_count or "not specified",
        "max_iterations": max_iterations or "not specified",
        "evolution_max_count": evolution_max_count or "not specified",
        "literature_review_description": lit_review_description,
    }

    return _build_prompt(
        "supervisor",
        variables,
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Helper functions to format supervisor guidance for different contexts
# Each helper extracts only the slice of the supervisor's output relevant
# to its node and renders it as a markdown section; all of them return ""
# when the needed keys are absent, so guidance is strictly additive.
def _format_supervisor_guidance_for_review(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for review prompts."""
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    sections = []
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    review_phase = workflow_plan.get("review_phase", {})

    if review_phase:
        sections.append("## Supervisor Guidance for Review\n")
        if review_phase.get("critical_criteria"):
            criteria = review_phase["critical_criteria"]
            if isinstance(criteria, list):
                criteria = ", ".join(criteria)
            sections.append(f"**Critical Criteria to Emphasize:** {criteria}\n")
        if review_phase.get("review_depth"):
            sections.append(
                f"**Review Depth Required:** {review_phase['review_depth']}\n")

    # Synthesized config: preferences constrain what a good idea is (shared with
    # generation); review_instructions are reviewer-only comparative guidance.
    config = supervisor_guidance.get("config_synthesis", {})
    if isinstance(config, dict):
        preferences = config.get("preferences") or []
        review_instructions = config.get("review_instructions") or []
        attributes = config.get("attributes") or []
        if not sections and (preferences or review_instructions or attributes):
            sections.append("## Supervisor Guidance for Review\n")
        if preferences:
            sections.append("**Preferences (a good idea should satisfy):**\n")
            sections.extend(f"- {p}\n" for p in preferences)
        if review_instructions:
            sections.append(
                "\n**Review instructions (validate, do not restate the"
                " preferences):**\n")
            sections.extend(f"- {r}\n" for r in review_instructions)
        if attributes:
            sections.append("\n**Stratification attributes (score each 1-5):**"
                            "\n")
            for attr in attributes:
                if isinstance(attr, dict) and attr.get("name"):
                    sections.append(
                        f"- {attr['name']}: {attr.get('rubric', '')}\n")

    return "".join(sections) if sections else ""


def _format_key_areas_guidance(supervisor_guidance: dict[str, Any] | None,
                               header: str, trailer: str) -> str:
    """Format the supervisor's key research areas as a guidance section.

    Args:
        supervisor_guidance: Supervisor guidance dict from workflow state.
        header: Bolded sub-header introducing the key-areas list.
        trailer: Sentence telling the node how to apply the key areas.

    Returns:
        A markdown guidance section, or an empty string without key areas.
    """
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    key_areas = goal_analysis.get("key_areas", [])
    if not key_areas:
        return ""

    sections = ["## Supervisor Guidance\n", f"**{header}:**\n"]
    for area in key_areas:
        sections.append(f"- {area}\n")
    sections.append(f"\n{trailer}\n")
    return "".join(sections)


def _format_supervisor_guidance_for_ranking(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for ranking prompts."""
    return _format_key_areas_guidance(
        supervisor_guidance, "Key Research Areas to Consider",
        "When comparing hypotheses, prioritize those that better"
        " address these key areas.")


def _format_supervisor_guidance_for_proximity(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for proximity prompts."""
    return _format_key_areas_guidance(
        supervisor_guidance, "Key Research Areas",
        "When assessing similarity, consider whether hypotheses"
        " explore different aspects of these key areas. Hypotheses"
        " that address the same area with similar approaches should"
        " be flagged as duplicates.")


# Reads the state dict shaped by nodes/meta_review.py (which renames the
# schema's strengths/weaknesses fields to common_strengths/
# common_weaknesses when storing state), not the raw META_REVIEW_SCHEMA
# output.
def _format_meta_review_context(meta_review: dict[str, Any] | None) -> str:
    """Format meta-review insights for review prompts (when re-reviewing evolved
    hypotheses).
    """
    if not meta_review or not isinstance(meta_review, dict):
        return ""

    sections = []
    sections.append("## Meta-Review Context\n")
    sections.append(
        "The following insights were synthesized from previous reviews"
        " of all hypotheses:\n\n")

    common_strengths = meta_review.get("common_strengths", [])
    if common_strengths:
        sections.append("**Common Strengths Across Hypotheses:**\n")
        for strength in common_strengths:
            sections.append(f"- {strength}\n")
        sections.append("\n")

    common_weaknesses = meta_review.get("common_weaknesses", [])
    if common_weaknesses:
        sections.append("**Common Weaknesses to Watch For:**\n")
        for weakness in common_weaknesses:
            sections.append(f"- {weakness}\n")
        sections.append("\n")

    strategic_recommendations = meta_review.get("strategic_recommendations", [])
    if strategic_recommendations:
        sections.append("**Strategic Recommendations:**\n")
        for rec in strategic_recommendations:
            if isinstance(rec, dict):
                rec_text = rec.get("recommendation", str(rec))
            else:
                rec_text = str(rec)
            sections.append(f"- {rec_text}\n")
        sections.append("\n")

    sections.append(
        "Use these insights to provide more informed and consistent reviews.\n")

    return "".join(sections) if sections else ""


def _format_run_guidance(run_setup_guidance: str | None = None,
                         run_focus_guidance: str | None = None) -> str:
    """Format durable run setup/focus guidance for downstream prompts."""
    sections = []
    if run_setup_guidance:
        sections.append("## Run Setup Guidance\n")
        sections.append(run_setup_guidance.strip())
        sections.append("\n")
    if run_focus_guidance:
        sections.append("## Run Focus Guidance\n")
        sections.append(run_focus_guidance.strip())
        sections.append("\n")
    return "\n".join(sections).strip()


def _format_deep_verification_context(probes: list[dict[str, Any]] | None,
                                      verdict: str | None, label: str) -> str:
    """Format deep-verification probes for one hypothesis in ranking prompts.

    Returns an empty string when no probes are available so the ranking prompt
    is unchanged on the first tournament (before any deep verification has run).

    Args:
        probes: Probing-question entries from the deep-verification node, or
            None.
        verdict: The deep-verification verdict ("holds", "weakened", or
            "undermined"), or None.
        label: The hypothesis label ("A" or "B") for the section header.

    Returns:
        A formatted block with a leading separator, or an empty string.
    """
    if not probes:
        return ""

    verdict_text = verdict or "unknown"
    sections = [
        f"\n\n**Hypothesis {label} Deep Verification"
        f" (verdict: {verdict_text}):**\n"
    ]
    for probe in probes:
        question = probe.get("question", "")
        answer = probe.get("answer", "")
        fundamental = (" (fundamental assumption)"
                       if probe.get("assumption_is_fundamental") else "")
        sections.append(f"- Q{fundamental}: {question}\n")
        if answer:
            sections.append(f"  A: {answer}\n")

    return "".join(sections)


def _format_review_context(review_a: dict[str, Any] | None,
                           review_b: dict[str, Any] | None) -> str:
    """Format review scores for ranking prompts."""
    if not review_a and not review_b:
        return ""

    sections = []
    sections.append("## Review Scores Context\n")
    sections.append("The following review scores are available to inform your"
                    " comparison:\n\n")

    if review_a:
        sections.append("**Hypothesis A Review Scores:**\n")
        if isinstance(review_a, dict):
            if "scores" in review_a:
                for criterion, score in review_a["scores"].items():
                    sections.append(f"- {criterion}: {score}\n")
            if "overall_score" in review_a:
                sections.append(
                    f"- Overall Score: {review_a['overall_score']}\n")
        sections.append("\n")

    if review_b:
        sections.append("**Hypothesis B Review Scores:**\n")
        if isinstance(review_b, dict):
            if "scores" in review_b:
                for criterion, score in review_b["scores"].items():
                    sections.append(f"- {criterion}: {score}\n")
            if "overall_score" in review_b:
                sections.append(
                    f"- Overall Score: {review_b['overall_score']}\n")
        sections.append("\n")

    sections.append("Consider these scores, but make your judgment based on"
                    " comprehensive comparison, not just scores.\n")

    return "".join(sections) if sections else ""


def _format_supervisor_guidance_for_meta_review(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for meta-review prompts."""
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    sections = []
    sections.append("## Supervisor Guidance\n")

    # Add key research areas
    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    key_areas = goal_analysis.get("key_areas", [])
    if key_areas:
        sections.append("**Key Research Areas:**\n")
        for area in key_areas:
            sections.append(f"- {area}\n")
        sections.append("\n")

    # Add evolution phase guidance
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    evolution_phase = workflow_plan.get("evolution_phase", {})
    if evolution_phase:
        sections.append("**Evolution Phase Guidance:**\n")
        if evolution_phase.get("refinement_priorities"):
            priorities = evolution_phase["refinement_priorities"]
            if isinstance(priorities, list):
                priorities = ", ".join(priorities)
            sections.append(f"- Refinement Priorities: {priorities}\n")
        if evolution_phase.get("iteration_strategy"):
            iter_strat = evolution_phase['iteration_strategy']
            sections.append(f"- Iteration Strategy: {iter_strat}\n")
        sections.append("\n")

    sections.append(
        "Use this guidance to ensure your meta-review synthesis aligns"
        " with the research plan and evolution strategy.\n")

    return "".join(sections) if sections else ""


# Renders prompts/reflection_observations.md for nodes/reflection.py, run
# per hypothesis against the literature-review synthesis; indra_evidence
# carries optional knowledge-graph enrichment text ("" when unavailable).
def get_reflection_prompt(
    articles_with_reasoning: str,
    hypothesis_text: str,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    indra_evidence: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Get the reflection observations prompt and schema."""
    return _build_prompt(
        "reflection_observations",
        {
            "articles_with_reasoning": articles_with_reasoning,
            "hypothesis": hypothesis_text,
            "indra_evidence": indra_evidence,
        },
        meta_review_context=_format_meta_review_context(meta_review),
        tool_registry=tool_registry,
    )


# PubMed-specific variant kept for backwards compatibility; production code
# goes through the source-aware getter below, which dispatches to the same
# template when source_type is "pubmed".
def get_literature_review_query_generation_pubmed_prompt(
    research_goal: str,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_literature: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
) -> str:
    """Get the PubMed query generation prompt."""
    return load_prompt(
        "literature_review_query_generation_pubmed",
        {
            "research_goal":
                research_goal,
            "preferences":
                preferences if preferences else "None provided",
            "attributes":
                ", ".join(attributes) if attributes else "None provided",
            "user_literature": ("\n".join(f"- {lit}" for lit in user_literature)
                                if user_literature else "None provided"),
            "user_hypotheses": ("\n".join(f"- {hyp}" for hyp in user_hypotheses)
                                if user_hypotheses else "None provided"),
        },
    )


# Query-generation entry point used by nodes/literature_review.py, paired
# there with LITERATURE_QUERY_SCHEMA. Returns a bare string (no schema in
# the tuple) because the schema is imported directly by the caller.
def get_literature_review_query_generation_prompt(
    research_goal: str,
    source_type: str = "academic",
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_literature: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
) -> str:
    """Get source-aware query generation prompt.

    Selects the appropriate prompt template based on source type:
    - knowledge_graph (INDRA): Extract gene/protein names
    - academic (PubMed, arXiv, Scholar): Natural language queries
    - pubmed: PubMed-specific (backwards compat)

    Args:
        research_goal: The research goal
        source_type: Type of literature source (from ToolConfig.source_type)
        preferences: Optional user preferences
        attributes: Optional user attributes
        user_literature: Optional user-provided literature
        user_hypotheses: Optional user-provided hypotheses

    Returns:
        Formatted prompt string
    """
    # Select template based on source type
    if source_type == "knowledge_graph":
        template_name = "literature_review_query_generation_indra"
    elif source_type == "pubmed":
        template_name = "literature_review_query_generation_pubmed"
    else:
        # Generic fallback for other academic sources
        template_name = "literature_review_query_generation_generic"

    return load_prompt(
        template_name,
        {
            "research_goal":
                research_goal,
            "preferences":
                preferences if preferences else "None provided",
            "attributes":
                ", ".join(attributes) if attributes else "None provided",
            "user_literature": ("\n".join(f"- {lit}" for lit in user_literature)
                                if user_literature else "None provided"),
            "user_hypotheses": ("\n".join(f"- {hyp}" for hyp in user_hypotheses)
                                if user_hypotheses else "None provided"),
        },
    )


def _format_authors(authors: list[str]) -> str:
    """Format an author list for paper analysis prompts."""
    return ", ".join(authors) if authors else "Unknown"


def _format_year(year: int | None) -> str:
    """Format a publication year for paper analysis prompts."""
    return str(year) if year else "Unknown"


# Renders prompts/literature_review_paper_analysis.md, called by
# nodes/literature_review.py once per fetched paper (paired there with
# LITERATURE_PAPER_ANALYSIS_SCHEMA).
def get_literature_review_paper_analysis_prompt(research_goal: str, title: str,
                                                authors: list[str],
                                                year: int | None,
                                                fulltext: str) -> str:
    """Get the prompt for analyzing a single paper."""
    return load_prompt(
        "literature_review_paper_analysis",
        {
            "research_goal": research_goal,
            "title": title,
            "authors": _format_authors(authors),
            "year": _format_year(year),
            "fulltext": fulltext,
        },
    )


# Renders prompts/literature_review_synthesis.md for
# nodes/literature_review.py: flattens the per-paper analyses into one
# markdown block and optionally appends knowledge-graph background as a
# "Mechanistic Background" section (empty string when unavailable).
def get_literature_review_synthesis_prompt(
    research_goal: str,
    paper_analyses: list[dict[str, Any]],
    background_context: str = "",
) -> str:
    """Get the prompt for synthesizing paper analyses."""
    # Format paper analyses as structured text
    analyses_text = []
    for i, analysis_data in enumerate(paper_analyses, 1):
        metadata = analysis_data.get("metadata", {})
        analysis = analysis_data.get("analysis", {})

        paper_section = f"""### paper {i}: {metadata.get('title', 'Unknown')}
**authors:** {', '.join(metadata.get('authors', ['Unknown']))}
**year:** {metadata.get('year', 'Unknown')}

**key findings:** {analysis.get('key_findings', 'N/A')}

**gaps identified:** {analysis.get('gaps_identified', 'N/A')}

**future work suggested:** {analysis.get('future_work', 'N/A')}

**methodology limitations:** {analysis.get('methodology_limitations', 'N/A')}

**unexplored areas:** {analysis.get('unexplored_areas', 'N/A')}

**relevance:** {analysis.get('relevance', 'N/A')}
"""
        analyses_text.append(paper_section)

    background_context_section = (
        "\n## Mechanistic Background (Knowledge Graph)\n\n"
        "The following structured evidence was retrieved from external"
        " knowledge sources "
        "to supplement the literature. Use it to ground the synthesis"
        " in known causal "
        "relationships and flag where hypotheses can leverage or"
        " contradict this background.\n\n" +
        background_context if background_context else "")

    return load_prompt(
        "literature_review_synthesis",
        {
            "research_goal": research_goal,
            "paper_analyses": "\n\n".join(analyses_text),
            "background_context_section": background_context_section,
        },
    )


# Renders prompts/hypothesis_novelty_analysis.md, called by
# nodes/generation/literature_tools/validate.py once per (draft hypothesis,
# paper) pair (paired there with HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA).
def get_hypothesis_novelty_analysis_prompt(hypothesis_text: str, title: str,
                                           authors: list[str], year: int | None,
                                           fulltext: str) -> str:
    """Get the prompt for analyzing a paper for hypothesis novelty."""
    return load_prompt(
        "hypothesis_novelty_analysis",
        {
            "hypothesis_text": hypothesis_text,
            "title": title,
            "authors": _format_authors(authors),
            "year": _format_year(year),
            "fulltext": fulltext,
        },
    )


def _format_hypotheses_with_novelty_analyses(
        hypotheses_with_analyses: list[dict[str, Any]]) -> str:
    """Render draft hypotheses and their per-paper novelty analyses.

    Shared by both validation-synthesis prompt builders so the draft/analysis
    layout has a single definition.

    Args:
        hypotheses_with_analyses: Draft hypotheses, each with a ``draft`` dict
            and a ``novelty_analyses`` list of ``{paper_metadata, analysis}``.

    Returns:
        The formatted block, sections joined by blank lines.
    """
    hypotheses_text = []
    for i, hyp_data in enumerate(hypotheses_with_analyses, 1):
        draft = hyp_data.get("draft", {})
        analyses = hyp_data.get("novelty_analyses", [])

        hyp_section = f"""### draft hypothesis {i}
**text:** {draft.get('text', 'Unknown')}
**gap reasoning:** {draft.get('gap_reasoning', 'N/A')}
**literature sources:** {draft.get('literature_sources', 'N/A')}

**novelty analyses ({len(analyses)} papers examined):**
"""

        for j, analysis_data in enumerate(analyses, 1):
            paper_meta = analysis_data.get("paper_metadata", {})
            analysis = analysis_data.get("analysis", {})
            p_title = paper_meta.get('title', 'Unknown')
            p_year = paper_meta.get('year', 'N/A')

            paper_analysis = (
                f"\n**paper {j}:** {p_title} ({p_year})\n"
                f"- methods used:"
                f" {analysis.get('methods_used', 'N/A')}\n"
                f"- populations studied:"
                f" {analysis.get('populations_studied', 'N/A')}\n"
                f"- mechanisms investigated:"
                f" {analysis.get('mechanisms_investigated', 'N/A')}\n"
                f"- key findings:"
                f" {analysis.get('key_findings', 'N/A')}\n"
                f"- stated limitations:"
                f" {analysis.get('stated_limitations', 'N/A')}\n"
                f"- future work suggested:"
                f" {analysis.get('future_work_suggested', 'N/A')}\n"
                f"- **novelty assessment:"
                f" {analysis.get('novelty_assessment', 'N/A')}**\n"
                f"- overlap explanation:"
                f" {analysis.get('overlap_explanation', 'N/A')}\n")
            hyp_section += paper_analysis

        hypotheses_text.append(hyp_section)
    return "\n\n".join(hypotheses_text)


# Tool-less validation-synthesis variant. No production caller: the
# pipeline uses get_validation_synthesis_prompt_with_tools below; this one
# is retained for tests and tool-free experimentation.
def get_hypothesis_validation_synthesis_prompt(
    research_goal: str,
    hypotheses_with_analyses: list[dict[str, Any]],
    articles: list[Any] | None = None,
    tool_registry: Any | None = None,
    reference_list: str = "",
) -> str:
    """Get the prompt for validation synthesis based on novelty analyses.

    Args:
        research_goal: The research goal
        hypotheses_with_analyses: List of draft hypotheses with novelty analyses
        articles: Optional list of Article objects for citation metadata
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys

    Returns:
        Formatted prompt string
    """
    variables = {
        "research_goal":
            research_goal,
        "hypotheses_with_analyses":
            _format_hypotheses_with_novelty_analyses(hypotheses_with_analyses),
        "articles_metadata":
            format_articles_metadata(articles or []),
        "citation_reference_section":
            _build_citation_reference_section(reference_list),
    }

    # Inject domain-specific prompt customizations
    variables.update(_get_domain_variables(tool_registry))

    return load_prompt("hypothesis_validation_synthesis", variables)


def _build_already_validated_context(
        already_validated_texts: list[str] | None) -> str:
    """Build diversity constraint block for retry path.

    Injected only when retrying failed batches individually, so the model
    knows which hypothesis territory is already claimed and can pivot away.
    """
    if not already_validated_texts:
        return ""
    lines = "\n".join(f"- {t}" for t in already_validated_texts)
    return f"""
## Hypotheses Already Validated (Diversity Constraint)

The following hypotheses have already been validated and will be included in the final output.  # pylint: disable=line-too-long
Your output **must explore different mechanistic territory** from each of these.
If your draft overlaps significantly with any entry below, treat it as saturated and pivot:

{lines}

"""


# Renders prompts/hypothesis_validation_synthesis_with_tools.md for the
# Phase 2 validation agent in nodes/generation/literature_tools/validate.py.
# tool_instructions is built from the "validation" workflow's tool list so
# the agent knows which MCP search tools it may call while pivoting.
def get_validation_synthesis_prompt_with_tools(
    research_goal: str,
    hypotheses_with_analyses: list[dict[str, Any]],
    articles: list[Any] | None = None,
    articles_with_reasoning: str | None = None,
    max_iterations: int = 8,
    tool_registry: Any | None = None,
    reference_list: str = "",
    already_validated_texts: list[str] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get prompt for validation synthesis with tool access.

    This version includes tool instructions so the LLM can search for
    additional papers when deciding to pivot hypotheses.

    Args:
        research_goal: The research goal
        hypotheses_with_analyses: List of draft hypotheses with novelty analyses
        articles: Optional list of Article objects for citation metadata
        articles_with_reasoning: Literature review synthesis
        max_iterations: Max tool iterations for the agent
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        already_validated_texts: Hypothesis texts already validated
            (retry path only). Injected as a diversity constraint so the
            model avoids duplicate territory.
    """
    # Get tool IDs for validation workflow
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("validation")

    # Build dynamic tool instructions
    tool_instructions = build_tool_instructions(tool_ids, tool_registry)

    variables = {
        "research_goal":
            research_goal,
        "hypotheses_with_analyses":
            _format_hypotheses_with_novelty_analyses(hypotheses_with_analyses),
        "hypotheses_count":
            len(hypotheses_with_analyses),
        "articles_metadata":
            format_articles_metadata(articles or []),
        "articles_with_reasoning":
            articles_with_reasoning
            or "no literature review summary available.",
        "citation_reference_section":
            _build_citation_reference_section(reference_list or ""),
        "max_iterations":
            max_iterations,
        "tool_instructions":
            tool_instructions,
        "already_validated_context":
            _build_already_validated_context(already_validated_texts),
    }

    return _build_prompt(
        "hypothesis_validation_synthesis_with_tools",
        variables,
        tool_registry=tool_registry,
    )


# Called by nodes/generation/debate.py once per debate turn. Template
# choice depends on literature availability
# (generation_debate_and_literature vs generation_after_debate), and the
# final turn switches from free-form discussion to schema-constrained JSON
# output (GENERATION_SCHEMA).
def get_debate_generation_prompt(
    research_goal: str,
    hypotheses_count: int,
    transcript: str,
    supervisor_guidance: dict[str, Any] | None = None,
    preferences: str | None = None,
    attributes: str | list[str] | None = None,
    is_final_turn: bool = False,
    articles_with_reasoning: str | None = None,
    articles: list[Any] | None = None,
    tool_registry: Any | None = None,
    reference_list: str = "",
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the debate-based hypothesis generation prompt.

    This uses a multi-turn debate strategy where experts discuss and refine
    hypotheses.
    The transcript accumulates over multiple turns until final hypotheses are
    generated.

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to generate
        transcript: Accumulated conversation transcript from previous turns
        supervisor_guidance: Optional guidance from supervisor
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        is_final_turn: Whether this is the final turn (outputs JSON schema)
        articles_with_reasoning: Optional literature review synthesis for
            context
        articles: Optional list of Article objects for citation metadata
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        meta_review: Optional cross-iteration meta-review feedback

    Returns:
        Tuple of (formatted prompt string, JSON schema dict or None)
    """
    variables = {
        "goal":
            research_goal,
        "hypotheses_count":
            hypotheses_count,
        "transcript":
            transcript or "",
        "preferences":
            preferences
            or "Novel, testable, scientifically sound, specific, and diverse"
            " hypotheses",
        "attributes": (", ".join(attributes)
                       if attributes and isinstance(attributes, list) else
                       (attributes or "testable and falsifiable")),
    }

    # Add literature review if provided
    if articles_with_reasoning:
        variables["articles_with_reasoning"] = articles_with_reasoning

    # Add article metadata for citations
    variables["articles_metadata"] = format_articles_metadata(articles or [])
    variables["citation_reference_section"] = _build_citation_reference_section(
        reference_list or "")

    # Format supervisor guidance if available
    if supervisor_guidance and isinstance(supervisor_guidance, dict):
        guidance_sections = []
        has_content = False

        goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
        key_areas = goal_analysis.get("key_areas", [])
        if key_areas:
            if not has_content:
                guidance_sections.append("Key research areas to consider:\n")
                has_content = True
            for area in key_areas:
                guidance_sections.append(f"- {area}\n")

        workflow_plan = supervisor_guidance.get("workflow_plan", {})
        generation_phase = workflow_plan.get("generation_phase", {})
        if generation_phase:
            if not has_content:
                guidance_sections.append("Generation guidance:\n")
                has_content = True
            if generation_phase.get("focus_areas"):
                focus_areas = generation_phase["focus_areas"]
                if isinstance(focus_areas, list):
                    focus_areas = ", ".join(focus_areas)
                guidance_sections.append(f"Focus on: {focus_areas}\n")

        variables["supervisor_guidance"] = "".join(
            guidance_sections) if has_content else ""
    else:
        variables["supervisor_guidance"] = ""

    # Add meta-review context if available (blank on iteration 1).
    variables["meta_review_context"] = _format_meta_review_context(meta_review)
    variables["run_guidance"] = _format_run_guidance(run_setup_guidance,
                                                     run_focus_guidance)

    # Inject domain-specific prompt customizations
    variables.update(_get_domain_variables(tool_registry))

    # Determine which prompt to use based on literature availability
    prompt_name = ("generation_debate_and_literature"
                   if articles_with_reasoning else "generation_after_debate")

    # If final turn, append instruction to output JSON and use schema
    if is_final_turn:
        prompt, schema = load_prompt_with_schema(prompt_name, variables)

        # Append JSON output instructions for final turn
        # Concatenated verbatim after the rendered template (never run
        # through substitute_variables), so the literal braces in the JSON
        # example below need no {{}} escaping.
        final_instructions = """

## FINAL TURN - OUTPUT FORMAT

This is the final turn of the debate. Based on the discussion above, output your finalized hypothesis in JSON format with all four required components:

### 1. hypothesis (required)
Dense technical description following "We want to develop [X] to enable [Y]" format (2-3 sentences).
- Include specific technical details: algorithms, mechanisms, mathematical formulations  # pylint: disable=line-too-long
- Be precise about what will be developed and the technical approach

Example: "We want to develop a 'Dynamic Velocity Sentinel'—which monitors the rate of change in latent activation directions across early-to-mid layers rather than static depths—to enable anticipatory gating that triggers only when precursor signals cross a 'point of no return' for danger features."

### 2. explanation (required)
Clear explanation for technical audiences in layman terms (4-6 sentences).
- Core problem being addressed
- Why key mechanisms work
- How components interact
- Practical advantages

Example: "This approach addresses the computational bottleneck by focusing on early layers where precursor signals first emerge. Rather than analyzing static magnitudes, the technique tracks velocity—the rate of change—which provides earlier detection of trajectories toward dangerous outputs. The system employs autoencoders to identify danger features, with dynamic gating that triggers only when trajectories cross a learned threshold."

### 3. literature_grounding (required)
Explicit grounding with inline citation keys (2-4 sentences).
- If a Citation Reference List was provided above, use ONLY those `[C*]` keys (e.g. `[C1]`, `[C2]`, `[C3]`)
- Do NOT invent author-year citations — only use keys from the list
- If no Citation Reference List was provided, state: "This hypothesis is formulated without access to a literature review."  # pylint: disable=line-too-long

Example: "This approach builds on sparse autoencoder analysis [C1] and circuit tracing [C2]. The velocity monitoring concept addresses a gap in static-analysis methods [C3][C4]."

### 4. experiment (required)
Concrete experiment design with models, datasets, methodology, metrics, and validation (4-6 sentences).  # pylint: disable=line-too-long

Example format: "Objective: Demonstrate that velocity monitoring achieves comparable detection with reduced cost. Models: GPT-2 Medium, pre-trained SAE layers 1-6. Datasets: AdvBench harmful prompts (500 examples), HH-RLHF benign prompts (1000 examples). Methodology: (1) Implement velocity tracking, (2) Train threshold detector, (3) Compare against baseline. Metrics: Detection accuracy, timing, false positive rate, computational overhead. Validation: Success requires >90% detection, <5% false positives, >50% cost reduction."  # pylint: disable=line-too-long

---

Output exactly 1 hypothesis as valid JSON:
{
  "hypotheses": [
    {
      "hypothesis": "...",
      "explanation": "...",
      "literature_grounding": "...",
      "experiment": "..."
    }
  ]
}

IMPORTANT: Use plain text with standard punctuation (no LaTeX, no decorative Unicode).
"""
        prompt = prompt + final_instructions
        return prompt, schema
    else:
        # Non-final turns: no schema, just conversational
        prompt = load_prompt(prompt_name, variables)
        return prompt, None


# Formatting helpers for generate node
# Used by the generation prompt getters in this module (draft and debate);
# each turns an optional user input into prompt-ready text, substituting a
# sensible default when the input is absent.


def format_preferences(preferences: str | None) -> str:
    """Format user preferences for prompts."""
    if preferences:
        return preferences
    return "Focus on novelty, testability, and potential impact."


def format_attributes(attributes: list[str] | None) -> str:
    """Format user attributes for prompts."""
    if attributes:
        return "\n".join(f"- {attr}" for attr in attributes)
    return "- Novel\n- Testable\n- Impactful"


def format_user_hypotheses(user_hypotheses: list[str] | None) -> str:
    """Format user-provided starting hypotheses for prompts."""
    if user_hypotheses:
        return "\n".join(f"- {hyp}" for hyp in user_hypotheses)
    return "No user-provided starting hypotheses."


def format_supervisor_guidance_for_generation(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for generation prompts with research strategy
    section.
    """
    if not supervisor_guidance:
        return ""

    # Unlike the other guidance formatters, this reads a free-text
    # "research_plan" key rather than SUPERVISOR_SCHEMA fields, so it only
    # renders when a caller supplies that plan-style guidance shape.
    research_plan = supervisor_guidance.get("research_plan", "")
    if research_plan and research_plan.strip():
        return f"""
## Research Strategy

{research_plan}
"""
    return ""


def format_articles_metadata(articles: list[Any]) -> str:
    """Format analyzed articles with metadata for tool-based generation prompts.

    Returns structured list of articles with titles, authors, year, citations,
    pdf availability.
    Only includes articles with used_in_analysis=True.
    """
    if not articles:
        return ""

    used_articles = [art for art in articles if art.used_in_analysis]
    if not used_articles:
        return ""

    articles_list_text = "\n\n".join([
        f"**{i+1}. {art.title}**\n"
        f"   - Authors: {', '.join(art.authors[:3])}{' et al.' if len(art.authors) > 3 else ''}\n"  # pylint: disable=line-too-long
        f"   - Year: {art.year or 'Unknown'}\n"
        f"   - Citations: {art.citations}\n"
        f"   - PDF: {'Available - ' + art.pdf_links[0] if art.pdf_links else 'No PDF found (abstract only)'}\n"  # pylint: disable=line-too-long
        f"   - URL: {art.url}" for i, art in enumerate(used_articles)
    ])

    n = len(used_articles)
    return ("\n### Papers Analyzed in Literature Review\n\n"
            f"These {n} papers were ranked highest and analyzed."
            " Some may have had accessibility issues"
            " (abstracts only, paywalls, captchas).\n"
            "You can use tools to:\n"
            "- Try accessing PDFs that weren't available initially\n"
            "- Query specific papers for detailed information\n"
            "- Search for alternative papers if these have issues\n"
            f"\n{articles_list_text}\n")


def _build_citation_reference_section(reference_list: str) -> str:
    """Build the Citation Reference List prompt section.

    Returns an empty string when reference_list is empty so the LLM
    never sees citation instructions that don't apply to its run.
    The section is intentionally domain-agnostic — no INDRA/KG language.
    """
    if not reference_list.strip():
        return ""
    return ("\n## Citation Reference List\n\n"
            "Use **only** these `[C*]` citation keys inline in"
            " `literature_grounding` "
            "— do NOT invent author-year citations.\n\n" + reference_list +
            "\n")


def build_tool_instructions(
    tool_ids: list[str],
    tool_registry: Any | None = None,
) -> str:
    """Build dynamic tool instructions section from tool registry.

    Args:
        tool_ids: List of tool IDs to include in instructions
        tool_registry: ToolRegistry instance with tool configurations

    Returns:
        Formatted markdown section describing available tools
    """
    # If no registry provided, try to get the global one
    if tool_registry is None:
        try:
            from co_scientist.config import get_tool_registry  # pylint: disable=import-outside-toplevel

            tool_registry = get_tool_registry()
            # If no tool_ids provided, get them from draft workflow
            if not tool_ids:
                tool_ids = tool_registry.get_tools_for_workflow(
                    "draft_generation")
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    if not tool_registry or not tool_ids:
        # Minimal fallback when no config available
        return ("No tool configuration available."
                " Literature tools may not be accessible.")

    sections = []

    for tool_id in tool_ids:
        tool_config = tool_registry.get_tool(tool_id)
        if not tool_config or not tool_config.enabled:
            continue

        # Add tool entry
        sections.append(
            f"- `{tool_config.mcp_tool_name}`: {tool_config.description}")

        # Add prompt snippet if available
        # prompt_snippet is per-tool usage guidance authored in the YAML
        # config, indented here so it nests under the tool's list entry.
        if tool_config.prompt_snippet:
            # Indent the snippet
            snippet_lines = tool_config.prompt_snippet.strip().split("\n")
            for line in snippet_lines:
                sections.append(f"  {line}")

        sections.append("")  # blank line between tools

    if not sections:
        return "No tools available."

    return "\n".join(sections).strip()


# Renders prompts/generation_draft_with_tools.md for the Phase 1 draft
# agent in nodes/generation/literature_tools/draft.py (schema:
# GENERATION_DRAFT_SCHEMA via the prompt-name lookup).
def get_draft_prompt_with_tools(
    research_goal: str,
    hypotheses_count: int,
    supervisor_guidance: dict[str, Any] | None = None,
    articles: list[Any] | None = None,
    articles_with_reasoning: str | None = None,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
    instructions: str | None = None,
    max_iterations: int = 8,
    tool_registry: Any | None = None,
    reference_list: str = "",
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get prompt for Phase 1: drafting hypotheses with tools.

    Uses generation_draft_with_tools.md template.
    Focuses on reading papers and identifying gaps.
    Includes lit review summary as context (not instructions).

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to draft
        supervisor_guidance: Optional guidance from supervisor
        articles: List of Article objects from literature review
        articles_with_reasoning: Literature review synthesis
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        user_hypotheses: User-provided starting hypotheses
        instructions: Custom instructions
        max_iterations: Max tool iterations for the agent
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        meta_review: Optional cross-iteration meta-review feedback
    """
    # Get tool IDs for draft generation workflow
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("draft_generation")

    # Build dynamic tool instructions
    tool_instructions = build_tool_instructions(tool_ids, tool_registry)

    variables = {
        "goal":
            research_goal,
        "hypotheses_count":
            hypotheses_count,
        "preferences":
            format_preferences(preferences),
        "attributes":
            format_attributes(attributes),
        "user_hypotheses":
            format_user_hypotheses(user_hypotheses),
        "supervisor_guidance":
            format_supervisor_guidance_for_generation(supervisor_guidance),
        "articles_with_reasoning":
            articles_with_reasoning
            or "no literature review summary available - examine papers"
            " below directly.",
        "articles_metadata":
            format_articles_metadata(articles or []),
        "citation_reference_section":
            _build_citation_reference_section(reference_list or ""),
        "max_iterations":
            max_iterations,
        "instructions":
            instructions
            or "Focus on creative ideation - draft diverse hypotheses"
            " based on literature gaps.",
        "tool_instructions":
            tool_instructions,
    }

    return _build_prompt(
        "generation_draft_with_tools",
        variables,
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )
