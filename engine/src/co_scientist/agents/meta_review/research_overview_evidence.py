"""Research overview evidence sources and contact-discovery calls."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import Any, Final

from co_scientist.constants import strip_citation_markers
from co_scientist.models import Article
from co_scientist.prompts import PromptRunContext
from co_scientist.state import WorkflowState

_MAX_CONTACT_CANDIDATES: Final = 30
"""Verified authors offered to the model as possible research contacts."""

_MAX_RESEARCH_CONTACTS: Final = 5
"""Grounded contacts kept from the model's response."""

_MAX_RESEARCH_CONTACT_GROUPS: Final = 5
"""Groups kept from the model's response (R14-6) -- bounded like the
contacts themselves, since there cannot usefully be more groups than
there are contacts to put in them."""

_MAX_GROUP_EXAMPLE_HYPOTHESES: Final = 2
"""Example hypotheses kept per group, matching the published exemplar's
two "Example Hypothesis Titles" per research direction (R14-6)."""


def _build_contact_candidates(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build a bounded expert pool exclusively from retrieved-paper authors."""
    candidates: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()
    for article_index, article in enumerate(articles or []):
        if not article.used_in_analysis:
            continue
        for author_index, raw_name in enumerate(article.authors or []):
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
            "research_direction": str(
                raw.get("research_direction") or ""
            ).strip(),
        }
        for raw, candidate in matches
    ]


def _resolve_example_hypothesis_ids(
    raw_indices: Any, hypothesis_by_index: dict[int, str]
) -> list[str]:
    """Resolve a group's example-hypothesis indices to real hypothesis ids.

    R14-6: the model refers to a hypothesis by the same 1-based position
    used in the numbered top-k summary it was shown, never by echoing
    the hypothesis's own text -- a schema that echoes input scales
    output with the pool and truncates identically on every retry (see
    AGENTS.md). An index outside the pool, a non-integer entry, or a
    repeat is dropped rather than guessed at; the caller renders titles
    from the resolved ids, never from anything the model wrote itself.
    """
    if not isinstance(raw_indices, list):
        return []
    ids: list[str] = []
    for raw in itertools.islice(raw_indices, _MAX_GROUP_EXAMPLE_HYPOTHESES):
        hyp_id = hypothesis_by_index.get(raw) if isinstance(raw, int) else None
        if hyp_id is not None and hyp_id not in ids:
            ids.append(hyp_id)
    return ids


def _validate_research_contact_group(
    raw: Any, hypothesis_by_index: dict[int, str]
) -> dict[str, Any] | None:
    """Validate one research-contact group, or None when unnamed."""
    if not isinstance(raw, dict):
        return None
    direction = str(raw.get("research_direction") or "").strip()
    if not direction:
        return None
    return {
        "research_direction": direction,
        "rationale": str(raw.get("rationale") or "").strip(),
        "example_hypothesis_ids": _resolve_example_hypothesis_ids(
            raw.get("example_hypothesis_indices"), hypothesis_by_index
        ),
    }


def _validate_research_contact_groups(
    raw_groups: Any, hypothesis_by_index: dict[int, str]
) -> list[dict[str, Any]]:
    """Keep only well-formed groups, capped and stripped of raw indices.

    Unlike ``_validate_research_contacts``, a group's ``research_direction``
    is not checked against a verified pool -- it is free text the model
    is asked to copy from its own ``research_contacts`` response (MO-7's
    comment on that field: a direction label is not an invented fact the
    way a name or affiliation would be). The renderer matches a group to
    its contacts by that text, so a group whose text does not match any
    contact simply renders no contacts under it.
    """
    if not isinstance(raw_groups, list):
        return []
    validated = (
        _validate_research_contact_group(raw, hypothesis_by_index)
        for raw in raw_groups
    )
    return list(
        itertools.islice(
            (group for group in validated if group is not None),
            _MAX_RESEARCH_CONTACT_GROUPS,
        )
    )


_EVIDENCE_ABSTRACT_CHARS: Final = 3000
"""Per-source abstract budget in the evidence corpus.

Measured rather than assumed, and deliberately left where it is. Over
the analyzed articles of six real-provider runs (239 sources, checkpoint
state, 2026-08/09) abstracts average ~1,590 characters and **two** of the
239 exceeded this cap, by 80 and 306 characters: 386 characters withheld
in total, none of them carrying a number, a unit or an entity name.
Raising the cap therefore buys the deep knowledge-base call (F8) nothing.
It is not what bounds that section's detail.

What bounds it is the field this reads. ``Article.abstract`` is the
abstract as retrieved, while the PMC full text the search tool already
downloaded (``pubmed_search_with_fulltext``) sits unused beside it in
``Article.content`` -- present on 157 of those same 239 analyzed
articles, averaging ~14,000 characters and reaching 68,000. That is where
the published exemplar's class of detail lives: across three of those
runs the corpus abstracts carry 0.0-0.4 number-with-unit mentions per
thousand words against the exemplar knowledge base's 1.9, while their
unread full texts hold roughly ten times the absolute count (196
percentages and 19 dosed concentrations in one run, against 20 and 3 in
the abstracts it did send). So the ceiling on evidence detail here is
corpus *composition* -- abstracts only -- not this cap.

Reading full text in is not the fix either, and the arithmetic is the
reason. The assembled corpus already measures ~400 tokens per source, so
the 132-source production run ``d1273490`` sent roughly 52,000 tokens of
corpus; that run's ``research_overview``-bucket calls billed 337,400
prompt tokens over six attempts, ~56,200 each, i.e. the corpus is nearly
the whole prompt. The same corpus carrying full text would be an order
of magnitude larger than any context this chain's models offer, and
prompt tokens are billed like any other. Moving detail into the section
means *selecting* passages, not lifting a cap -- and note the section
that this corpus produced was not itself numerically thin (3.1
number-with-unit mentions per thousand words on ``d1273490``, above the
exemplar's own 1.9), so the shortfall ``ecc4ec10`` closed was the ask,
not the evidence.

None of the above bounds *how many* sources the corpus holds, and that is
a separate failure with its own measurement. Every parsed search result is
marked ``used_in_analysis`` (``tools/response_parser.py``) and deep
verification appends its probe articles every cycle
(``reflection/deep_verification_evidence.merge_retrieved_articles``), so
the analyzed set grows without bound across a long run. Production
extended run ``bc77950f`` (2026-09-08, cycle 2 interim overview) reached
``prompt_tokens=126,975``; ``openrouter/minimax/minimax-m3:free`` dropped
the stream mid-reasoning on 8 of 8 attempts across two durable task
attempts, and the first fallback answered only at 108,753 prompt tokens on
the third -- 11 provider requests against a ~100/day free cap and ~50
minutes for one answer. ``RESEARCH_OVERVIEW_MAX_SOURCES`` below is the cap
that fixes that, and it is **orthogonal to this one**: it bounds how many
sources are sent, this bounds how much of each. Neither substitutes for
the other, so removing either re-opens a different failure.
"""


RESEARCH_OVERVIEW_MAX_SOURCES: Final = 130
"""How many analyzed sources the corpus may carry.

Set at the largest corpus this chain is known to answer: the assembled
corpus measures ~400 tokens per source, so 130 sources is ~52,000 tokens
of corpus, which is what production run ``d1273490`` sent (132 sources,
~56,200 prompt tokens per call) and had answered. The same three calls
that share this corpus at the terminal firing (draft, accuracy review,
knowledge base's outline, whose own writing calls resend it once per
theme) still fit their output budget beside it. Capping here covers all
of them, since each reaches the corpus through ``_build_evidence_corpus``.
"""


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

    The analyzed list is round-robined across its sources and then cut to
    ``RESEARCH_OVERVIEW_MAX_SOURCES``. Selection is positional, never a
    global sort by ``retrieval_score``: that score floors every web result
    at a normalized 0.0, so sorting by it would drop the web sources whole
    rather than thin every source evenly. Round-robin's first row is one
    article per source, so every source type present survives the cut.

    Evidence ids are assigned by presentation order (contiguous
    ``evidence-1..N`` over the selected articles); downstream consumers
    treat the id as an opaque handle and the app re-resolves cited topics by
    title, so the numbering carries no rank meaning.
    """
    analyzed = [
        article for article in (articles or []) if article.used_in_analysis
    ]
    selected = _interleave_by_source(analyzed)[:RESEARCH_OVERVIEW_MAX_SOURCES]
    corpus: dict[str, dict[str, Any]] = {}
    for index, article in enumerate(selected):
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
    """Format bounded analyzed evidence for cross-source synthesis.

    Strips each source's own inline citation markers from the prompt
    copy only. ``corpus`` itself is left untouched -- it is reused
    verbatim to attach source metadata to the synthesis LLM's cited
    topics (``_validate_knowledge_base``), which is the evidence
    excerpt the finished report ships, and that must stay the abstract
    as retrieved.
    """
    for_prompt = {
        evidence_id: {
            **record,
            "abstract": strip_citation_markers(record["abstract"]),
        }
        for evidence_id, record in corpus.items()
    }
    return _format_or_placeholder(
        for_prompt,
        (
            "- {evidence_id}: title={title}; source={source}; "
            "source_id={source_id}; abstract={abstract}"
        ),
        "No verified evidence corpus available.",
    )


def prompt_context(state: WorkflowState) -> PromptRunContext:
    """The run-scoped prompt context this node's calls render against.

    Args:
        state: The workflow state at the terminal synthesis node.

    Returns:
        The tool registry and run guidance every call here is given.
    """
    return PromptRunContext(
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )
