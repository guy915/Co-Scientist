"""Deep Knowledge Base synthesis - its own call, its own budget (F8).

Google's published Knowledge Base is a reference work: 9,702 words over 43
named subject headings grouped into themes, carrying no citation apparatus
anywhere in the span. Ours was one field on the research-overview call,
capped at eight flat topics, and a measured production report rendered
2,079 words of it.

That depth cannot be bought on the overview call. Its draft already spends
~15.9k of a 24000-token ceiling that is itself the escalation ladder's own
top rung, and the published span alone measures 19,084 tokens - asking for
both in one answer is the ``finish_reason="length"`` walk the thinking-
budget gotcha describes. So this is a second call with a budget sized from
that measurement (``KNOWLEDGE_BASE_MAX_TOKENS``), gated to the tiers whose
declared ceiling can pay for it, and degrading in every failure mode to the
flat topics the overview call still produces.

The gate is read here rather than in ``app.run_modes``: the tiers set one
number this node can see (``Budget.max_llm_calls``), and a second table
naming tiers would have to be kept in step with it by hand.

What closed the *remaining* gap was the opposite of that reasoning, and
the distinction is worth keeping: a second call bought the structure, but
the depth inside it was bounded by what the prompt asked for, not by what
the call could afford. Measured section by section on production run
``d1273490`` (2026-09-07): 38 subject sections averaging 164 words,
median 162, **none above 213** -- the whole distribution pinned inside
the "150-250 words" the prompt then named, hugging its floor -- against
an exemplar averaging 218 with eleven sections above 250 and a 505-word
top. Of the 3,142-word shortfall, roughly a third is the five missing
sections and two thirds is per-section thinness. That answer is ~11k
tokens against this call's 42000-token ceiling, so raising the ceiling
buys nothing (and on this chain a reasoning model spends whatever it is
given); splitting per theme would multiply one background section into
eight or nine provider requests against a ~100/day per-model cap; and
capping reasoning the way entailment does (``MINIMAL_REASONING_MAX_
TOKENS``, reachable only via ``enable_thinking=False``) trades away the
one thing composing 40+ themed sections actually uses reasoning for.
So the lever is the ask: graded word bands whose floor is the exemplar's
own mean, a section-count target the evidence has to support, and the
content kinds the exemplar carries that nothing here used to request --
exhaustive entity enumeration, every number with its unit, and boundary
conditions. Those targets live in ``schemas.knowledge_base`` because the
prompt and the schema descriptions both have to state them.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from co_scientist.constants import (
    KNOWLEDGE_BASE_MAX_TOKENS,
    MEDIUM_TEMPERATURE,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.prompts import PromptRunContext, get_knowledge_base_prompt
from co_scientist.schemas.synthesis import (
    KNOWLEDGE_BASE_MAX_SECTIONS,
    KNOWLEDGE_BASE_MAX_THEMES,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

_MAX_KNOWLEDGE_BASE_TOPICS: Final = 8
"""Flat knowledge-base topics accepted from the overview call itself.

The shallower shape this module falls back to, unchanged: the overview
call still produces it on every run, and it is what publishes wherever
the deep synthesis is unfunded or does not answer.
"""

KNOWLEDGE_BASE_MIN_LLM_CALLS: Final = 2500
"""Smallest declared run ceiling that funds the deep synthesis.

Exactly the standard tier's ``max_llm_calls`` (``app.run_modes``), so the
gate reads "standard and above". Express declares 1200 and is the tier
this is withheld from: its whole run is four ideas and one iteration, and
a single 42000-token call would be a visible share of what it spends,
for a background section rather than for an idea.

A run that declares no ceiling at all does not fund it either. Every
production run declares one (``engine_adapter.opts`` sets it from the
tier), so an absent ceiling means a caller that never chose a tier -- a
test, a dev script, the in-process reference path -- and reading that as
"unbounded, therefore yes" would spend the largest call in the engine on
whoever forgot to say.
"""


def knowledge_base_is_funded(state: WorkflowState) -> bool:
    """Whether this run's declared ceiling pays for the deep synthesis.

    Args:
        state: The workflow state at the terminal synthesis node.

    Returns:
        True when the run declares a ceiling at or above
        ``KNOWLEDGE_BASE_MIN_LLM_CALLS``.
    """
    ceiling = (state.get("budget") or {}).get("max_llm_calls")
    return ceiling is not None and int(ceiling) >= KNOWLEDGE_BASE_MIN_LLM_CALLS


async def synthesize_knowledge_base(
    state: WorkflowState,
    hypotheses_summary: str,
    corpus: dict[str, dict[str, Any]],
    evidence_corpus_text: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Synthesize the themed Knowledge Base from this run's evidence.

    Args:
        state: The workflow state at the terminal synthesis node.
        hypotheses_summary: The same numbered top-k summary the overview
            call is given, for orientation only.
        corpus: The evidence corpus, keyed by evidence id. Reused verbatim
            to attach immutable source metadata to a cited section.
        evidence_corpus_text: The pre-formatted corpus for the prompt;
            rebuilt from ``corpus`` by the caller, which already renders it
            for the overview call.

    Returns:
        Tuple of (one topic per grounded section, in reading order; LLM
        calls spent). Both empty when there is nothing to synthesize from;
        a failed call returns no topics but still reports its cost, since
        the provider was paid for the attempt.
    """
    if not corpus:
        return [], 0
    prompt, schema = get_knowledge_base_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=hypotheses_summary,
        evidence_corpus=evidence_corpus_text,
        context=PromptRunContext(
            tool_registry=state.get("tool_registry"),
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
        ),
    )
    try:
        response = await call_llm_json(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=state["supervisor_model_name"],
                max_tokens=KNOWLEDGE_BASE_MAX_TOKENS,
                temperature=MEDIUM_TEMPERATURE,
                json_schema=schema,
            ),
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception:
        logger.error(
            "Knowledge-base synthesis failed; publishing the research "
            "overview's own topics instead",
            exc_info=True,
        )
        return [], 1
    return validate_themes(response.get("themes"), corpus), 1


