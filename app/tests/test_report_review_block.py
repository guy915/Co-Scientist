"""The report renders the reviews and probes a run already paid for.

Every review in the cascade ran, was persisted, and reached the report
payload -- and the report printed none of it. Published per-hypothesis
documents carry roughly 3,800 words of review per idea across an
``Appendix:``/``All reviews:`` block and a ``Reviews summary``, plus a
deep-verification section; ours carried zero words of all three.

These pin the published section vocabulary and the omit-when-empty
convention (R14-23) for the three blocks:

* ``#### Reviews summary`` -- the eight numbered published parts;
* ``#### Appendix:`` / ``All reviews:`` -- per-axis feedback, the
  novelty review's two named lists, Detailed Assumptions, and each
  axis's own closing ``Answer: N`` line;
* ``#### Deep verification`` -- the ``Question:``/``Answer:``/
  ``Reasoning:`` probe triple and the verdict.
"""

from __future__ import annotations

from typing import Any

from app.report_markdown_review_block import (
    _render_deep_verification,
    _render_hypothesis_reviews,
    _render_reviews_summary,
)
from tests._review_block_helpers import _row, _summary_row


def _initial_row() -> dict[str, Any]:
    return _row(
        "review",
        {
            "scores": {
                "scientific_soundness": 8,
                "plausibility": 7,
                "novelty": 6,
                "testability": 9,
                "potential_impact": 5,
                "relevance": 4,
                "safety": 10,
                "clarity": 3,
            },
            "detailed_feedback": {
                "scientific_soundness": "The mechanism is consistent.",
                "novelty": "The pairing is unusual.",
                "testability": "A pilot assay would settle it.",
                "potential_impact": "Would change first-line practice.",
                "relevance": "Squarely on the research goal.",
                "clarity": "Precisely stated.",
            },
            "already_explored": ["Target engagement is documented."],
            "novel_aspects": ["The stress-induced modification is new."],
            "constructive_feedback": "Name the control arm.",
        },
    )


def _full_row() -> dict[str, Any]:
    return _row(
        "full_review",
        {
            "correctness": "The logic holds throughout.",
            "quality_and_novelty": "A genuine contribution.",
            "literature_grounding": "Two cohort studies agree.",
            "justification": "Worth a pilot.",
            "comparison_with_knowledge_base": "Agrees with the canon.",
            "goal_requirements_assessment": "Meets every requirement.",
            "feasibility_steps": ["Run the pilot.", "Read out at day 30."],
            "feasibility_reasoning": "Both steps use standard assays.",
            "impact_assessment": "Would change first-line practice.",
            "assumptions": [
                {
                    "assumption": "The receptor is expressed.",
                    "reasoning": "Two cohorts detect it directly.",
                    "support": "Plausible",
                }
            ],
        },
    )


def _references() -> list[tuple[str, dict[str, Any]]]:
    """One hypothesis's resolvable citation index, as the entry builds it."""
    return [
        (
            "C1",
            {
                "title": "Hexameric resistosome assembly",
                "authors": ["Madhuprakash"],
                "year": 2024,
                "abstract": "Direct evidence for a hexameric helper NLR.",
            },
        )
    ]


# ---------------------------------------------------------------------------
# Per-axis sub-structure (R14-17)
# ---------------------------------------------------------------------------


def test_each_published_axis_carries_its_own_sub_structure() -> None:
    """R14-17: four axes, four different fixed shapes, not one template.

    Correctness is the richest (Comparison with Knowledge Base and Goal
    Requirement Assessment were the two published parts nothing here had
    a field for); Feasibility is the leanest at three; Impact potential
    closes on its own assessment.
    """
    text = "\n".join(_render_hypothesis_reviews([_initial_row(), _full_row()]))

    assert "**Comparison with Knowledge Base**" in text
    assert "**Goal Requirement Assessment**" in text
    assert "**Steps to Test the Idea**" in text
    assert "1. Run the pilot." in text
    assert "**Reasoning about Feasibility**" in text
    assert "**Overall Impact Potential**" in text


def test_correctness_sub_parts_render_in_the_published_order() -> None:
    """The published Correctness axis's own eight-part order."""
    text = "\n".join(
        _render_hypothesis_reviews([_initial_row(), _full_row()], _references())
    )

    order = [
        text.index("**Related Article Abstracts**"),
        text.index("**Detailed Assumptions**"),
        text.index("**Comparison with Knowledge Base**"),
        text.index("**Reasoning about Correctness**"),
        text.index("**Strength of Evidence**"),
        text.index("**Suggested Improvements**"),
        text.index("**Goal Requirement Assessment**"),
        text.index("**Final Reasoning and Recommendation**"),
    ]
    assert order == sorted(order)


