"""Structured display detail for the drained review rows.

Split out of ``drain_reviews`` when persisting the review block's own
fields took that module past the 500-line ceiling -- the same split the
citation half already took (``drain_citations``). Every name here is
re-exported from ``drain_reviews``, so importers written against that
module keep resolving unchanged.

The division is by *shape*, not by review type: ``drain_reviews`` decides
which rows exist and writes them; this module turns one engine result
into the bounded JSON a row's ``detail_json`` column carries. The prose
``critique`` each row also carries is built there and left untouched --
the workbench reads the prose, the report reads these parts, and neither
is derived from the other.

Every field is display-only. The review-disposition gate reads
``verdict``/``justification`` off the engine result
(``mature_reviews.apply_mature_review_disposition``), never a row.
"""

from __future__ import annotations

import json
from typing import Any

# Bounds for detail_json (R14-22/R14-15): generous enough for genuine
# reader content, tight enough that a malformed json_object-downgrade
# response (an over-long string, a runaway array) cannot inflate the row.
_MAX_DETAIL_ITEMS = 10
_MAX_DETAIL_CHARS = 500
_MAX_SHORT_CHARS = 200
# Reviewer prose (per-axis feedback, the full review's own paragraphs, one
# probe's answer) is the reader-facing body of the report's review block,
# so it needs room a bulleted finding does not: the published per-axis
# sections run to several hundred words each.
_MAX_PROSE_CHARS = 4000
# The review rubric's own 1-10 band (engine schemas/review.py's
# REVIEW_SCORE_MINIMUM/MAXIMUM). A score outside it did not come from the
# rubric, and printing it as "Answer: 47" would read as a real judgement.
_MIN_AXIS_SCORE = 1
_MAX_AXIS_SCORE = 10


def _clip_detail(value: Any, limit: int) -> str:
    """Coerce one possibly-malformed field to a bounded, flat string."""
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


# The eight review axes, in the published Correctness -> Novelty ->
# Feasibility -> Impact-potential order the engine's own _SCORE_CRITERIA
# declares. Named here rather than imported so the app keeps reading a
# drained row without importing an engine schema module at runtime; a
# copied list drifts, so ``tests/test_drain_reviews_detail.py::
# test_review_axes_match_the_engine_score_criteria`` asserts this tuple
# against the engine's own, the way the engine already pins the offline
# backend's copy (``test_offline_llm.py::
# test_review_score_fields_matches_the_schema_criteria``).
#
# Only three of the eight ever reached a column, and one of those under
# another axis's name (the ``plausibility`` column holds
# ``scientific_soundness``). The report's per-axis "Answer: N" line
# therefore had no source for five of them, so all eight travel in
# ``detail_json`` and the renderer reads only from there -- never from the
# columns, whose names do not mean what they say.
_REVIEW_AXES: tuple[str, ...] = (
    "scientific_soundness",
    "plausibility",
    "novelty",
    "testability",
    "potential_impact",
    "relevance",
    "safety",
    "clarity",
)


def _axis_scores(raw: Any) -> dict[str, int]:
    """Keep the declared axes whose score is a usable 1-10 integer.

    Everything else is dropped rather than coerced: production's
    json_object downgrade does not enforce the schema, so an invented axis
    name or a "high" where an integer belongs is an ordinary answer here.
    """
    if not isinstance(raw, dict):
        return {}
    scores: dict[str, int] = {}
    for axis in _REVIEW_AXES:
        value = raw.get(axis)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if _MIN_AXIS_SCORE <= value <= _MAX_AXIS_SCORE:
            scores[axis] = value
    return scores


def _axis_feedback(raw: Any) -> dict[str, str]:
    """Bounded per-axis prose feedback, for the axes that carry any."""
    if not isinstance(raw, dict):
        return {}
    feedback = {}
    for axis in _REVIEW_AXES:
        text = _clip_detail(raw.get(axis), _MAX_PROSE_CHARS)
        if text:
            feedback[axis] = text
    return feedback


def _bounded_list(raw: Any) -> list[str]:
    """Bounded, non-empty entries of one novelty-review list."""
    items = raw if isinstance(raw, list) else []
    return [
        text
        for item in items[:_MAX_DETAIL_ITEMS]
        if (text := _clip_detail(item, _MAX_DETAIL_CHARS))
    ]


def _initial_review_detail(rv: dict[str, Any]) -> dict[str, Any]:
    """The initial review's structured display detail for the report.

    Beside, not instead of, the row's ``critique`` prose: the workbench
    reads the prose and the report reads the parts, and re-deriving the
    parts by parsing the prose back apart is exactly the fragility this
    avoids.
    """
    detail: dict[str, Any] = {}
    for key, value in (
        ("scores", _axis_scores(rv.get("scores"))),
        (
            "constructive_feedback",
            _clip_detail(rv.get("constructive_feedback"), _MAX_PROSE_CHARS),
        ),
        ("detailed_feedback", _axis_feedback(rv.get("detailed_feedback"))),
        ("already_explored", _bounded_list(rv.get("already_explored"))),
        ("novel_aspects", _bounded_list(rv.get("novel_aspects"))),
    ):
        if value:
            detail[key] = value
    return detail


