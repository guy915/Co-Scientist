"""The two provider calls the Knowledge Base is assembled from (F8).

Split out of ``research_overview_knowledge_base``, which keeps the
orchestration and the grounding rules, so neither module carries both the
wire shape and the validation shape.

Both calls ask for their chain of thought to be bounded, which is the
other half of the fix the split is: production run ``e47a3ba1`` failed all
three attempts of the old single call with ``completion_tokens ==
reasoning_tokens`` -- 10,080 to 20,949 tokens of reasoning and not one
answer token written before the stream died. On this deployment's declared
chain ``enable_thinking=False`` does not disable reasoning (no free
gateway model claims ``reasoning_can_disable``); it reaches
``llm_gateway_body._minimal_reasoning_knob``, which sends an explicit
``MINIMAL_REASONING_MAX_TOKENS`` bound instead. That is what these calls
want. Neither is a task a long chain of thought earns its keep on: the
outline selects and names subjects the corpus already contains, and each
writer is handed a structure somebody else decided and asked to write
prose into it.
"""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.constants import (
    KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS,
    KNOWLEDGE_BASE_THEME_MAX_TOKENS,
    MEDIUM_TEMPERATURE,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.prompts import (
    PromptRunContext,
    ThemeWritingMaterial,
    get_knowledge_base_outline_prompt,
    get_knowledge_base_theme_prompt,
)
from co_scientist.schemas.synthesis import (
    KNOWLEDGE_BASE_MAX_SECTIONS,
    KNOWLEDGE_BASE_MAX_THEMES,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _prompt_context(state: WorkflowState) -> PromptRunContext:
    """The run-scoped prompt context both calls render against."""
    return PromptRunContext(
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )


async def _ask(
    state: WorkflowState,
    prompt: str,
    schema: dict[str, Any] | None,
    max_tokens: int,
) -> dict[str, Any]:
    """Run one part call with its chain of thought bounded.

    Args:
        state: The workflow state at the terminal synthesis node.
        prompt: The rendered prompt for this part.
        schema: The part's JSON schema.
        max_tokens: The part's own answer budget.

    Returns:
        The parsed response.
    """
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["supervisor_model_name"],
            max_tokens=max_tokens,
            temperature=MEDIUM_TEMPERATURE,
            json_schema=schema,
        ),
        options=LLMCallOptions(enable_thinking=False),
    )


def _outline_themes(raw_themes: Any) -> list[dict[str, Any]]:
    """Return the outline's themes, bounded and stripped of malformed ones.

    Bounds are re-imposed here for the same reason ``validate_themes``
    re-imposes them downstream: the production downgrade path (json_object
    mode) does not enforce ``maxItems`` server-side, and here an extra
    theme is not a slice at the end but a whole extra provider request.
    An empty theme is dropped for that same reason -- it would otherwise
    buy a writing call with nothing to write, against a free chain capped
    at roughly 100 requests per model per day.
    """
    if not isinstance(raw_themes, list):
        return []
    themes: list[dict[str, Any]] = []
    for raw in raw_themes[:KNOWLEDGE_BASE_MAX_THEMES]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        raw_sections = raw.get("sections")
        sections = [
            section
            for section in (
                raw_sections[:KNOWLEDGE_BASE_MAX_SECTIONS]
                if isinstance(raw_sections, list)
                else []
            )
            if isinstance(section, dict)
        ]
        if not title or not sections:
            continue
        themes.append({"title": title, "sections": sections})
    return themes


async def plan_knowledge_base_outline(
    state: WorkflowState,
    hypotheses_summary: str,
    evidence_corpus_text: str,
) -> list[dict[str, Any]]:
    """Decide the whole Knowledge Base's structure in one small answer.

    Args:
        state: The workflow state at the terminal synthesis node.
        hypotheses_summary: The numbered top-k summary, for orientation.
        evidence_corpus_text: The pre-formatted corpus for the prompt.

    Returns:
        One entry per theme, each carrying its title and its outlined
        sections; empty when the call did not answer, which leaves the
        overview's own flat topics standing.
    """
    prompt, schema = get_knowledge_base_outline_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=hypotheses_summary,
        evidence_corpus=evidence_corpus_text,
        context=_prompt_context(state),
    )
    try:
        response = await _ask(
            state, prompt, schema, KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception:
        logger.error(
            "Knowledge-base outline failed; publishing the research "
            "overview's own topics instead",
            exc_info=True,
        )
        return []
    return _outline_themes(response.get("themes"))


def format_outline(themes: list[dict[str, Any]]) -> str:
    """Render the whole outline for the writers to steer around."""
    lines: list[str] = []
    for theme in themes:
        lines.append(f"## {theme['title']}")
        lines += [
            f"- {str(section.get('heading') or '').strip()}"
            for section in theme["sections"]
        ]
    return "\n".join(lines)


def format_theme_sections(theme: dict[str, Any]) -> str:
    """Render one theme's headings with the evidence each was assigned."""
    lines: list[str] = []
    for section in theme["sections"]:
        raw_ids = section.get("evidence_ids")
        ids = [
            item
            for item in (raw_ids if isinstance(raw_ids, list) else [])
            if isinstance(item, str)
        ]
        heading = str(section.get("heading") or "").strip()
        lines.append(f"- {heading} (evidence: {', '.join(ids) or 'none'})")
    return "\n".join(lines)


async def write_theme_sections(
    state: WorkflowState,
    theme: dict[str, Any],
    outline_text: str,
    evidence_corpus_text: str,
) -> list[dict[str, Any]]:
    """Write the prose for one outlined theme.

    Failures are absorbed rather than raised: these calls run under one
    ``asyncio.gather``, where a raising sibling cancels the themes that
    were writing perfectly well beside it (the trap ``evolve`` documents).

    Args:
        state: The workflow state at the terminal synthesis node.
        theme: One entry from ``plan_knowledge_base_outline``.
        outline_text: The full outline, so this theme does not repeat one
            of its neighbours.
        evidence_corpus_text: The pre-formatted corpus for the prompt.

    Returns:
        The raw written sections, or empty when this theme did not answer.
    """
    prompt, schema = get_knowledge_base_theme_prompt(
        research_goal=state["research_goal"],
        material=ThemeWritingMaterial(
            title=theme["title"],
            sections=format_theme_sections(theme),
            outline=outline_text,
        ),
        evidence_corpus=evidence_corpus_text,
        context=_prompt_context(state),
    )
    try:
        response = await _ask(
            state, prompt, schema, KNOWLEDGE_BASE_THEME_MAX_TOKENS
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception:
        logger.error(
            "Knowledge-base theme %r failed; publishing the rest of the "
            "section without it",
            theme["title"],
            exc_info=True,
        )
        return []
    written = response.get("sections")
    if not isinstance(written, list):
        return []
    return [item for item in written if isinstance(item, dict)]
