"""Render review summaries, per-axis findings, critiques and deep verification.

Read axis scores from persisted review parts, whose schema matches their
labels. Related articles come from resolved evidence, never model-written
citations. Empty review sections are omitted.
"""

from __future__ import annotations

import json
from typing import Any

from app.report.markdown.references import _reference_label

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
