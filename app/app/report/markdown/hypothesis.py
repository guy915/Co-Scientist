"""Report section rendering one numbered 'Top hypotheses' entry."""

from __future__ import annotations

import json
import re
from typing import Any

from app.citations import (
    CitationMetadata,
    DateState,
    SourceType,
    classify_date,
    classify_source_type,
)
from app.claims.gate import claim_status, role_of
from app.human_input import SCIENTIST_MANUAL_ORIGIN
from app.report.markdown.document import _ABOUT_DISCLOSURE, _SYSTEM_NAME
from app.text_utils import hypothesis_statement, hypothesis_title

# Matches the fixed prefix _persist_one_citation writes: "[C1] cited in
# hypothesis". Anchored so a citation row from a different, unrelated
# concern (e.g. a hand-seeded demo citation whose claim is the hypothesis
# statement itself) is recognized as unresolvable rather than mismatched.
_CLAIM_KEY_PREFIX = re.compile(r"^\[(C\d+)\]")

# Matches a trailing "et al."/"et al" credit some curated author fields
# write inline (e.g. "Kim et al.") rather than as a separate authors list
# -- stripped before resolving a first-author surname, or the literal
# "al." reads as the surname.
_ET_AL_SUFFIX = re.compile(r"\s+et\s+al\.?\s*$", re.IGNORECASE)


def _citation_key(claim: str) -> str | None:
    """Extract a citation row's [C*] key from its fixed-format claim prefix.

    Returns None when the claim does not carry a recognizable key -- a row
    from before this drain format, or from a different producer entirely.
    """
    match = _CLAIM_KEY_PREFIX.match(claim)
    return match.group(1) if match else None


def _reference_label(evidence: dict[str, Any]) -> str:
    """Build a reference's display label from its evidence row.

    Mirrors the engine's own short citation label (author/year, or the
    title alone for a source with no authors -- e.g. a knowledge-graph
    statement, whose "title" already carries its full display text; see
    ``drain.citations._ensure_citation_evidence_id``).
    """
    title = str(evidence.get("title") or "").strip()
    authors = evidence.get("authors") or []
    year = evidence.get("year")
    # A curated author credit is sometimes written "Kim et al." rather
    # than a bare surname -- strip that suffix before taking the last
    # word, or the literal "al." resolves as the surname.
    first_author_text = (
        _ET_AL_SUFFIX.sub("", str(authors[0]).strip()) if authors else ""
    )
    first_author = first_author_text.split()[-1] if first_author_text else ""
    if first_author and year:
        prefix = f"{first_author} et al., {year}"
        return f"{prefix} — {title}" if title else prefix
    return title or "Untitled source"


def _render_reference_line(key: str, evidence: dict[str, Any]) -> str:
    """Render one '- **[Ck]** label' line, linked when the source has a URL."""
    label = _reference_label(evidence)
    url = str(evidence.get("url") or "")
    text = f"[{label}]({url})" if url else label
    return f"- **[{key}]** {text}"