# R12-15/MO-4: Google's own per-assumption reasoning renders each item's
# support as prose -- "Plausible:", "Plausible, but requires careful
# investigation:", "Unknown:" (docs/CORPUS-EXTRACTION.md:4135-4141,
# kira6-detailed-output-validated.md's "Reasoning about assumptions") --
# not the schema's closed enum name. Two of the three values mirror that
# wording directly, matching both the published word and the prompts'
# own definition of the value (full_review.md/deep_verification.md):
# `supported` ("the evidence backs it") is Google's "Plausible:";
# `uncertain` ("the evidence is thin or mixed") is Google's "Plausible,
# but requires careful investigation:". The third does not: `likely_false`
# means "the evidence points against it" -- a genuine negative verdict --
# while every "Unknown:" in the published exemplar marks an assumption
# nothing has tested yet ("limited safety data exists... unknown and
# needs experiments to verify"), not one the evidence contradicts.
# Relabeling `likely_false` as "Unknown" would understate that verdict to
# the reader, so it keeps its own honest label instead of a borrowed,
# mismatched one -- "Implausible", read alongside "Plausible" as its
# direct opposite. The published vocabulary simply carries no negative
# verdict to mirror here; see `docs/PARITY.md` REVIEW-ASSUMPTION-WORDING-001.
#
# The stored enum (`review.py`'s ASSUMPTION_SUPPORT_VALUES) is unchanged --
# `mature_reviews._project_full_review` keys its `assumptions_likely_false`
# filter (fed into the ranking judge's prompt context) off the literal
# `"likely_false"` string, so migrating stored values would silently break
# that filter for a purely cosmetic gain. Only this render-time lookup
# translates the value a reader sees.
_ASSUMPTION_SUPPORT_LABELS: dict[str, str] = {
    "supported": "Plausible",
    "uncertain": "Plausible, but requires careful investigation",
    "likely_false": "Implausible",
}


def _simulation_detail(review: dict[str, Any]) -> dict[str, Any]:
    """Bounded failure_points/decisive_step for the markdown renderer.

    Google's published shape numbers and bolds these (R14-22); nothing
    here or downstream parses or gates on them. ``failure_points`` may
    legitimately be empty -- a ``holds`` verdict names no failure point --
    which the caller renders as no section at all.
    """
    raw_points = review.get("failure_points")
    points = [
        clipped
        for point in (raw_points if isinstance(raw_points, list) else [])[
            :_MAX_DETAIL_ITEMS
        ]
        if (clipped := _clip_detail(point, _MAX_DETAIL_CHARS))
    ]
    decisive_step = _clip_detail(review.get("decisive_step"), _MAX_SHORT_CHARS)
    detail: dict[str, Any] = {}
    if points:
        detail["failure_points"] = points
    if decisive_step:
        detail["decisive_step"] = decisive_step
    return detail


def _verdict_detail(review: dict[str, Any]) -> dict[str, Any]:
    """Bounded Go/No-Go framing for the full/recurrent review (R14-15).

    Display only, rendered verbatim: neither this function nor its
    caller nor the markdown renderer treats either field as a decision --
    the review-disposition gate reads only ``verdict``/``justification``
    (``mature_reviews.apply_mature_review_disposition``), never this.
    """
    go_no_go = _clip_detail(
        review.get("go_no_go_recommendation"), _MAX_SHORT_CHARS
    )
    time_to_verdict = _clip_detail(
        review.get("time_to_verdict"), _MAX_SHORT_CHARS
    )
    detail: dict[str, Any] = {}
    if go_no_go:
        detail["go_no_go"] = go_no_go
    if time_to_verdict:
        detail["time_to_verdict"] = time_to_verdict
    return detail


# R14-14: the published "Reviews summary" block's eight parts, in the
# order every populated published file prints them. Six are bulleted
# lists there and two are prose, which is how the schema declares them
# (engine schemas/review.py REVIEWS_SUMMARY_PARTS) and how they are
# copied here.
_REVIEWS_SUMMARY_PROSE: tuple[str, ...] = ("executive_verdict", "conclusion")
_REVIEWS_SUMMARY_LISTS: tuple[str, ...] = (
    "critical_flaws",
    "addressed_objections",
    "validated_risks",
    "supporting_arguments",
    "alignment_and_novelty",
    "feasibility_assessment",
)


def _reviews_summary_detail(raw: Any) -> dict[str, Any]:
    """Bounded eight-part Reviews summary, part by part (R14-14).

    Optional on the schema (``full_review.md``'s numbered instructions do
    not name it), so an absent or malformed block is an ordinary answer
    and yields no key at all rather than an empty scaffold.
    """
    if not isinstance(raw, dict):
        return {}
    summary: dict[str, Any] = {
        name: text
        for name in _REVIEWS_SUMMARY_PROSE
        if (text := _clip_detail(raw.get(name), _MAX_PROSE_CHARS))
    }
    summary.update(
        {
            name: items
            for name in _REVIEWS_SUMMARY_LISTS
            if (items := _bounded_list(raw.get(name)))
        }
    )
    return summary