def test_related_article_abstracts_come_from_the_citations_not_the_model() -> (
    None
):
    """The one published sub-part a schema must never ask a model for.

    It is a literal echo of the articles the review prompt supplied, and
    an echoing schema scales its response with its input and truncates
    identically on every retry. The renderer joins it back from the same
    citation index the entry's References section prints from, so it
    costs nothing and cannot be hallucinated.
    """
    text = "\n".join(
        _render_hypothesis_reviews([_initial_row(), _full_row()], _references())
    )

    assert "- **[C1]** Madhuprakash et al., 2024 — Hexameric" in text
    assert "Direct evidence for a hexameric helper NLR." in text


def test_only_correctness_prints_the_abstracts_in_full() -> None:
    """The leaner axes print titles, as 5 of the 19 published files do.

    The same abstract repeated under all four axes would quadruple the
    longest block in the entry and tell a reader nothing new.
    """
    text = "\n".join(
        _render_hypothesis_reviews([_initial_row(), _full_row()], _references())
    )

    assert text.count("**Related Article Abstracts**") == 1
    assert text.count("**Related Article Abstract Titles**") == 3
    assert text.count("Direct evidence for a hexameric helper NLR.") == 1


def test_an_old_shaped_review_renders_exactly_what_it_always_did() -> None:
    """A resumed run's review predates every field added here.

    None of the new sub-parts has a value, so none prints a heading --
    the omit-rather-than-empty convention (R14-23) applied to a shape
    change rather than to an unanswered field.
    """
    old_row = _row(
        "full_review",
        {
            "correctness": "The logic holds throughout.",
            "quality_and_novelty": "A genuine contribution.",
            "literature_grounding": "Two cohort studies agree.",
            "justification": "Worth a pilot.",
        },
    )
    text = "\n".join(_render_hypothesis_reviews([_initial_row(), old_row]))

    for heading in (
        "Related Article",
        "Comparison with Knowledge Base",
        "Goal Requirement Assessment",
        "Steps to Test the Idea",
        "Reasoning about Feasibility",
        "Overall Impact Potential",
    ):
        assert heading not in text
    assert "**Reasoning about Correctness**" in text


# ---------------------------------------------------------------------------
# All reviews (F1)
# ---------------------------------------------------------------------------


def test_all_reviews_uses_the_published_axis_headings() -> None:
    """Google's four named axes lead, in the published order."""
    text = "\n".join(_render_hypothesis_reviews([_initial_row()]))

    assert "#### Appendix:" in text
    assert "**All reviews:**" in text
    heads = [
        text.index("##### Correctness"),
        text.index("##### Novelty"),
        text.index("##### Feasibility"),
        text.index("##### Impact potential"),
    ]
    assert heads == sorted(heads)


def test_all_reviews_closes_each_axis_with_its_own_answer_line() -> None:
    """The published per-axis review ends on a bolded ``Answer: N``.

    The score reaches the renderer only through ``detail_json``: three of
    the eight have columns, and the ``plausibility`` column holds
    ``scientific_soundness``, so reading the columns would print one
    axis's score under another axis's name.
    """
    lines = _render_hypothesis_reviews([_initial_row()])

    assert "**Answer: 8**" in lines
    assert "**Answer: 3**" in lines
    assert (
        lines.index("The pairing is unusual.")
        < lines.index("**Answer: 6**")
        < lines.index("##### Feasibility")
    )


def test_all_reviews_renders_the_novelty_two_named_lists() -> None:
    """MO-3: the published novelty review is exactly these two lists."""
    lines = _render_hypothesis_reviews([_initial_row()])

    already = lines.index("Aspects already explored:")
    novel = lines.index("Novel Aspects:")
    assert lines[already + 1] == "- Target engagement is documented."
    assert lines[novel + 1] == "- The stress-induced modification is new."
    assert already < novel < lines.index("**Answer: 6**")


def test_all_reviews_renders_detailed_assumptions_under_correctness() -> None:
    """MO-9: each assumption's support verdict and its reasoning paragraph."""
    lines = _render_hypothesis_reviews([_initial_row(), _full_row()])

    assert "**Detailed Assumptions**" in lines
    assert (
        "- **Plausible:** The receptor is expressed. — "
        "Two cohorts detect it directly." in lines
    )
    correctness = lines.index("##### Correctness")
    assert correctness < lines.index("**Detailed Assumptions**")
    assert lines.index("**Detailed Assumptions**") < lines.index(
        "##### Novelty"
    )


def test_all_reviews_renders_the_full_reviews_own_prose() -> None:
    """The full review's four prose fields, under their published axes."""
    lines = _render_hypothesis_reviews([_initial_row(), _full_row()])

    assert "The logic holds throughout." in lines
    assert "A genuine contribution." in lines
    assert "Two cohort studies agree." in lines


def test_all_reviews_renders_the_constructive_feedback() -> None:
    """The initial review's actionable suggestions, published as their own."""
    lines = _render_hypothesis_reviews([_initial_row()])

    assert "**Suggested Improvements**" in lines
    assert "Name the control arm." in lines