def references_by_hypothesis(
    citations: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Group a run's citation rows into per-hypothesis (key, evidence) lists."""
    evidence_by_id = {str(row.get("id")): row for row in evidence}
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for citation in citations:
        key = _citation_key(str(citation.get("claim") or ""))
        source = evidence_by_id.get(str(citation.get("evidence_id") or ""))
        if key is None or source is None:
            continue
        hyp_id = str(citation.get("hypothesis_id") or "")
        grouped.setdefault(hyp_id, []).append((key, source))
    for entries in grouped.values():
        entries.sort(key=lambda pair: int(pair[0][1:]))
    return grouped


def _render_references_markdown(
    entries: list[tuple[str, dict[str, Any]]],
) -> list[str]:
    """Render one hypothesis's 'References' subsection, or nothing when empty.

    Repo convention (unlike the published corpus, which always prints the
    heading): omit the heading along with the body when there is nothing to
    list, rather than showing an empty "References" section.
    """
    if not entries:
        return []
    lines = ["#### References", ""]
    lines.extend(_render_reference_line(key, source) for key, source in entries)
    lines.append("")
    return lines


def _normalized_title(title: str) -> str:
    """Collapse whitespace/case for the title-based dedup fallback key."""
    return " ".join(title.strip().lower().split())


def _evidence_identity(evidence: dict[str, Any]) -> str:
    """Return one evidence row's dedup identity: DOI > PMID > URL > title.

    Always resolves to something -- ``evidence.title`` is ``NOT NULL`` in
    the schema, so the title fallback never actually fails for real data.
    The row's own id is a last-resort key for a synthetic/test row with
    none of the above, so an unidentifiable row is never merged with
    another one that is equally unidentifiable.
    """
    doi = str(evidence.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    pmid = str(evidence.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    url = str(evidence.get("url") or "").strip()
    if url:
        return f"url:{url}"
    title = _normalized_title(str(evidence.get("title") or ""))
    if title:
        return f"title:{title}"
    return f"id:{evidence.get('id')}"


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a run's evidence rows to one per stable identity.

    First-seen wins -- the caller hands rows in ``store.list_evidence``'s
    own ``created_at`` order, so the survivor is always the earliest-
    persisted copy of a source the run retrieved more than once, not
    whichever the caller's own iteration happens to visit first.
    """
    by_identity: dict[str, dict[str, Any]] = {}
    for row in evidence:
        by_identity.setdefault(_evidence_identity(row), row)
    return list(by_identity.values())


def _identifier_suffix(evidence: dict[str, Any]) -> str:
    """Trailing '(DOI: ...)' / '(PMID: ...)' when the row carries one.

    Same DOI-then-PMID precedence as ``_evidence_identity`` -- whichever
    identifier is authoritative for dedup is also the one shown.
    """
    doi = str(evidence.get("doi") or "").strip()
    if doi:
        return f" (DOI: {doi})"
    pmid = str(evidence.get("pmid") or "").strip()
    if pmid:
        return f" (PMID: {pmid})"
    return ""


def _retracted_suffix(evidence: dict[str, Any]) -> str:
    """Flag a withdrawn source -- the same fact the Learning tab pins (D18).

    A bibliography listing a retracted paper as a plain reference is the
    exact defect the Learning tab's own retracted pill exists to avoid.
    """
    return " (retracted)" if evidence.get("retracted") else ""


# Only the source types a reader would otherwise mistake for a reviewed
# paper are named. A peer-reviewed article is what a bibliography entry
# already reads as, so labelling it adds a word to every line and
# distinguishes nothing; an unclassifiable row says nothing rather than
# claiming a type it does not know.
_SOURCE_TYPE_WORDS = {
    SourceType.PREPRINT: "preprint",
    SourceType.DATABASE: "database record",
    SourceType.WEB: "web page",
    SourceType.DOCUMENT: "attached document",
}


def _row_metadata(evidence: dict[str, Any]) -> CitationMetadata:
    """Read one evidence row back as the citation metadata it describes."""
    return CitationMetadata(
        url=str(evidence.get("url") or ""),
        doi=str(evidence.get("doi") or ""),
        pmid=str(evidence.get("pmid") or ""),
        retracted=bool(evidence.get("retracted")),
        source=str(evidence.get("source") or ""),
        year=evidence.get("year"),
    )


def _row_source_type(evidence: dict[str, Any]) -> SourceType:
    """Resolve one row's source type, persisted value first.

    The drain's classification saw the publisher's declared publication
    type, which this row no longer carries, so it wins where it exists;
    a row predating the column, or evidence that never went through the
    drain, is classified from what it does carry.
    """
    stored = str(evidence.get("source_type") or "")
    if stored in {member.value for member in SourceType}:
        return SourceType(stored)
    return classify_source_type(_row_metadata(evidence))


def _source_type_suffix(source_type: SourceType) -> str:
    """Name a source that is not a peer-reviewed paper."""
    word = _SOURCE_TYPE_WORDS.get(source_type)
    return f" ({word})" if word else ""


def _date_suffix(evidence: dict[str, Any], source_type: SourceType) -> str:
    """Say when a reference's date is missing or cannot be real."""
    state = classify_date(_row_metadata(evidence))
    if state is DateState.MISSING and source_type.is_publication:
        return " (no date)"
    if state is DateState.IMPLAUSIBLE:
        return " (date not verifiable)"
    return ""


def _render_reference_entry(evidence: dict[str, Any]) -> str:
    """Render one '- label' bullet, linked when the row has a URL."""
    source_type = _row_source_type(evidence)
    label = (
        _reference_label(evidence)
        + _identifier_suffix(evidence)
        + _source_type_suffix(source_type)
        + _date_suffix(evidence, source_type)
        + _retracted_suffix(evidence)
    )
    url = str(evidence.get("url") or "")
    text = f"[{label}]({url})" if url else label
    return f"- {text}"


def _render_references_section(evidence: list[dict[str, Any]]) -> list[str]:
    """Render the run-wide 'References' section, or nothing when empty."""
    deduped = _dedupe_evidence(evidence)
    if not deduped:
        return []
    ordered = sorted(deduped, key=lambda row: _reference_label(row).casefold())
    lines = ["", "## References", ""]
    lines.extend(_render_reference_entry(row) for row in ordered)
    lines.append("")
    return lines


# How many cited articles one axis lists. The published exemplars print
# two to five; the cap is what keeps a heavily-cited idea from turning
# one axis into a bibliography.
_MAX_RELATED_ARTICLES = 6

# One abstract's printed length. Google prints a one-to-two-sentence
# relevance note rather than the abstract in full, and the rows here hold
# whole abstracts, so they are cut to roughly that.
_MAX_ABSTRACT_CHARS = 400

Reference = tuple[str, dict[str, Any]]


def _abstract_excerpt(source: dict[str, Any]) -> str:
    """The article's abstract, flattened and cut to a published-length note."""
    text = " ".join(str(source.get("abstract") or "").split())
    if len(text) <= _MAX_ABSTRACT_CHARS:
        return text
    return text[:_MAX_ABSTRACT_CHARS].rstrip() + "..."


def _related_articles(
    references: list[Reference], with_abstracts: bool
) -> list[str]:
    """The published ``Related Article Abstracts`` list for one axis."""
    entries = references[:_MAX_RELATED_ARTICLES]
    if not entries:
        return []
    label = (
        "**Related Article Abstracts**"
        if with_abstracts
        else "**Related Article Abstract Titles**"
    )
    lines = [label, ""]
    for key, source in entries:
        line = f"- **[{key}]** {_reference_label(source)}"
        if with_abstracts and (excerpt := _abstract_excerpt(source)):
            line += f": {excerpt}"
        lines.append(line)
    return [*lines, ""]


def _prose(label: str, value: Any) -> list[str]:
    """A labeled prose paragraph, or nothing when the field is empty."""
    text = str(value or "").strip()
    return [f"**{label}**", "", text, ""] if text else []


def _steps(label: str, items: Any) -> list[str]:
    """The published numbered ``Steps to Test the Idea`` list."""
    entries = [
        text
        for item in (items if isinstance(items, list) else [])
        if (text := str(item).strip())
    ]
    if not entries:
        return []
    numbered = [f"{n}. {text}" for n, text in enumerate(entries, start=1)]
    return [f"**{label}**", "", *numbered, ""]


def _feasibility_extras(
    initial: dict[str, Any], mature: dict[str, Any]
) -> list[str]:
    """The published Feasibility axis's own two judged parts.

    Steps to Test the Idea -> Reasoning about Feasibility. With the
    related-article list its caller attaches, that is the leanest of the
    four published axes (3 parts) and the shape 13 of the 19 files print.
    """
    del initial
    return [
        *_steps("Steps to Test the Idea", mature.get("feasibility_steps")),
        *_prose(
            "Reasoning about Feasibility", mature.get("feasibility_reasoning")
        ),
    ]


def _impact_extras(
    initial: dict[str, Any], mature: dict[str, Any]
) -> list[str]:
    """The published Impact potential axis's own closing assessment.

    Google also reprints Detailed Assumptions and Suggested Improvements
    under this axis; both are already printed once under Correctness from
    the single field each has here, and printing the same paragraph twice
    in one entry reads as a rendering fault rather than as fidelity.
    """
    del initial
    return _prose("Overall Impact Potential", mature.get("impact_assessment"))


def related_article_abstracts(references: list[Reference]) -> list[str]:
    """Correctness's ``Related Article Abstracts``, abstracts included.

    The one axis that prints them in full: it is the axis whose judgment
    is *about* whether the evidence backs the hypothesis, so the abstract
    is the thing being weighed rather than a pointer to it.
    """
    return _related_articles(references, with_abstracts=True)


def related_article_titles(references: list[Reference]) -> list[str]:
    """The leaner ``Related Article Abstract Titles`` list (5/19 files)."""
    return _related_articles(references, with_abstracts=False)


# R14-17: Google's published appendix names four axes, in this order.
# This system scores eight; the four that map carry Google's own heading
# (Correctness's second axis, ``plausibility``, has no prose feedback and
# so usually renders as its score alone), and the four that map to
# nothing in the published rubric keep their own names rather than being
# forced into a heading that would misdescribe them.
_AXIS_SECTIONS: tuple[tuple[str, str], ...] = (
    ("scientific_soundness", "Correctness"),
    ("plausibility", "Plausibility"),
    ("novelty", "Novelty"),
    ("testability", "Feasibility"),
    ("potential_impact", "Impact potential"),
    ("relevance", "Relevance"),
    ("safety", "Safety"),
    ("clarity", "Clarity"),
)

# R14-14: the published block's eight numbered headings, verbatim, keyed
# by the schema field each is filled from
# (``schemas/review.py::REVIEWS_SUMMARY_PARTS``).
_REVIEWS_SUMMARY_SECTIONS: tuple[tuple[str, str], ...] = (
    ("executive_verdict", "1. Executive Verdict"),
    ("critical_flaws", "2. Critical Flaws"),
    ("addressed_objections", "3. Addressed Objections"),
    ("validated_risks", "4. Validated Risks & Limitations"),
    ("supporting_arguments", "5. Supporting Arguments & Evidence (Motivation)"),
    ("alignment_and_novelty", "6. Alignment & Novelty"),
    ("feasibility_assessment", "7. Feasibility Assessment (Go/No-Go Decision)"),
    ("conclusion", "8. Conclusion"),
)


def _latest_detail(
    reviews: list[dict[str, Any]], reviewer_agent: str
) -> dict[str, Any]:
    """Return the newest parsed review detail for one agent, or ``{}``."""
    for row in reversed(reviews):
        if row.get("reviewer_agent") != reviewer_agent:
            continue
        try:
            parsed = json.loads(row.get("detail_json") or "null")
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _mature_detail(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """The freshest of the two reviews sharing the full-review schema.

    A recurrent review supersedes an earlier full review, matching
    ``report.markdown.hypothesis._render_hypothesis_verdict``'s own
    precedence for the Go/No-Go framing drained from the same rows.
    """
    return _latest_detail(reviews, "recurrent_review") or _latest_detail(
        reviews, "full_review"
    )


def _bullets(label: str, items: Any) -> list[str]:
    """A labeled bulleted list, or nothing when it names nothing."""
    entries = [
        text
        for item in (items if isinstance(items, list) else [])
        if (text := str(item).strip())
    ]
    if not entries:
        return []
    return [label, *[f"- {entry}" for entry in entries], ""]


def _assumption_lines(mature: dict[str, Any]) -> list[str]:
    """The published "Detailed Assumptions" list (MO-9).

    Each entry pairs the support verdict in Google's own wording -- the
    label ``drain.review_detail._assumption_detail`` already resolved --
    with the assumption and the free-text reasoning behind it.
    """
    raw = mature.get("assumptions")
    lines: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        entry = f"- **{item.get('support')}:** {item.get('assumption')}"
        if reasoning := str(item.get("reasoning") or "").strip():
            entry += f" — {reasoning}"
        lines.append(entry)
    return ["**Detailed Assumptions**", "", *lines, ""] if lines else []


def _correctness_extras(
    initial: dict[str, Any], mature: dict[str, Any]
) -> list[str]:
    """Everything the published Correctness axis carries beyond its prose."""
    return [
        *_assumption_lines(mature),
        *_prose(
            "Comparison with Knowledge Base",
            mature.get("comparison_with_knowledge_base"),
        ),
        *_prose("Reasoning about Correctness", mature.get("correctness")),
        *_prose("Strength of Evidence", mature.get("literature_grounding")),
        *_prose("Suggested Improvements", initial.get("constructive_feedback")),
        *_prose(
            "Goal Requirement Assessment",
            mature.get("goal_requirements_assessment"),
        ),
        *_prose(
            "Final Reasoning and Recommendation", mature.get("justification")
        ),
    ]


def _novelty_extras(
    initial: dict[str, Any], mature: dict[str, Any]
) -> list[str]:
    """The novelty review's two named lists (MO-3), plus the full review's.

    Google's published novelty review *is* these two lists -- "Aspects
    already explored:" and "Novel Aspects:" -- which is why they render
    here rather than being folded into the axis's own prose feedback.
    """
    return [
        *_prose("Reasoning about Novelty", mature.get("quality_and_novelty")),
        *_bullets("Aspects already explored:", initial.get("already_explored")),
        *_bullets("Novel Aspects:", initial.get("novel_aspects")),
    ]


# Extra content one axis carries beyond its own prose feedback. R14-17:
# all four of Google's named axes carry their own sub-structure; the four
# axes this system adds beyond that rubric are feedback plus their score,
# since the published rubric names nothing for them.
_AXIS_EXTRAS = {
    "scientific_soundness": _correctness_extras,
    "novelty": _novelty_extras,
    "testability": _feasibility_extras,
    "potential_impact": _impact_extras,
}

# The published per-axis article list, keyed by axis. Correctness prints
# the abstracts themselves; the leaner axes print titles only, the form 5
# of the 19 published files use -- the same abstract repeated under all
# four axes would quadruple the longest block in the entry and tell a
# reader nothing new. Sourced from the hypothesis's own citations, never
# from the model (see ``report.markdown.reviews``).
_AXIS_ARTICLES = {
    "scientific_soundness": related_article_abstracts,
    "novelty": related_article_titles,
    "testability": related_article_titles,
    "potential_impact": related_article_titles,
}


def _axis_findings(
    axis: str, initial: dict[str, Any], mature: dict[str, Any]
) -> list[str]:
    """One axis's own judged content: its prose feedback, then its parts."""
    feedback = initial.get("detailed_feedback") or {}
    extras = _AXIS_EXTRAS.get(axis)
    text = str(feedback.get(axis) or "").strip()
    return [
        *([text, ""] if text else []),
        *(extras(initial, mature) if extras else []),
    ]


def _axis_section(
    axis: str,
    label: str,
    initial: dict[str, Any],
    mature: dict[str, Any],
    references: list[Reference],
) -> list[str]:
    """One published review axis: its findings, then its own score line.

    The related-article list rides an axis that was actually judged: it
    is context for a verdict, not a verdict, so an axis the review never
    scored or commented on stays omitted rather than printing a heading
    over a bibliography.
    """
    findings = _axis_findings(axis, initial, mature)
    score = (initial.get("scores") or {}).get(axis)
    if not findings and score is None:
        return []
    articles = _AXIS_ARTICLES.get(axis)
    lines = [f"##### {label}", ""]
    lines += articles(references) if articles else []
    lines += findings
    # The published axis closes on its own bolded rating (R14-18); an
    # unscored axis simply omits the line rather than printing a zero.
    if score is not None:
        lines += [f"**Answer: {score}**", ""]
    return lines


def _render_hypothesis_reviews(
    reviews: list[dict[str, Any]],
    references: list[Reference] | None = None,
) -> list[str]:
    """Render one hypothesis's ``Appendix:`` / ``All reviews:`` block (F1)."""
    initial = _latest_detail(reviews, "review")
    mature = _mature_detail(reviews)
    cited = list(references or [])
    body: list[str] = []
    for axis, label in _AXIS_SECTIONS:
        body += _axis_section(axis, label, initial, mature, cited)
    if not body:
        return []
    return ["#### Appendix:", "", "**All reviews:**", "", *body]


def _reviews_summary_section(key: str, label: str, value: Any) -> list[str]:
    """One numbered part of the published Reviews summary block."""
    body = (
        [str(value).strip(), ""]
        if isinstance(value, str)
        else [f"- {text}" for item in value if (text := str(item).strip())]
    )
    if not [line for line in body if line]:
        return []
    trailer = [] if isinstance(value, str) else [""]
    return [f"##### {label}", "", *body, *trailer]


def _render_reviews_summary(reviews: list[dict[str, Any]]) -> list[str]:
    """Render the published eight-part ``Reviews summary`` block."""
    summary = _mature_detail(reviews).get("reviews_summary")
    if not isinstance(summary, dict):
        return []
    body: list[str] = []
    for key, label in _REVIEWS_SUMMARY_SECTIONS:
        value = summary.get(key)
        if isinstance(value, (str, list)):
            body += _reviews_summary_section(key, label, value)
    return ["#### Reviews summary", "", *body] if body else []


def _probe_lines(index: int, probe: dict[str, Any]) -> list[str]:
    """One deep-verification probe as the published Q/A/Reasoning triple."""
    flag = "fundamental" if probe.get("fundamental") else "non-fundamental"
    lines = [f"**Probe {index} ({flag} assumption)**", ""]
    for label, key in (
        ("Question", "question"),
        ("Answer", "answer"),
        ("Reasoning", "reasoning"),
    ):
        if text := str(probe.get(key) or "").strip():
            lines += [f"{label}: {text}", ""]
    return lines


# The two Reviews-summary parts that carry negative critique, keyed in
# the published rollup order (R10-8). The other six parts are the idea's
# positives, verdict and feasibility, and stay in the Reviews summary
# block above rather than in this negative-only rollup.
_CRITIQUE_PARTS: tuple[str, ...] = ("critical_flaws", "validated_risks")


def _critique_entries(summary: dict[str, Any]) -> list[str]:
    """The negative-critique bullets from a full review's own summary."""
    entries: list[str] = []
    for key in _CRITIQUE_PARTS:
        value = summary.get(key)
        if isinstance(value, str):
            if text := value.strip():
                entries.append(text)
        elif isinstance(value, list):
            entries += [t for item in value if (t := str(item).strip())]
    return entries


def _render_critiques_rollup(reviews: list[dict[str, Any]]) -> list[str]:
    """Render the per-idea negative-critique rollup."""
    summary = _mature_detail(reviews).get("reviews_summary")
    if not isinstance(summary, dict):
        return []
    entries = _critique_entries(summary)
    if not entries:
        return []
    return [
        "#### Critiques",
        "",
        "Here's a summary of the negative critiques from the reviews:",
        "",
        *[f"- {entry}" for entry in entries],
        "",
    ]


def _render_deep_verification(reviews: list[dict[str, Any]]) -> list[str]:
    """Render the deep-verification probes and verdict (F2)."""
    detail = _latest_detail(reviews, "deep_verification")
    raw = detail.get("probes")
    probes = [item for item in (raw or []) if isinstance(item, dict)]
    if not probes:
        return []
    lines = ["#### Deep verification", ""]
    if verdict := str(detail.get("verdict") or "").strip():
        lines += [f"**Verdict:** {verdict}", ""]
    for index, probe in enumerate(probes, start=1):
        lines += _probe_lines(index, probe)
    return lines


# R14-13: byte-identical across all 19 published hypothesis files
# (docs/CORPUS-EXTRACTION.md R14-13) -- a fixed disclaimer, not derived
# from the hypothesis, so it carries no field guard and always renders.
# Shared with the report-level About disclosure (R14-4,
# ``report.markdown.document._ABOUT_DISCLOSURE``) -- Google's two published
# instances of this wording are byte-identical, so this re-exports the one
# constant rather than maintaining a second copy of the string.
_HYPOTHESIS_DISCLAIMER = _ABOUT_DISCLOSURE

# Mirrors ``co_scientist.models.SCIENTIST_REVIEWER`` -- the app-side
# review rows carry the same literal in ``reviewer_agent``, and there is no
# shared app constant for it (it is duplicated module-locally wherever the
# distinction is needed, e.g. ``engine_adapter.drain.reviews``).
_SCIENTIST_REVIEWER = "scientist"


def _render_evidence_span(span: Any, relation: str) -> str:
    """Render one exact supporting or contradicting source span."""
    if not isinstance(span, dict):
        quote = " ".join(str(span).split())
        return f"  - {relation} span: “{quote}”"
    quote = " ".join(str(span.get("quote") or "").split())
    source_title = str(
        span.get("source_title")
        or span.get("source")
        or span.get("evidence_id")
        or "Evidence passage"
    )
    url = str(span.get("url") or "")
    source = f"[{source_title}]({url})" if url else source_title
    return f"  - {relation} span — {source}: “{quote}”"


_ASSESSMENT_METHODS = {
    "legacy_unknown": "not recorded",
    "no_evidence": "no candidate evidence",
    "deterministic_lexical": "lexical comparison",
    "model_primary": "model judgment",
    "lexical_founded": "model judgment with a lexical contradiction check",
    "contradiction_guard_rejected": (
        "contradiction rejected by provenance checks"
    ),
    "model_opposition_verified": (
        "separate model opposition check (not scientific validation)"
    ),
    "model_opposition_unconfirmed": (
        "model opposition check did not confirm contradiction"
    ),
}


def _render_claim_evidence(edges: list[dict[str, Any]]) -> list[str]:
    """Render every persisted claim verdict for one released hypothesis."""
    if not edges:
        return []
    lines = ["**Claim evidence:**", ""]
    for edge in edges:
        claim = str(edge.get("claim") or "")
        lines.append(f"- **{claim_status(edge)} · {role_of(edge)}** — {claim}")
        method = _ASSESSMENT_METHODS.get(
            str(edge.get("verification_method")), "not recorded"
        )
        lines.append(f"  Assessment method: {method}.")
        for span in edge.get("supporting") or []:
            lines.append(_render_evidence_span(span, "Supporting"))
        for span in edge.get("contradicting") or []:
            lines.append(_render_evidence_span(span, "Contradicting"))
    lines.append("")
    return lines


def _render_hypothesis_scene_setting(hyp: dict[str, Any]) -> list[str]:
    """Render the Introduction/Recent findings scene-setting subsections.

    MO-6: the published proposal opens with an Introduction and a Recent
    findings and related research section before the mechanism -- rendered
    here in that order, ahead of the proposed hypothesis itself.
    """
    lines: list[str] = []
    for label, value in (
        ("Introduction", hyp.get("introduction")),
        ("Recent findings and related research", hyp.get("recent_findings")),
    ):
        if value:
            lines += [f"#### {label}", "", str(value), ""]
    return lines


def _render_hypothesis_mechanism(hyp: dict[str, Any]) -> list[str]:
    """Render the Mechanism/Predicted effect subsections."""
    lines: list[str] = []
    for label, value in (
        ("**Mechanism:**", hyp.get("mechanism")),
        ("**Predicted effect:**", hyp.get("expected_effect")),
    ):
        if value:
            lines += [f"{label} {value}", ""]
    return lines


def _render_hypothesis_experiment(hyp: dict[str, Any]) -> list[str]:
    """Render the "Steps to Test the Idea" pilot-plan subsection (R14-20).

    ``experimental_context`` (the store's name for the engine's
    ``Hypothesis.experiment``) is already the fully-formatted markdown
    text a populated run produces -- numbered steps then separately
    bolded ``**Go:**``/``**No-Go:**`` lines, built by the engine's
    ``format_experiment_plan`` -- so this is a straight pass-through, the
    same shape as ``_render_hypothesis_safety`` below. An older run's
    plain-paragraph experiment (predating this structure, or a downgrade
    response the engine could not structure) still renders correctly:
    it is just prose under the same heading.
    """
    experiment = hyp.get("experimental_context")
    if not experiment:
        return []
    return ["#### Steps to test the idea", "", str(experiment), ""]


def _render_hypothesis_safety(hyp: dict[str, Any]) -> list[str]:
    """Render the proposer's own Safety and toxicity subsection.

    MO-10: the proposer's own pharmacological safety assessment -- not the
    reviewer's safety_ethical_concerns (dual-use/ethics), which renders in
    the reviews surface instead.
    """
    safety_and_toxicity = hyp.get("safety_and_toxicity")
    if not safety_and_toxicity:
        return []
    return ["#### Safety and toxicity", "", str(safety_and_toxicity), ""]


def _reviews_by_hypothesis(
    reviews: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group review rows by hypothesis id in one pass.

    Feeds the per-entry Go/No-Go framing and simulation-review renderers
    (R14-15/R14-22); every review row belongs to exactly one hypothesis.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        key = str(review.get("hypothesis_id") or "")
        grouped.setdefault(key, []).append(review)
    return grouped


def _is_unreviewed_scientist_admission(
    hyp: dict[str, Any], reviews: list[dict[str, Any]]
) -> bool:
    """True when a scientist-authored idea holds no peer review.

    HITL-MANUAL-HYP-001 residual window: a scientist contribution admitted
    on the cycle that spends the run's last ``max_llm_calls`` request reaches
    the report before the owed-review override can force a REFLECT pass -- the
    override refuses to race the provider-request seam that would crash the
    forced review with a permanent task failure. Such an idea is published
    unreviewed, so the report labels it distinctly. A scientist's own review
    is not a peer review (``co_scientist.models.has_peer_review``), so
    it does not clear the flag.
    """
    if hyp.get("created_by_agent") != SCIENTIST_MANUAL_ORIGIN:
        return False
    return not any(
        review.get("reviewer_agent") != _SCIENTIST_REVIEWER
        for review in reviews
    )


def _render_scientist_admission_notice(
    hyp: dict[str, Any], reviews: list[dict[str, Any]]
) -> list[str]:
    """Render the unreviewed-scientist-admission notice, or nothing.

    Leads the entry's body (right under the disclaimer) so a reader sees the
    provenance before the idea's own claims.
    """
    if not _is_unreviewed_scientist_admission(hyp, reviews):
        return []
    return [
        "**Scientist-contributed — not yet reviewed:** this idea was added "
        "by a scientist and reached the report before the automated review "
        "agents assessed it.",
        "",
    ]


def _review_detail(
    reviews: list[dict[str, Any]], reviewer_agent: str
) -> dict[str, Any]:
    """Return one review row's parsed ``detail_json``, or ``{}``.

    Every failure mode degrades to the same empty result rather than
    raising: no row under this ``reviewer_agent`` (a run that predates
    the mature cascade, or the review never ran), a NULL/empty column (a
    run that predates this column, or a review with nothing structured
    to say), unparseable JSON, or JSON that parsed to something other
    than an object.
    """
    for row in reviews:
        if row.get("reviewer_agent") != reviewer_agent:
            continue
        raw = row.get("detail_json")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _render_hypothesis_simulation_review(
    reviews: list[dict[str, Any]],
) -> list[str]:
    """Render the simulation review's numbered failure points (R14-22).

    Google's published shape lists each failure point as a bolded name
    plus a reasoning paragraph. Our schema's ``failure_points`` is a flat
    string array with no separate name field, so there is no honest way
    to split one point into both -- each numbered item bolds its ordinal
    label instead and carries the point's own text as its reasoning.

    Omitted entirely (no heading, no body) when the mechanism holds --
    the schema's intended output for a sound mechanism, and therefore the
    common case on published runs -- or the review never reached this
    hypothesis at all. Matches this repo's own render convention
    (R14-23): omit rather than print an empty section.
    """
    detail = _review_detail(reviews, "simulation_review")
    raw_points = detail.get("failure_points")
    points = [
        text
        for point in (raw_points if isinstance(raw_points, list) else [])
        if (text := str(point).strip())
    ]
    decisive_step = str(detail.get("decisive_step") or "").strip()
    if not points and not decisive_step:
        return []
    lines = ["#### Simulation review", ""]
    for idx, text in enumerate(points, start=1):
        lines.append(f"{idx}. **Failure point:** {text}")
    if points:
        lines.append("")
    if decisive_step:
        lines += [f"**Decisive step:** {decisive_step}", ""]
    return lines


def _render_hypothesis_verdict(reviews: list[dict[str, Any]]) -> list[str]:
    """Render the full/recurrent review's display-only Go/No-Go framing.

    R14-15: Google's published shape carries a bolded free-text
    ``Verdict: <recommendation>`` and a ``Time to Verdict:`` timeframe --
    a testing recommendation, distinct from this system's own
    ``sound``/``needs_revision``/``rejected`` review verdict enum.

    Display only, by construction: nothing downstream of the full/
    recurrent review call reads either field. The review-disposition
    gate reads only ``verdict``/``justification``
    (``mature_reviews.apply_mature_review_disposition``), and the
    prompt-context summary the ranking judge, evolution, and meta-review
    all read stops at the same two fields
    (``mature_reviews._project_full_review``) -- this renderer is the
    only consumer of ``go_no_go``/``time_to_verdict`` in the codebase.
    A recurrent review supersedes an earlier full review's framing when
    both rows exist, matching which one is the fresher assessment.
    """
    detail = _review_detail(reviews, "recurrent_review") or _review_detail(
        reviews, "full_review"
    )
    go_no_go = str(detail.get("go_no_go") or "").strip()
    time_to_verdict = str(detail.get("time_to_verdict") or "").strip()
    lines: list[str] = []
    if go_no_go:
        lines += [f"**Verdict:** {go_no_go}", ""]
    if time_to_verdict:
        lines += [f"**Time to Verdict:** {time_to_verdict}", ""]
    return lines


def _render_hypothesis_review_surface(
    reviews: list[dict[str, Any]],
    references: list[tuple[str, dict[str, Any]]],
) -> list[str]:
    """Render this hypothesis's review-derived blocks, in published order.

    R14-15/R14-22: the reviewer's own findings for this hypothesis --
    display-only Go/No-Go framing, then the simulation review's numbered
    failure points -- sit after the proposer's own content and before this
    system's claim-evidence extension.

    R14-26 fixes the published order of these review-side subsections:
    Reviews summary, then the Appendix's All reviews block, then Deep
    verification. The Go/No-Go framing sits between the first two --
    published files carry it inside the Reviews summary's own
    "Feasibility Assessment" part, and this renders it as the two bolded
    lines it has always been rather than moving it into a block whose
    coverage differs. The simulation review is this system's own analogue
    of the published flaw list (R14-22) and keeps its place ahead of deep
    verification. R10-8: the entry then closes on the synthesized per-idea
    ``Critiques`` rollup, the last review-side block before this system's
    own claim-evidence extension.

    Args:
        reviews: Every persisted review row for this hypothesis.
        references: The same (citation key, evidence row) pairs the
            entry's References section prints from, reused for the
            per-axis Related Article Abstracts lists (R14-17) -- the one
            published sub-part that must be attached rather than asked
            of a model, since it echoes the review prompt's own input.
    """
    lines: list[str] = []
    lines += _render_reviews_summary(reviews)
    lines += _render_hypothesis_verdict(reviews)
    lines += _render_hypothesis_reviews(reviews, references)
    lines += _render_hypothesis_simulation_review(reviews)
    lines += _render_deep_verification(reviews)
    # R10-8: the published per-idea document closes on a synthesized
    # negative-critique rollup, after all the detailed review material.
    lines += _render_critiques_rollup(reviews)
    return lines


def _render_hypothesis_entry(
    i: int,
    hyp: dict[str, Any],
    edges: list[dict[str, Any]],
    references: list[tuple[str, dict[str, Any]]],
    reviews: list[dict[str, Any]],
) -> list[str]:
    """Render one numbered 'Top hypotheses' entry.

    Title and statement both resolve through the shared ``text_utils``
    helpers, so this entry and the payload's Agent-insights panel name the
    same idea with the same words. R14-13: every entry carries the
    published disclaimer right under its title, unconditionally -- the
    only always-present line among this function's mostly-optional
    subsections.

    R14-12: the title is bold and product-prefixed, mirroring Google's
    ``# **<Product> - <Title>**`` shape with this system's own name in
    place of Google's. The heading level stays ``###`` rather than
    Google's H1 -- this entry is a subsection of the Goal Report's own
    ``## Top hypotheses`` section, not a standalone per-hypothesis
    document, and promoting it to H1 would break the document's own
    heading hierarchy without making it any more like Google's actual
    per-file shape (see R14-26, still a DECISION, on whether a
    per-hypothesis document ever exists here at all).
    """
    title = hypothesis_title(hyp)
    lines = [
        f"### {i}. **{_SYSTEM_NAME} - {title}**"
        f"  _Elo: {hyp.get('elo_rating', '')}_",
        _HYPOTHESIS_DISCLAIMER,
        "",
    ]
    lines += _render_scientist_admission_notice(hyp, reviews)
    lines += _render_hypothesis_scene_setting(hyp)
    if statement := hypothesis_statement(hyp):
        lines += [f"**Proposed hypothesis:** {statement}", ""]
    lines += _render_hypothesis_mechanism(hyp)
    lines += _render_hypothesis_experiment(hyp)  # R14-20, right after Mechanism
    # Resolves the [C*] keys the mechanism text just cited -- the engine's
    # per-hypothesis reference index, joined back from citations+evidence
    # (see report.markdown.references). Right after Mechanism/Predicted
    # effect, the text the keys actually appear in.
    #
    # R14-26: Google's canonical hypothesis-document order places
    # Safety and toxicity inside "Proposal" alongside the L1 References,
    # but doesn't settle their order relative to each other -- the one
    # exemplar checked (kira6-detailed-output-validated.md, MO-10) never
    # shows a References heading near its own Safety section at all. Kept
    # here rather than reordered on that ambiguous evidence.
    lines += _render_references_markdown(references)
    lines += _render_hypothesis_safety(hyp)
    lines += _render_hypothesis_review_surface(reviews, references)
    # Claim evidence stays last, as our own extension beyond the
    # published review-side subsections above.
    lines += _render_claim_evidence(edges)
    return lines