def _assumption_detail(item: Any) -> dict[str, str] | None:
    """One full-review assumption as parts, or None when it names nothing.

    The same content ``_assumption_line`` bakes into the row's critique
    prose, kept structured so the report can render the published
    "Detailed Assumptions" list instead of re-splitting a sentence. The
    support verdict carries its reader-facing label (R12-15/MO-4) here
    too, for the one reason the prose does: the enum name is not what
    Google prints.
    """
    if not isinstance(item, dict):
        return None
    assumption = _clip_detail(item.get("assumption"), _MAX_DETAIL_CHARS)
    if not assumption:
        return None
    support = str(item.get("support") or "").strip()
    label = _ASSUMPTION_SUPPORT_LABELS.get(support, support or "unrated")
    return {
        "assumption": assumption,
        "reasoning": _clip_detail(item.get("reasoning"), _MAX_PROSE_CHARS),
        "support": label,
    }


# The full review's prose fields, in the order the report's per-axis
# appendix reads them. The first four are the review's own paragraphs;
# the last four are the published per-axis sub-parts (R14-17) that had no
# field here until the axis sub-structure was built, and they arrive from
# the same full-review call as the rest, so they cost no extra request
# and need no plumbing of their own.
_MATURE_PROSE_FIELDS: tuple[str, ...] = (
    "correctness",
    "quality_and_novelty",
    "literature_grounding",
    "justification",
    "comparison_with_knowledge_base",
    "goal_requirements_assessment",
    "feasibility_reasoning",
    "impact_assessment",
)


def _mature_prose_fields(review: dict[str, Any]) -> dict[str, str]:
    """The full review's non-empty prose fields, each bounded."""
    return {
        name: text
        for name in _MATURE_PROSE_FIELDS
        if (text := _clip_detail(review.get(name), _MAX_PROSE_CHARS))
    }


def _mature_review_detail(review: dict[str, Any]) -> dict[str, Any]:
    """The full/recurrent review's structured display detail.

    Supersedes the Go/No-Go-only ``_verdict_detail``: the prose fields and
    the per-assumption reasoning were already generated and persisted, but
    only as one flat ``critique`` string, which no renderer can take apart
    again. Every field here is display-only -- the disposition gate reads
    ``verdict``/``justification`` off the engine result, never this row.
    """
    detail: dict[str, Any] = _verdict_detail(review)
    detail.update(_mature_prose_fields(review))
    if steps := _bounded_list(review.get("feasibility_steps")):
        detail["feasibility_steps"] = steps
    raw = review.get("assumptions")
    assumptions = [
        parsed
        for item in (raw if isinstance(raw, list) else [])[:_MAX_DETAIL_ITEMS]
        if (parsed := _assumption_detail(item))
    ]
    if assumptions:
        detail["assumptions"] = assumptions
    if summary := _reviews_summary_detail(review.get("reviews_summary")):
        detail["reviews_summary"] = summary
    return detail


def _deep_verification_detail(
    probes: list[dict[str, Any]], verdict: Any
) -> dict[str, Any]:
    """Deep verification's probes as parts, for the report (R14-15).

    ``format_deep_verification_critique`` renders the same content into
    the row's ``critique``, but two-space-indented under a probe header --
    a shape markdown collapses into one paragraph. The report reads these
    parts instead and prints the published ``Question:``/``Answer:``/
    ``Reasoning:`` triple; the prose column is left exactly as it was for
    the workbench, which already reads it.
    """
    entries: list[dict[str, Any]] = []
    for probe in probes[:_MAX_DETAIL_ITEMS]:
        if not isinstance(probe, dict):
            continue
        question = _clip_detail(probe.get("question"), _MAX_DETAIL_CHARS)
        if not question:
            continue
        entries.append(
            {
                "question": question,
                "answer": _clip_detail(probe.get("answer"), _MAX_PROSE_CHARS),
                "reasoning": _clip_detail(
                    probe.get("reasoning"), _MAX_PROSE_CHARS
                ),
                "fundamental": bool(probe.get("assumption_is_fundamental")),
            }
        )
    if not entries:
        return {}
    return {
        "verdict": str(verdict or "unspecified"),
        "probes": entries,
    }


def _detail_json(detail: dict[str, Any]) -> str | None:
    """Serialize one row's display detail, or None when it has none.

    None rather than ``"{}"``: an empty JSON object in the column reads
    as "this review had structured detail and it was empty", which is a
    different fact from "this review type carries none".
    """
    return json.dumps(detail) if detail else None


def _review_detail_json(key: str, review: dict[str, Any]) -> str | None:
    """Return one mature review's structured display detail, or None.

    Simulation carries its failure points and decisive step; full and
    recurrent carry the Go/No-Go framing, the review's own prose, its
    assumptions, and the eight-part Reviews summary. Every other key
    carries none.
    """
    if key == "simulation":
        detail = _simulation_detail(review)
    elif key in ("full", "recurrent"):
        detail = _mature_review_detail(review)
    else:
        detail = {}
    return _detail_json(detail)
