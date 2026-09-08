"""Deep Knowledge Base synthesis - outlined once, written a theme at a time.

Google's published Knowledge Base is a reference work: 9,702 words over 43
named subject headings grouped into themes, carrying no citation apparatus
anywhere in the span. Ours was one field on the research-overview call,
capped at eight flat topics, and a measured production report rendered
2,079 words of it.

That depth cannot be bought on the overview call, whose draft already
spends ~15.9k of a 24000-token ceiling. So it is bought here instead, gated
to the tiers whose declared ceiling can pay for it, and degrading in every
failure mode to the flat topics the overview call still produces. The gate
is read here rather than in ``app.run_modes``: the tiers set one number
this node can see (``Budget.max_llm_calls``), and a second table naming
tiers would have to be kept in step with it by hand.

**It is not one call.** It was, at ``KNOWLEDGE_BASE_MAX_TOKENS`` (42000),
and that call failed in three consecutive production runs -- nine
attempts, no successes, while every 18000- and 24000-token call in the same
runs answered. This module's own reasoning for the single call was that
raising a budget buys nothing and splitting would multiply one background
section into eight or nine provider requests. Both halves were answered by
the same measurement, and it is the clock, not the budget:

* ``COSCIENTIST_LLM_TIMEOUT_SECONDS`` bounds one call at 600s, and the
  failing attempts measured 27-37 tokens/second (10,080 tokens in 366s;
  20,949 in 563s). 42,000 tokens is 1,100-1,500s of generation at that
  rate, so the request could never have been served: both runs ended the
  retry loop on ``LLMTimeoutError``, and the upstream had already dropped
  the stream itself at 366-563s on the attempts before it.
* The largest *answer* any call produced in either run was 7,644 tokens
  (meta-review, run ``bc77950f``), against the ~20,000 this span needs. No
  budget makes one call deliver it.
* Nothing clamps a request to a model's declared output ceiling, and
  clamping would not have helped: ``minimax/minimax-m3:free`` advertises
  943,718 completion tokens. The declaration was never the constraint.
* The mid-stream ``finish_reason="error"`` is not distinguishable from
  ordinary provider weather -- ``research_overview`` at 24000 hit the same
  shape six times in one run, at 764 to 17,523 tokens -- so
  ``is_transient_provider_error`` correctly waits it out. The waiting was
  only waste because the request could not fit; it fits now.

So: one outline call decides every theme and heading, then one call per
theme writes that theme's prose, concurrently, each bounded well inside the
clock (``research_overview_knowledge_base_calls``). Nine requests where
there was one -- 0.4% of the standard tier's declared 2,500 ceiling, and
0.1% of extended's 7,000, against a section that otherwise publishes
nothing. The other rejected lever, capping reasoning, was not rejected: it
is applied *inside* the parts, where the structural judgment the chain of
thought was defended for has already been made by the outline.

What closed the *depth* gap within that structure is a separate lever and
still applies: measured section by section on production run ``d1273490``
(2026-09-07), 38 subject sections averaged 164 words, median 162, **none
above 213** -- the whole distribution pinned inside the "150-250 words" the
prompt then named, hugging its floor -- against an exemplar averaging 218
with eleven sections above 250 and a 505-word top. So the ask carries
graded word bands whose floor is the exemplar's own mean, a section-count
target the evidence has to support, and the content kinds the exemplar
carries that nothing here used to request -- exhaustive entity enumeration,
every number with its unit, and boundary conditions. Those targets live in
``schemas.knowledge_base`` because the prompt and the schema descriptions
both have to state them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from co_scientist.agents.meta_review import (
    research_overview_knowledge_base_calls as parts,
)
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
the outline call plus one call per theme would be a visible share of what
it spends, for a background section rather than for an idea.

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
        calls counts the requests made, not the ones that answered, since
        the provider was paid for every attempt.
    """
    if not corpus:
        return [], 0
    themes = await parts.plan_knowledge_base_outline(
        state, hypotheses_summary, evidence_corpus_text
    )
    if not themes:
        return [], 1
    outline_text = parts.format_outline(themes)
    written = await asyncio.gather(
        *[
            parts.write_theme_sections(
                state, theme, outline_text, evidence_corpus_text
            )
            for theme in themes
        ]
    )
    raw = [
        {"title": theme["title"], "sections": _grounded_sections(theme, part)}
        for theme, part in zip(themes, written, strict=True)
    ]
    return validate_themes(raw, corpus), 1 + len(themes)


def _grounded_sections(
    theme: dict[str, Any], written: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Restore the outline's evidence ids to sections that cite none.

    Splitting the call split the grounding decision away from the prose:
    the outline chose each subsection's sources, and a writer that answers
    without repeating them would otherwise have its section dropped for
    citing nothing -- which reads as a thin corpus rather than as a lost
    field. Matched on the heading the writer was told to keep verbatim.

    Args:
        theme: The outlined theme, carrying the assigned evidence ids.
        written: The sections that theme's writing call produced.

    Returns:
        The written sections, each carrying evidence ids.
    """
    outlined = {
        str(section.get("heading") or "").strip(): section.get("evidence_ids")
        for section in theme["sections"]
    }
    for section in written:
        if not section.get("evidence_ids"):
            heading = str(section.get("heading") or "").strip()
            section["evidence_ids"] = outlined.get(heading)
    return written


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
