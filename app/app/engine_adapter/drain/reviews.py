"""Review persistence for the final-state drain."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import app.store as store
from app.citations import CitationRecord, classify_citation
from app.claims.assessor import SENTENCE_SPLIT
from app.report import format_deep_verification_critique

# Bracketed citation groups inside a grounding sentence: "[C1]", "[C1, C3]".
_BRACKET_GROUP = re.compile(r"\[([^\[\]]+)\]")


@dataclass(frozen=True)
class _CitationSink:
    """The drain's citation lookups, mutated in place as rows are written.

    Attributes:
        ev_id_by_title: Evidence id per source title; a citation may add its
            own source on the fly.
        abstract_by_title: Abstract per retrieved source title, used to
            classify a citation against the paper it cites.
        citation_summary: Running per-state citation counts.
    """

    ev_id_by_title: dict[str, str]
    abstract_by_title: dict[str, str]
    citation_summary: dict[str, int]


@dataclass(frozen=True)
class _CitationTarget:
    """The hypothesis row a citation attaches to, inside one transaction.

    Attributes:
        run_id: Run the citation belongs to.
        hyp_id: Persisted hypothesis row the citation attaches to.
        grounding: Claim text the citation is matched against.
        conn: Open connection of the caller's transaction.
    """

    run_id: str
    hyp_id: str
    grounding: str
    conn: sqlite3.Connection


def _ensure_citation_evidence_id(
    run_id: str,
    cite_title: str,
    cite_info: dict[str, Any],
    ev_id_by_title: dict[str, str],
    conn: sqlite3.Connection,
) -> str:
    """Return the evidence id for a cited source, adding it on the fly.

    Mutates `ev_id_by_title` in place when a new evidence row is added.

    Args:
        run_id: Run the cited source belongs to.
        cite_title: Title the source is keyed by.
        cite_info: The engine's raw citation entry.
        ev_id_by_title: Evidence id per source title, updated in place.
        conn: Open connection of the caller's transaction.

    Returns:
        The evidence id for the cited source.
    """
    cite_ev_id = ev_id_by_title.get(cite_title)
    if cite_ev_id is None:
        cite_ev_id = store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=cite_title,
                source=cite_info.get("type", "engine"),
                url=_citation_url(cite_info),
                authors=cite_info.get("authors") or [],
                year=cite_info.get("year"),
                abstract="",
                available=True,
            ),
            conn=conn,
        )
        ev_id_by_title[cite_title] = cite_ev_id
    return cite_ev_id


def _hypothesis_grounding_text(h: dict[str, Any]) -> str:
    """Return the literature-grounding text used as a citation's claim basis.

    Falls back to the hypothesis's own statement text, then to empty, when no
    dedicated grounding text was generated.
    """
    return str(h.get("literature_grounding") or h.get("text") or "")


def _claim_cited_by(grounding: str, cite_key: str) -> str:
    """The part of a grounding paragraph that actually cites ``cite_key``.

    A grounding is a synthesis spanning every source the hypothesis rests on,
    and each source backs one or two of its sentences. ``_token_overlap``
    measures coverage over the *claim's* vocabulary, so handing a single
    paper's abstract the whole paragraph divides its real overlap by every
    other source's words as well -- which puts the upper states out of reach
    however well the paper supports what it was cited for. On one live run
    the best of 27 citations scored 0.23 against a 0.30 "partial" line, and
    the audit reported 0 verified, 0 partial, 33 unsupported: the same
    unreachable-upper-states failure the coverage metric was introduced to
    fix, arriving through the claim side instead of the metric.

    Args:
        grounding: The hypothesis's whole literature-grounding text.
        cite_key: The engine's key for one citation (e.g. ``C1``).

    Returns:
        The grounding sentences carrying a ``[C1]``-style marker for this
        key, or the whole grounding when the key is not marked inline (a
        knowledge-graph source, or a payload that never inlined markers).
    """
    marker = f"[{cite_key}]"
    cited = [
        sentence
        for sentence in SENTENCE_SPLIT.split(grounding)
        # A sentence may list several keys ("[C1, C3]"), so match the key
        # inside a bracket group rather than only a lone marker.
        if marker in sentence
        or any(
            cite_key == part.strip()
            for group in _BRACKET_GROUP.findall(sentence)
            for part in group.split(",")
        )
    ]
    return " ".join(cited).strip() or grounding


def _citation_map(h: dict[str, Any]) -> dict[str, Any]:
    """Return a hypothesis's raw engine citation map, defaulting to empty."""
    return h.get("citation_map") or {}


