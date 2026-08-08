"""Research-overview node - terminal synthesis into a roadmap + NIH aims."""

import itertools
import logging
from collections.abc import Iterator
from typing import Any, Final

from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    PROGRESS_RESEARCH_OVERVIEW_START,
    RESEARCH_OVERVIEW_MAX_TOKENS,
    RESEARCH_OVERVIEW_TOP_K,
)
from co_scientist.llm import (
    CompletionSpec,
    call_llm_json,
)
from co_scientist.models import (
    Article,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
    rank_for_publication,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import (
    PromptRunContext,
    get_research_overview_prompt,
)
from co_scientist.safety import is_blocking_status
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Bounds on what the terminal synthesis prompt offers the model and accepts
# back. The offered pools are capped so a large run's article set cannot grow
# the prompt without limit; the acceptance caps bound the sections a reader is
# handed.
_MAX_CONTACT_CANDIDATES: Final = 30
"""Verified authors offered to the model as possible research contacts."""

_MAX_RESEARCH_CONTACTS: Final = 5
"""Grounded contacts kept from the model's response."""

_MAX_KNOWLEDGE_BASE_TOPICS: Final = 8
"""Knowledge-base topics considered from the model's response."""

_EVIDENCE_ABSTRACT_CHARS: Final = 3000
"""Per-source abstract budget in the evidence corpus."""


async def research_overview_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesize the top-k hypotheses into an overview + NIH Specific Aims.

    Only hypotheses the publication gates release are offered to the model:
    the pool is filtered before the LLM call, because prose synthesized
    from a blocked idea cannot be unlabeled afterwards.

    Args:
        state: The current workflow state.

    Returns:
        A state delta carrying the research overview, metrics, and a message.
    """
    hypotheses = state.get("hypotheses", [])
    publishable = _publishable_hypotheses(hypotheses)
    if not publishable:
        # Nothing survived to this terminal node (e.g. an earlier failure
        # or all hypotheses were pruned), or the publication gates
        # withheld every remaining hypothesis; skip the LLM call rather
        # than synthesizing an overview from an empty or excluded pool.
        if hypotheses:
            logger.warning(
                "Research overview skipped: publication gates withheld all "
                "%d hypotheses; nothing to synthesize",
                len(hypotheses),
            )
        return {"research_overview": {}}

    articles = state.get("articles")
    summary = _summarize_top_hypotheses(publishable)
    contact_candidates = _build_contact_candidates(articles)
    evidence_corpus = _build_evidence_corpus(articles)

    await emit_progress(
        state,
        "research_overview_start",
        "Synthesizing research overview...",
        PROGRESS_RESEARCH_OVERVIEW_START,
    )

    research_overview = await _synthesize_research_overview(
        state, summary, contact_candidates, evidence_corpus
    )

    await emit_progress(
        state,
        "research_overview_complete",
        "Research overview ready",
        PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    )
    logger.info("Research overview complete")
    return _build_research_overview_result(research_overview)


def _publishable_hypotheses(
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Filter to the hypotheses the final report would publish.

    Mirrors the report's exclusions on engine-side state: the tournament's
    rankability test (``Hypothesis.is_rankable``) plus the blocking safety
    outcomes. Ideas needing revision publish, as do undermined ones
    (demoted, not withheld); duplicates are pruned upstream.

    Args:
        hypotheses: The hypothesis pool at the terminal node.

    Returns:
        The publishable hypotheses, in pool order.
    """
    return [
        h
        for h in hypotheses
        if h.is_rankable() and not is_blocking_status(h.safety_status)
    ]


def _summarize_top_hypotheses(hypotheses: list[Hypothesis]) -> str:
    """Ranks hypotheses for publication and formats the top-k summary.

    Re-ranks defensively (does not assume the incoming list is already
    sorted) and keeps only the strongest ``RESEARCH_OVERVIEW_TOP_K``
    hypotheses so the synthesis prompt stays a bounded size.
    ``rank_for_publication``, not plain Elo: an undermined idea publishes
    but must not headline the synthesis, and its Elo -- won before the
    verdict doubting it -- is what would put it there.

    Args:
        hypotheses: The publishable hypothesis pool.

    Returns:
        A newline-joined, numbered summary of the top-k hypotheses.
    """
    ranked = rank_for_publication(hypotheses)
    top = ranked[:RESEARCH_OVERVIEW_TOP_K]
    return "\n".join(
        f"{i + 1}. (Elo {h.elo_rating}) {h.text}" for i, h in enumerate(top)
    )


async def _synthesize_research_overview(
    state: WorkflowState,
    summary: str,
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Builds the research-overview prompt, calls the LLM, and formats it.

    Uses the supervisor model (strategic synthesis, not a worker task);
    meta_review and the durable run guidance steer it toward the same
    strategic themes used elsewhere in the workflow.

    Args:
        state: Current workflow state.
        summary: Top-k hypotheses summary from _summarize_top_hypotheses.
        contact_candidates: Verified authors keyed by a stable candidate id.
        evidence_corpus: Analyzed sources keyed by a stable evidence id.

    Returns:
        "overview" and "nih_specific_aims" dicts, each defaulting to empty
        so consumers always see a well-formed research_overview shape.
    """
    prompt, schema = get_research_overview_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        contact_candidates=_format_contact_candidates(contact_candidates),
        evidence_corpus=_format_evidence_corpus(evidence_corpus),
        context=PromptRunContext(
            meta_review=state.get("meta_review"),
            tool_registry=state.get("tool_registry"),
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
        ),
    )
    response = await _call_research_overview_llm(state, prompt, schema)
    return _format_research_overview_response(
        response, contact_candidates, evidence_corpus
    )


async def _call_research_overview_llm(
    state: WorkflowState, prompt: str, schema: dict[str, Any] | None
) -> dict[str, Any]:
    """Calls the supervisor model to synthesize the research overview.

    Budgeted above the thinking floor: the multi-paragraph strategy
    document and the chain of thought must share one allowance.
    """
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=state["supervisor_model_name"],
            max_tokens=RESEARCH_OVERVIEW_MAX_TOKENS,
            temperature=MEDIUM_TEMPERATURE,
            json_schema=schema,
        ),
    )


def _format_research_overview_response(
    response: dict[str, Any],
    contact_candidates: dict[str, dict[str, Any]],
    evidence_corpus: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Formats and validates the raw LLM response into the overview shape."""
    return {
        "overview": response.get("overview", {}),
        "nih_specific_aims": response.get("nih_specific_aims", {}),
        "research_contacts": _validate_research_contacts(
            response.get("research_contacts"), contact_candidates
        ),
        "knowledge_base": _validate_knowledge_base(
            response.get("knowledge_base"), evidence_corpus
        ),
    }


def _build_contact_candidates(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build a bounded expert pool exclusively from retrieved-paper authors."""
    candidates: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()
    for article_index, article in enumerate(articles or []):
        if not article.used_in_analysis:
            continue
        for author_index, raw_name in enumerate(article.authors):
            name = raw_name.strip()
            normalized = name.casefold()
            if (
                not name
                or normalized in seen_names
                or len(candidates) >= _MAX_CONTACT_CANDIDATES
            ):
                continue
            candidate_id = f"author-{article_index + 1}-{author_index + 1}"
            candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "name": name,
                "source_id": article.source_id or "",
                "source_title": article.title,
                "source_url": article.url or "",
                "source": article.source,
            }
            seen_names.add(normalized)
    return candidates


def _format_or_placeholder(
    records: dict[str, dict[str, Any]], template: str, empty_message: str
) -> str:
    """Render bounded records as bullet lines, or a placeholder when empty.

    Args:
        records: Bounded records keyed by a stable id.
        template: A str.format template applied to each record's fields.
        empty_message: Returned verbatim when there are no records.

    Returns:
        Newline-joined bullet lines, or empty_message.
    """
    if not records:
        return empty_message
    return "\n".join(template.format(**record) for record in records.values())


def _format_contact_candidates(
    candidates: dict[str, dict[str, Any]],
) -> str:
    """Format the verified candidate pool for the synthesis prompt."""
    return _format_or_placeholder(
        candidates,
        (
            "- {candidate_id}: {name}; paper={source_title}; "
            "source_id={source_id}; url={source_url}"
        ),
        "No verified literature authors available.",
    )


def _valid_candidate_id(raw: Any, seen: set[str]) -> str | None:
    """Return raw's candidate id if it is an unseen, well-formed reference.

    Args:
        raw: One raw contact entry from the model response.
        seen: Candidate ids already accepted in this validation pass.

    Returns:
        The candidate id, or None if raw is malformed or already used.
    """
    if not isinstance(raw, dict):
        return None
    candidate_id = raw.get("candidate_id")
    if not isinstance(candidate_id, str) or candidate_id in seen:
        return None
    return candidate_id


def _matching_candidate(
    candidate_id: str,
    raw: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the verified candidate if raw's name matches it exactly."""
    candidate = candidates.get(candidate_id)
    if candidate is None:
        return None
    if raw.get("name") != candidate["name"]:
        return None
    return candidate


def _iter_matching_contacts(
    raw_contacts: list[Any],
    candidates: dict[str, dict[str, Any]],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (raw, candidate) for each unseen exact candidate match."""
    seen: set[str] = set()
    for raw in raw_contacts:
        candidate_id = _valid_candidate_id(raw, seen)
        if candidate_id is None:
            continue
        candidate = _matching_candidate(candidate_id, raw, candidates)
        if candidate is None:
            continue
        seen.add(candidate_id)
        yield raw, candidate


def _validate_research_contacts(
    raw_contacts: Any,
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only exact candidate matches and attach immutable provenance."""
    if not isinstance(raw_contacts, list):
        return []
    matches = itertools.islice(
        _iter_matching_contacts(raw_contacts, candidates),
        _MAX_RESEARCH_CONTACTS,
    )
    return [
        {
            **candidate,
            "expertise": str(raw.get("expertise") or "").strip(),
            "justification": str(raw.get("justification") or "").strip(),
        }
        for raw, candidate in matches
    ]


def _interleave_by_source(articles: list[Article]) -> list[Article]:
    """Round-robin analyzed articles across their source.

    Search results reach this node ranked best-first by retrieval score, which
    clusters each source's top papers at the front of the list. Presenting that
    order to the synthesis LLM makes it over-cite the first few references and
    ignore the tail, so the knowledge base ends up drawn from one source's top
    hits. Interleaving one paper per source at a time keeps best-first order
    within each source while ensuring the head of the corpus samples the full
    breadth of retrieved evidence rather than a single leading cluster.

    Args:
        articles: Analyzed articles in their incoming best-first order.

    Returns:
        The same articles reordered round-robin across ``source``.
    """
    groups: dict[str, list[Article]] = {}
    for article in articles:
        groups.setdefault(article.source, []).append(article)
    interleaved: list[Article] = []
    for row in itertools.zip_longest(*groups.values()):
        interleaved.extend(article for article in row if article is not None)
    return interleaved


def _build_evidence_corpus(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build the terminal synthesis corpus from articles actually analyzed.

    Evidence ids are assigned by presentation order (contiguous
    ``evidence-1..N``) over the source-interleaved list; downstream consumers
    treat the id as an opaque handle and the app re-resolves cited topics by
    title, so the numbering carries no rank meaning.
    """
    analyzed = [
        article for article in (articles or []) if article.used_in_analysis
    ]
    corpus: dict[str, dict[str, Any]] = {}
    for index, article in enumerate(_interleave_by_source(analyzed)):
        evidence_id = f"evidence-{index + 1}"
        corpus[evidence_id] = {
            "evidence_id": evidence_id,
            "source_id": article.source_id or "",
            "title": article.title,
            "abstract": (article.abstract or "")[:_EVIDENCE_ABSTRACT_CHARS],
            "source": article.source,
            "url": article.url or "",
        }
    return corpus


def _format_evidence_corpus(corpus: dict[str, dict[str, Any]]) -> str:
    """Format bounded analyzed evidence for cross-source synthesis."""
    return _format_or_placeholder(
        corpus,
        (
            "- {evidence_id}: title={title}; source={source}; "
            "source_id={source_id}; abstract={abstract}"
        ),
        "No verified evidence corpus available.",
    )


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


def _build_research_overview_result(
    research_overview: dict[str, Any],
) -> dict[str, Any]:
    """Assembles the research_overview_node return dict.

    Args:
        research_overview: Assembled research_overview dict.

    Returns:
        Dict with updated state fields (research_overview, metrics,
        messages).
    """
    # Only the delta (one LLM call) is passed here; merge_metrics (models.py)
    # adds it to the existing cumulative totals in state.
    metrics = create_metrics_update(deltas=MetricDeltas(llm_calls=1))
    # research_overview has no reducer annotation in state.py, so this is a
    # plain overwrite -- appropriate since this node runs once, terminally.
    return {
        "research_overview": research_overview,
        "metrics": metrics,
        "messages": phase_message(
            "research_overview",
            "Synthesized research overview and Specific Aims",
        ),
    }
