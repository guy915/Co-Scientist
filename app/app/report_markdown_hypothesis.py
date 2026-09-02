"""Report section rendering one numbered 'Top hypotheses' entry.

Moved out of ``report_markdown`` to keep this module's own complexity and
that module's line count under their caps: as more optional subsections
(scene-setting MO-6, safety-and-toxicity MO-10) were added to one entry,
its renderer's branch count grew past the mccabe ceiling. Each optional
subsection now factors into its own low-complexity helper here, and the
entry point is a straight-line assembly of them -- names are re-exported
from ``report_markdown`` so that module's namespace keeps resolving.
"""

from __future__ import annotations

import json
from typing import Any

from app.report_markdown_header import _ABOUT_DISCLOSURE, _SYSTEM_NAME
from app.report_markdown_references import _render_references_markdown
from app.text_utils import hypothesis_statement, hypothesis_title

# R14-13: byte-identical across all 19 published hypothesis files
# (docs/CORPUS-EXTRACTION.md R14-13) -- a fixed disclaimer, not derived
# from the hypothesis, so it carries no field guard and always renders.
# Shared with the report-level About disclosure (R14-4,
# ``report_markdown_header._ABOUT_DISCLOSURE``) -- Google's two published
# instances of this wording are byte-identical, so this re-exports the one
# constant rather than maintaining a second copy of the string.
_HYPOTHESIS_DISCLAIMER = _ABOUT_DISCLOSURE


def _claim_status(edge: dict[str, Any]) -> str:
    """Return the reader-facing scientific status for one claim edge."""
    label = str(edge.get("label") or "insufficient")
    role = str(edge.get("claim_role") or "categorical")
    if label == "supports":
        return "Supported"
    if label == "partial":
        return "Partially supported"
    if label == "contradicts":
        return "Contradicted"
    if role == "speculative":
        return "Speculative — evidence insufficient"
    return "Unsupported categorical claim"


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


def _render_claim_evidence(edges: list[dict[str, Any]]) -> list[str]:
    """Render every persisted claim verdict for one released hypothesis."""
    if not edges:
        return []
    lines = ["**Claim evidence:**", ""]
    for edge in edges:
        role = str(edge.get("claim_role") or "categorical")
        claim = str(edge.get("claim") or "")
        lines.append(f"- **{_claim_status(edge)} · {role}** — {claim}")
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
    Google's H1 -- this entry is a subsection of the Top Ranking
    Hypotheses document's own ``## Top hypotheses`` section (R14-11), not
    a standalone per-hypothesis document, and promoting it to H1 would
    break the document's own heading hierarchy without making it any more
    like Google's actual per-file shape (see R14-26, still a DECISION, on
    whether a per-hypothesis document ever exists here at all).
    """
    title = hypothesis_title(hyp)
    lines = [
        f"### {i}. **{_SYSTEM_NAME} - {title}**"
        f"  _Elo: {hyp.get('elo_rating', '')}_",
        _HYPOTHESIS_DISCLAIMER,
        "",
    ]
    lines += _render_hypothesis_scene_setting(hyp)
    if statement := hypothesis_statement(hyp):
        lines += [f"**Proposed hypothesis:** {statement}", ""]
    lines += _render_hypothesis_mechanism(hyp)
    lines += _render_hypothesis_experiment(hyp)  # R14-20, right after Mechanism
    # Resolves the [C*] keys the mechanism text just cited -- the engine's
    # per-hypothesis reference index, joined back from citations+evidence
    # (see report_markdown_references). Right after Mechanism/Predicted
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
    # R14-15/R14-22: the reviewer's own findings for this hypothesis --
    # display-only Go/No-Go framing, then the simulation review's
    # numbered failure points -- sit after the proposer's own content and
    # before this system's claim-evidence extension.
    lines += _render_hypothesis_verdict(reviews)
    lines += _render_hypothesis_simulation_review(reviews)
    lines += _render_claim_evidence(edges)
    return lines


def _render_top_ranking_hypotheses_list(
    top_hypotheses: list[dict[str, Any]],
) -> list[str]:
    """Render the Research Overview document's compact hypothesis list.

    R14-11/R14-1: the Research Overview document's own "Top ranking
    hypotheses" section is a titles-only list referencing hypothesis IDs
    (R11-4), distinct from the full per-idea write-up ("## Top
    hypotheses") that renders on the Top Ranking Hypotheses document
    instead (``_render_top_hypotheses_markdown`` in ``report_markdown.py``).
    Same ranked order, same data -- just titles, so a reader on this
    document knows what was compared without duplicating the full cards.
    """
    titles = [hypothesis_title(hyp) for hyp in top_hypotheses if hyp.get("id")]
    if not titles:
        return []
    lines = ["\n## Top ranking hypotheses\n"]
    lines += [f"{i}. {title}" for i, title in enumerate(titles, 1)]
    lines.append("")
    return lines