def _citation_url(cite_info: dict[str, Any]) -> str:
    """Return a citation's URL, defaulting to empty (an unavailable source)."""
    return cite_info.get("url") or ""


def _citation_available(cite_info: dict[str, Any], cite_url: str) -> bool:
    """Return whether a cited source counts as available (not retracted)."""
    return (
        bool(cite_url)
        and not bool(cite_info.get("is_retracted"))
        and str(cite_info.get("correction_status") or "").lower() != "retracted"
    )


def _persist_one_citation(
    target: _CitationTarget,
    cite_key: str,
    cite_info: dict[str, Any],
    sink: _CitationSink,
) -> None:
    """Persist one hypothesis citation row, classifying and tallying it.

    Routes the citation through the shared classifier rather than hardcoding
    a state, so the four-state citation UI reflects real runs. The target's
    grounding is the claim the citation supports; it is matched against the
    cited paper's abstract (when the source was retrieved), and a source
    with no resolvable URL (e.g. a knowledge-graph statement) falls out as
    "unavailable".

    Mutates the sink's `ev_id_by_title` (a citation may add evidence for its
    source on the fly) and `citation_summary` (running citation-state
    counts) in place.

    Args:
        target: The hypothesis row, its claim text, and the transaction.
        cite_key: The engine's key for this citation.
        cite_info: The engine's raw citation entry.
        sink: The drain's citation lookups, updated in place.
    """
    # "title" is a paper's own field; a non-paper source (knowledge-graph
    # statement, CVE entry, ...) carries no title at all, only "display"
    # (see citations._enrichment_reference_entries) -- falling straight to
    # cite_key would persist an evidence row literally titled "C3".
    cite_title = cite_info.get("title") or cite_info.get("display") or cite_key
    cite_url = _citation_url(cite_info)
    cite_ev_id = _ensure_citation_evidence_id(
        target.run_id,
        cite_title,
        cite_info,
        sink.ev_id_by_title,
        target.conn,
    )
    claim = f"[{cite_key}] cited in hypothesis"
    state = classify_citation(
        CitationRecord(
            url=cite_url,
            abstract=sink.abstract_by_title.get(cite_title, ""),
            claim=_claim_cited_by(target.grounding, cite_key),
            available=_citation_available(cite_info, cite_url),
        )
    )
    sink.citation_summary[state] += 1
    store.add_citation(
        store.NewCitation(
            run_id=target.run_id,
            hypothesis_id=target.hyp_id,
            evidence_id=cite_ev_id,
            claim=claim,
            state=state,
        ),
        conn=target.conn,
    )