def _section_topic(
    raw: Any,
    theme: str,
    corpus: dict[str, dict[str, Any]],
    index: int,
) -> dict[str, Any] | None:
    """Build one themed topic from a raw section, or None if unusable.

    Unusable means malformed, or citing no evidence id this run actually
    analyzed -- the same rule the overview call's own flat topics follow,
    so an ungrounded section cannot reach the report by taking the deeper
    route.
    """
    if not isinstance(raw, dict):
        return None
    raw_ids = raw.get("evidence_ids")
    ids = [
        item
        for item in (raw_ids if isinstance(raw_ids, list) else [])
        if isinstance(item, str) and item in corpus
    ]
    heading = str(raw.get("heading") or "").strip()
    if not ids or not heading:
        return None
    return {
        "id": f"topic-{index}",
        "theme": theme,
        "title": heading,
        "summary": "",
        "detail": str(raw.get("detail") or "").strip(),
        "uncertainty": "",
        "references": [corpus[item] for item in ids],
    }


def _theme_topics(
    raw_theme: Any, corpus: dict[str, dict[str, Any]], offset: int
) -> list[dict[str, Any]]:
    """Return one theme's grounded sections, numbered from ``offset``."""
    if not isinstance(raw_theme, dict):
        return []
    theme = str(raw_theme.get("title") or "").strip()
    raw_sections = raw_theme.get("sections")
    sections = raw_sections if isinstance(raw_sections, list) else []
    topics: list[dict[str, Any]] = []
    for raw in sections[:KNOWLEDGE_BASE_MAX_SECTIONS]:
        topic = _section_topic(raw, theme, corpus, offset + len(topics) + 1)
        if topic is not None:
            topics.append(topic)
    return topics


def validate_themes(
    raw_themes: Any, corpus: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten the themed response into the report's topic list.

    One topic per subsection, each carrying its theme, so the renderer
    prints a theme heading once above the sections that belong to it and
    the existing evidence-resolution path is unchanged. Bounds are
    re-imposed here because the production downgrade path (json_object
    mode) does not enforce ``maxItems`` server-side.

    Args:
        raw_themes: The raw ``themes`` array from the model response.
        corpus: The evidence corpus, keyed by evidence id.

    Returns:
        The grounded sections, in the order the model wrote them.
    """
    if not isinstance(raw_themes, list):
        return []
    topics: list[dict[str, Any]] = []
    for raw_theme in raw_themes[:KNOWLEDGE_BASE_MAX_THEMES]:
        topics += _theme_topics(raw_theme, corpus, len(topics))
    return topics


def _topic_evidence_ids(
    raw: Any, corpus: dict[str, dict[str, Any]]
) -> list[str] | None:
    """Return a raw topic's grounded evidence ids, or None if ungrounded.

    Args:
        raw: One raw knowledge-base topic from the model response.
        corpus: The bounded evidence corpus topics may cite.

    Returns:
        The subset of cited ids present in corpus, or None if raw is
        malformed or cites no valid evidence.
    """
    if not isinstance(raw, dict):
        return None
    raw_ids = raw.get("evidence_ids")
    if not isinstance(raw_ids, list):
        return None
    evidence_ids = [
        item for item in raw_ids if isinstance(item, str) and item in corpus
    ]
    return evidence_ids or None


def _validate_knowledge_base(
    raw_topics: Any,
    corpus: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop unsourced topics and attach immutable source metadata."""
    if not isinstance(raw_topics, list):
        return []
    topics: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_topics[:_MAX_KNOWLEDGE_BASE_TOPICS]):
        evidence_ids = _topic_evidence_ids(raw, corpus)
        if evidence_ids is None:
            continue
        topics.append(
            {
                "id": f"topic-{index + 1}",
                "title": str(raw.get("title") or "").strip(),
                "summary": str(raw.get("summary") or "").strip(),
                "detail": str(raw.get("detail") or "").strip(),
                "uncertainty": str(raw.get("uncertainty") or "").strip(),
                "references": [corpus[item] for item in evidence_ids],
            }
        )
    return topics