def test_all_reviews_prefers_the_latest_row_of_each_agent() -> None:
    """A re-reviewed hypothesis carries several rows, oldest first.

    ``store.list_reviews`` orders by creation time, so the last matching
    row is the current assessment; taking the first would pin a report to
    a superseded review for the rest of the run.
    """
    stale = _row("review", {"scores": {"novelty": 1}})
    fresh = _row("review", {"scores": {"novelty": 9}})

    lines = _render_hypothesis_reviews([stale, fresh])

    assert "**Answer: 9**" in lines
    assert "**Answer: 1**" not in lines


def test_all_reviews_renders_nothing_without_reviews() -> None:
    """R14-23: omit the heading too, never an empty section."""
    assert _render_hypothesis_reviews([]) == []


def test_all_reviews_renders_nothing_for_rows_with_no_detail() -> None:
    """A run drained before this column carries prose only."""
    rows = [{"hypothesis_id": "h1", "reviewer_agent": "review"}]

    assert _render_hypothesis_reviews(rows) == []


# ---------------------------------------------------------------------------
# Reviews summary (F6)
# ---------------------------------------------------------------------------


def test_reviews_summary_renders_the_published_eight_parts_in_order() -> None:
    """R14-14: the numbered headings every published file prints."""
    lines = _render_reviews_summary([_summary_row()])

    assert lines[0] == "#### Reviews summary"
    headings = [line for line in lines if line.startswith("##### ")]
    assert headings == [
        "##### 1. Executive Verdict",
        "##### 2. Critical Flaws",
        "##### 3. Addressed Objections",
        "##### 4. Validated Risks & Limitations",
        "##### 5. Supporting Arguments & Evidence (Motivation)",
        "##### 6. Alignment & Novelty",
        "##### 7. Feasibility Assessment (Go/No-Go Decision)",
        "##### 8. Conclusion",
    ]


def test_reviews_summary_renders_prose_and_bullets_by_part() -> None:
    """Six parts are bulleted in the published exemplars; two are prose."""
    lines = _render_reviews_summary([_summary_row()])

    assert "The index is well conceived." in lines
    assert "- The pore benchmark is wrong." in lines
    assert "Recalibrate before testing." in lines


def test_reviews_summary_omits_the_parts_a_review_left_empty() -> None:
    """A part with nothing to say prints no heading of its own."""
    lines = _render_reviews_summary(
        [_row("full_review", {"reviews_summary": {"conclusion": "Test it."}})]
    )

    assert lines[0] == "#### Reviews summary"
    assert [line for line in lines if line.startswith("##### ")] == [
        "##### 8. Conclusion"
    ]


def test_reviews_summary_renders_nothing_when_absent() -> None:
    """The block is optional on the schema, so most rows carry none."""
    assert _render_reviews_summary([_full_row()]) == []
    assert _render_reviews_summary([]) == []


# ---------------------------------------------------------------------------
# Deep verification (F2)
# ---------------------------------------------------------------------------


def _probe_row() -> dict[str, Any]:
    return _row(
        "deep_verification",
        {
            "verdict": "weakened",
            "probes": [
                {
                    "question": "Is CXCR1/2 inhibition alone sufficient?",
                    "answer": "It targets a key node of the microenvironment.",
                    "reasoning": "Not incoherent, but it needs care.",
                    "fundamental": True,
                },
                {
                    "question": "Does the dose reach the marrow?",
                    "answer": "Exposure data are absent.",
                    "reasoning": "",
                    "fundamental": False,
                },
            ],
        },
    )


def test_deep_verification_renders_the_published_probe_triple() -> None:
    """R14-15's exact labels, each on its own line."""
    lines = _render_deep_verification([_probe_row()])

    assert lines[0] == "#### Deep verification"
    assert "**Verdict:** weakened" in lines
    assert "Question: Is CXCR1/2 inhibition alone sufficient?" in lines
    assert "Answer: It targets a key node of the microenvironment." in lines
    assert "Reasoning: Not incoherent, but it needs care." in lines


def test_deep_verification_numbers_probes_and_marks_fundamentals() -> None:
    """A probe of a fundamental assumption is a different fact from one not."""
    lines = _render_deep_verification([_probe_row()])

    assert "**Probe 1 (fundamental assumption)**" in lines
    assert "**Probe 2 (non-fundamental assumption)**" in lines


def test_deep_verification_omits_a_probes_empty_parts() -> None:
    """A probe that answered without reasoning prints no Reasoning label."""
    lines = _render_deep_verification([_probe_row()])

    assert not [line for line in lines if line == "Reasoning: "]


def test_deep_verification_renders_nothing_without_a_probe_row() -> None:
    """R14-23 again: no probes, no heading."""
    assert _render_deep_verification([_initial_row()]) == []
    assert _render_deep_verification([]) == []