def _persist_engine_citations(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    sink: _CitationSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's citations, classifying each via the shared path.

    Mutates the sink's `ev_id_by_title` (a citation may add evidence for its
    source on the fly) and `citation_summary` (running citation-state
    counts) in place; see `_persist_one_citation` for the per-citation
    classification rules.

    Args:
        run_id: Run the hypothesis belongs to.
        hyp_id: Persisted hypothesis row the citations attach to.
        h: The engine's raw hypothesis payload.
        sink: The drain's citation lookups, updated in place.
        conn: Open connection of the caller's transaction.
    """
    target = _CitationTarget(
        run_id, hyp_id, _hypothesis_grounding_text(h), conn
    )
    for cite_key, cite_info in _citation_map(h).items():
        _persist_one_citation(target, cite_key, cite_info, sink)


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
# verdict to mirror here.
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


def _score_or_none(value: Any) -> float | None:
    """Coerce a raw engine score to a float, treating 0/falsy as unset."""
    return float(value or 0) or None


# Reviewer label for a scientist-authored review, matching the row
# `runs.contrib.add_human_review` writes. Kept apart from the engine's
# "review" agent so a human review never reaches a reader as an anonymous
# agent one.
_SCIENTIST_REVIEWER = "scientist"


def _scientist_review_row_survives(
    source_id: str, conn: sqlite3.Connection
) -> bool:
    """Return whether the review's own stored row is still there.

    An unparseable id cannot name a row, so it reads as gone and the review
    is restored -- losing a human review is the worse of the two failures.
    """
    if not source_id.isdigit():
        return False
    return store.review_exists(int(source_id), conn=conn)


def _persist_scientist_review(
    run_id: str, hyp_id: str, rv: dict[str, Any], conn: sqlite3.Connection
) -> bool:
    """Restore a merged scientist review, or report that it needs no row.

    A scientist review reaches the drain because the merge carried it into
    engine state (``engine_tasks.inputs._scientist_hypothesis_review``),
    which is also where its author and verdict ride. Its own row usually
    survived the run's resets untouched -- scientist rows are deliberately
    retained -- so the drain must not write a second, differently-attributed
    copy of it. The one case that does need a row back is a review of an
    *agent* hypothesis: deleting that hypothesis for the replay cascades the
    human review away with it, and only engine state still holds it.

    Returns:
        Whether this review was handled here, so the generic per-review
        insert must skip it.
    """
    feedback = rv.get("detailed_feedback") or {}
    source_id = str(feedback.get("scientist_review_id") or "")
    if not source_id:
        return False
    if _scientist_review_row_survives(source_id, conn):
        return True
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hyp_id,
            reviewer_agent=_SCIENTIST_REVIEWER,
            summary=rv.get("review_summary", ""),
            critique=str(feedback.get("scientist_critique") or ""),
            overall=_score_or_none(rv.get("overall_score", 0)),
            author=str(feedback.get("scientist_author") or ""),
            verdict=str(feedback.get("scientist_verdict") or "") or None,
        ),
        conn=conn,
    )
    return True


def _novelty_review_lines(rv: dict[str, Any]) -> list[str]:
    """Render the published novelty review's two named lists (MO-3).

    Google's exemplar (docs/CORPUS-EXTRACTION.md,
    reviews/als-reflection-reviews.md -- 106 lines, sha256 2f486c549886,
    Figure A.11) prints a novelty review as "Aspects already explored:" and
    "Novel Aspects:", each a bulleted list. Empty when the review named
    nothing in either list.
    """
    already = [str(x).strip() for x in rv.get("already_explored") or []]
    already = [x for x in already if x]
    novel = [str(x).strip() for x in rv.get("novel_aspects") or []]
    novel = [x for x in novel if x]
    lines: list[str] = []
    if already:
        lines += ["Aspects already explored:"]
        lines += [f"- {item}" for item in already]
    if novel:
        if lines:
            lines.append("")
        lines += ["Novel Aspects:"]
        lines += [f"- {item}" for item in novel]
    return lines


def _persist_engine_review_rows(
    run_id: str, hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's per-review rows from the engine's reviews list."""
    for rv in h.get("reviews") or []:
        if _persist_scientist_review(run_id, hyp_id, rv, conn):
            continue
        scores = rv.get("scores", {})
        critique_lines = [str(rv.get("constructive_feedback") or "")]
        novelty_lines = _novelty_review_lines(rv)
        if novelty_lines:
            critique_lines += ["", *novelty_lines]
        store.add_review(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hyp_id,
                reviewer_agent="review",
                summary=rv.get("review_summary", ""),
                critique="\n".join(critique_lines).strip(),
                novelty=_score_or_none(scores.get("novelty", 0)),
                plausibility=_score_or_none(
                    scores.get("scientific_soundness", 0)
                ),
                testability=_score_or_none(scores.get("testability", 0)),
                overall=_score_or_none(rv.get("overall_score", 0)),
                detail_json=_detail_json(_initial_review_detail(rv)),
            ),
            conn=conn,
        )


