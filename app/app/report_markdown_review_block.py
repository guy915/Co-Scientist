"""The per-idea review block: Reviews summary, All reviews, probes.

Every review a run performs was already generated, paid for and
persisted, and the Goal Report printed none of it. Google's published
per-hypothesis documents carry roughly 3,800 words of review per idea --
an ``Appendix:``/``All reviews:`` block per axis, an eight-part
``Reviews summary`` above it, and a deep-verification section below --
against zero words on our side. Nothing here calls a model: the three
renderers read the ``detail_json`` the drain already writes
(``engine_adapter/drain_review_detail.py``).

Homed apart from ``report_markdown_hypothesis`` because that module is
the per-entry assembly point and was already near the size ceiling; the
names are re-exported from ``report_markdown`` so that namespace keeps
resolving.

Two conventions this file keeps:

* **Read the parts, never the columns.** Three of the eight axis scores
  have columns on ``reviews`` and one of those holds another axis's value
  (the ``plausibility`` column carries ``scientific_soundness``), so a
  renderer mixing the two prints one axis's score under another's name.
* **Omit rather than print an empty heading** (R14-23). Coverage is
  uneven by design -- the mature cascade reaches only the top slice of
  the pool (``research_adapter/budget.py::reviewed_hypothesis_limit``),
  so on a small tier some ideas carry a full review and some do not.
"""

from __future__ import annotations

import json
from typing import Any

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
    """Return the newest row's parsed ``detail_json`` for one agent, or ``{}``.

    Newest, not first: ``store.list_reviews`` orders by creation time and
    a hypothesis can be reviewed more than once (the recurrent review, a
    re-review after evolution), so the last matching row is the current
    assessment. Every failure mode -- no such row, a NULL column on a run
    predating it, unparseable JSON, JSON that is not an object -- degrades
    to the same empty result, which the callers render as no section.
    """
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
    ``report_markdown_hypothesis._render_hypothesis_verdict``'s own
    precedence for the Go/No-Go framing drained from the same rows.
    """
    return _latest_detail(reviews, "recurrent_review") or _latest_detail(
        reviews, "full_review"
    )


def _prose(label: str, value: Any) -> list[str]:
    """A labeled prose paragraph, or nothing when the field is empty."""
    text = str(value or "").strip()
    return [f"**{label}**", "", text, ""] if text else []


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
    label ``drain_review_detail._assumption_detail`` already resolved --
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
    """Everything the published Correctness axis carries beyond its prose.

    The published order inside this axis is Detailed Assumptions ->
    Reasoning about Correctness -> Strength of Evidence -> Suggested
    Improvements -> Final Reasoning and Recommendation, which is what the
    fields below are laid out as.
    """
    return [
        *_assumption_lines(mature),
        *_prose("Reasoning about Correctness", mature.get("correctness")),
        *_prose("Strength of Evidence", mature.get("literature_grounding")),
        *_prose("Suggested Improvements", initial.get("constructive_feedback")),
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


# Extra content one axis carries beyond its own prose feedback. Only the
# two axes the published appendix elaborates appear; every other axis is
# feedback plus its score, as published.
_AXIS_EXTRAS = {
    "scientific_soundness": _correctness_extras,
    "novelty": _novelty_extras,
}


def _axis_section(
    axis: str, label: str, initial: dict[str, Any], mature: dict[str, Any]
) -> list[str]:
    """One published review axis: its findings, then its own score line."""
    feedback = initial.get("detailed_feedback") or {}
    body = [
        *(
            [str(feedback.get(axis)).strip(), ""]
            if str(feedback.get(axis) or "").strip()
            else []
        ),
        *(_AXIS_EXTRAS[axis](initial, mature) if axis in _AXIS_EXTRAS else []),
    ]
    score = (initial.get("scores") or {}).get(axis)
    if not body and score is None:
        return []
    lines = [f"##### {label}", ""]
    lines += body
    # The published axis closes on its own bolded rating (R14-18); an
    # unscored axis simply omits the line rather than printing a zero.
    if score is not None:
        lines += [f"**Answer: {score}**", ""]
    return lines


def _render_hypothesis_reviews(reviews: list[dict[str, Any]]) -> list[str]:
    """Render one hypothesis's ``Appendix:`` / ``All reviews:`` block (F1).

    Args:
        reviews: Every persisted review row for this hypothesis.

    Returns:
        The rendered lines, or nothing at all when this hypothesis
        carries no structured review detail -- the common case on a small
        tier, where the cascade reaches only the leaders.
    """
    initial = _latest_detail(reviews, "review")
    mature = _mature_detail(reviews)
    body: list[str] = []
    for axis, label in _AXIS_SECTIONS:
        body += _axis_section(axis, label, initial, mature)
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
    """Render the published eight-part ``Reviews summary`` block (F6, R14-14).

    Filled by the full review's own call -- the block is a field on
    ``FULL_REVIEW_SCHEMA``, not a second request -- so a hypothesis the
    mature cascade never reached carries none, and prints none.

    Args:
        reviews: Every persisted review row for this hypothesis.

    Returns:
        The rendered lines, or nothing when no part was answered.
    """
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


def _render_deep_verification(reviews: list[dict[str, Any]]) -> list[str]:
    """Render the deep-verification probes and verdict (F2).

    The probe triple is pinned against Google's published exemplar on the
    engine side (``test_published_artifact_shapes.py::
    test_deep_verification_probe_matches_published_exemplar``); this is
    the render of the same triple. The row's ``critique`` column carries
    the same content as one indented prose blob, which markdown collapses
    into a single paragraph -- the structured parts are read instead.

    Args:
        reviews: Every persisted review row for this hypothesis.

    Returns:
        The rendered lines, or nothing when verification never probed
        this hypothesis.
    """
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