def _persist_deep_verification_review(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist deep-verification probes as a dedicated review row, if any."""
    probes = h.get("deep_verification_probes") or []
    if not probes:
        return
    summary, critique = format_deep_verification_critique(
        probes, h.get("deep_verification_verdict")
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hyp_id,
            reviewer_agent="deep_verification",
            summary=summary,
            critique=critique,
            detail_json=_detail_json(
                _deep_verification_detail(
                    probes, h.get("deep_verification_verdict")
                )
            ),
        ),
        conn=conn,
    )


# Enrichment key -> persisted reviewer_agent for the mature Reflection
# cascade's reviews (audit E1). Distinct agents keep the results apart in
# the UI instead of collapsing them under a single "Full review" row.
_MATURE_REVIEW_AGENTS: tuple[tuple[str, str, str], ...] = (
    ("full", "full_review", "Full review verdict"),
    ("simulation", "simulation_review", "Simulation review verdict"),
    ("recurrent", "recurrent_review", "Recurrent review verdict"),
)


def _format_mature_critique(key: str, review: dict[str, Any]) -> str:
    """Render one mature review result as the persisted critique text.

    Reads only the schema's content fields, so the retrieval bookkeeping
    the engine stores alongside each result never reaches the row.
    """
    lines: list[str] = []
    if key == "simulation":
        _append_simulation_critique(lines, review)
    else:
        _append_full_critique(lines, review)
    return "\n".join(lines).strip()


def _labeled_lines(pairs: tuple[tuple[str, Any], ...]) -> list[str]:
    """Render the non-empty members of (label, value) pairs as lines."""
    lines = []
    for label, value in pairs:
        text = str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return lines


def _assumption_line(item: dict[str, Any]) -> str | None:
    """Render one full-review assumption entry, or None when empty.

    ``reasoning`` (MO-9) is the published free-text paragraph explaining the
    support verdict; appended when present so a hypothesis reviewed through
    full review alone still carries it, the way deep verification's
    ``sub_assumptions[].verification`` always has.

    This line is baked into the review's persisted ``critique`` text at
    drain time (``_format_mature_critique``, below), not recomputed on
    read -- so a run drained before this label mapping existed keeps
    reading "Assumption (supported): ..." forever; only a newly drained
    run picks up the published wording. Deep verification's own
    ``sub_assumptions[].status`` is a separate field this function never
    sees -- it is not rendered to a reader anywhere in this codebase (only
    its sibling ``probes``/``verdict`` are, via
    ``format_deep_verification_critique``), so this change does not touch
    it.
    """
    assumption = str(item.get("assumption") or "").strip()
    if not assumption:
        return None
    support = str(item.get("support") or "").strip()
    label = _ASSUMPTION_SUPPORT_LABELS.get(support, support or "unrated")
    line = f"Assumption ({label}): {assumption}"
    reasoning = str(item.get("reasoning") or "").strip()
    if reasoning:
        line += f" — {reasoning}"
    return line


def _append_full_critique(lines: list[str], review: dict[str, Any]) -> None:
    """Render the full/recurrent review's content fields."""
    lines += _labeled_lines(
        (
            ("Correctness", review.get("correctness")),
            ("Quality and novelty", review.get("quality_and_novelty")),
            ("Literature grounding", review.get("literature_grounding")),
            ("Justification", review.get("justification")),
        )
    )
    for item in review.get("assumptions") or []:
        if isinstance(item, dict) and (line := _assumption_line(item)):
            lines.append(line)


def _simulation_step_line(index: int, item: dict[str, Any]) -> str | None:
    """Render one simulation step entry, or None when empty."""
    step = str(item.get("step") or "").strip()
    if not step:
        return None
    plausible = "plausible" if item.get("plausible") else "implausible"
    return f"Step {index} ({plausible}): {step}"


def _simulation_step_lines(review: dict[str, Any]) -> list[str]:
    """Render the simulation review's numbered steps."""
    lines = []
    for index, item in enumerate(review.get("steps") or [], start=1):
        if isinstance(item, dict) and (
            line := _simulation_step_line(index, item)
        ):
            lines.append(line)
    return lines


def _failure_point_lines(review: dict[str, Any]) -> list[str]:
    """Render the simulation review's failure points."""
    lines = []
    for point in review.get("failure_points") or []:
        text = str(point).strip()
        if text:
            lines.append(f"Failure point: {text}")
    return lines


def _append_simulation_critique(
    lines: list[str], review: dict[str, Any]
) -> None:
    """Render the simulation review's content fields."""
    model = str(review.get("model") or "").strip()
    if model:
        lines.append(f"Simulated model: {model}")
    lines += _simulation_step_lines(review)
    lines += _failure_point_lines(review)
    lines += _labeled_lines(
        (
            ("Robustness", review.get("robustness")),
            ("Decisive step", review.get("decisive_step")),
        )
    )


def _persist_mature_review_rows(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist the mature cascade's reviews as distinctly-labeled rows.

    The full, simulation, and recurrent reviews used to stop at the
    engine's enrichments (audit E1): the report reader never saw them.
    Each result present at drain time becomes its own review row under a
    distinct reviewer_agent, with the verdict as the row's summary.
    """
    enrichments = h.get("enrichments") or {}
    for key, reviewer_agent, verdict_label in _MATURE_REVIEW_AGENTS:
        review = enrichments.get(key)
        if not isinstance(review, dict):
            continue
        verdict = str(review.get("verdict") or "unspecified")
        store.add_review(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hyp_id,
                reviewer_agent=reviewer_agent,
                summary=f"{verdict_label}: {verdict}",
                critique=_format_mature_critique(key, review),
                detail_json=_review_detail_json(key, review),
            ),
            conn=conn,
        )


def _persist_engine_reviews(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist every review row one drained hypothesis carries."""
    _persist_engine_review_rows(run_id, hyp_id, h, conn)
    _persist_deep_verification_review(run_id, hyp_id, h, conn)
    _persist_mature_review_rows(run_id, hyp_id, h, conn)


__all__ = [
    "_ASSUMPTION_SUPPORT_LABELS",
    "_CitationSink",
    "_detail_json",
    "_persist_engine_citations",
]
