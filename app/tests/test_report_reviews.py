from __future__ import annotations

import asyncio
import json
from typing import Any

from app.engine_adapter.drain.reviews import (
    _append_full_critique,
    _assumption_line,
    _review_detail_json,
    _simulation_detail,
    _verdict_detail,
)
from app.report import markdown as report_markdown
from app.report.markdown.hypothesis import (
    _render_critiques_rollup,
    _render_deep_verification,
    _render_hypothesis_reviews,
    _render_reviews_summary,
)
from app.store import records, reports
from tests._drain_helpers import (
    _build_report,
    _final_state_with_features,
    _final_state_with_lineage,
    _persist,
    _persist_and_finalize,
)
from tests._store_helpers import seed_run


def _row(agent: str, detail: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "hypothesis_id": "h1",
        "reviewer_agent": agent,
        "detail_json": json.dumps(detail),
        **extra,
    }


def _summary_row() -> dict[str, Any]:
    return _row(
        "full_review",
        {
            "reviews_summary": {
                "executive_verdict": "The index is well conceived.",
                "critical_flaws": ["The pore benchmark is wrong."],
                "addressed_objections": ["Modelling reliability was met."],
                "validated_risks": ["Parameter covariance is untreated."],
                "supporting_arguments": ["The theoretical basis is right."],
                "alignment_and_novelty": ["Squarely on the goal."],
                "feasibility_assessment": ["Moderate resource intensity."],
                "conclusion": "Recalibrate before testing.",
            }
        },
    )


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


def test_each_published_axis_carries_its_own_sub_structure() -> None:
    text = "\n".join(_render_hypothesis_reviews([_initial_row(), _full_row()]))

    assert "**Comparison with Knowledge Base**" in text
    assert "**Goal Requirement Assessment**" in text
    assert "**Steps to Test the Idea**" in text
    assert "1. Run the pilot." in text
    assert "**Reasoning about Feasibility**" in text
    assert "**Overall Impact Potential**" in text


def test_correctness_sub_parts_render_in_the_published_order() -> None:
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
    # Echoing supplied abstracts in model schemas scales replies with input and
    # causes repeat truncation.
    text = "\n".join(
        _render_hypothesis_reviews([_initial_row(), _full_row()], _references())
    )

    assert "- **[C1]** Madhuprakash et al., 2024 — Hexameric" in text
    assert "Direct evidence for a hexameric helper NLR." in text


def test_only_correctness_prints_the_abstracts_in_full() -> None:
    # Repeating the same abstract under all axes quadruples the longest block
    # without new information.
    text = "\n".join(
        _render_hypothesis_reviews([_initial_row(), _full_row()], _references())
    )

    assert text.count("**Related Article Abstracts**") == 1
    assert text.count("**Related Article Abstract Titles**") == 3
    assert text.count("Direct evidence for a hexameric helper NLR.") == 1


def test_an_old_shaped_review_renders_exactly_what_it_always_did() -> None:
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


def test_all_reviews_uses_the_published_axis_headings() -> None:
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
    # Axis scores live in detail_json; legacy columns map scientific_soundness
    # to plausibility.
    lines = _render_hypothesis_reviews([_initial_row()])

    assert "**Answer: 8**" in lines
    assert "**Answer: 3**" in lines
    assert (
        lines.index("The pairing is unusual.")
        < lines.index("**Answer: 6**")
        < lines.index("##### Feasibility")
    )


def test_all_reviews_renders_the_novelty_two_named_lists() -> None:
    lines = _render_hypothesis_reviews([_initial_row()])

    already = lines.index("Aspects already explored:")
    novel = lines.index("Novel Aspects:")
    assert lines[already + 1] == "- Target engagement is documented."
    assert lines[novel + 1] == "- The stress-induced modification is new."
    assert already < novel < lines.index("**Answer: 6**")


def test_all_reviews_renders_detailed_assumptions_under_correctness() -> None:
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
    lines = _render_hypothesis_reviews([_initial_row(), _full_row()])

    assert "The logic holds throughout." in lines
    assert "A genuine contribution." in lines
    assert "Two cohort studies agree." in lines


def test_all_reviews_renders_the_constructive_feedback() -> None:
    lines = _render_hypothesis_reviews([_initial_row()])

    assert "**Suggested Improvements**" in lines
    assert "Name the control arm." in lines


def test_all_reviews_prefers_the_latest_row_of_each_agent() -> None:
    # Reviews arrive oldest first; choosing the first would publish a superseded
    # assessment.
    stale = _row("review", {"scores": {"novelty": 1}})
    fresh = _row("review", {"scores": {"novelty": 9}})

    lines = _render_hypothesis_reviews([stale, fresh])

    assert "**Answer: 9**" in lines
    assert "**Answer: 1**" not in lines


def test_all_reviews_renders_nothing_without_reviews() -> None:
    assert _render_hypothesis_reviews([]) == []


def test_all_reviews_renders_nothing_for_rows_with_no_detail() -> None:
    rows = [{"hypothesis_id": "h1", "reviewer_agent": "review"}]

    assert _render_hypothesis_reviews(rows) == []


def test_reviews_summary_renders_the_published_eight_parts_in_order() -> None:
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
    lines = _render_reviews_summary([_summary_row()])

    assert "The index is well conceived." in lines
    assert "- The pore benchmark is wrong." in lines
    assert "Recalibrate before testing." in lines


def test_reviews_summary_omits_the_parts_a_review_left_empty() -> None:
    lines = _render_reviews_summary(
        [_row("full_review", {"reviews_summary": {"conclusion": "Test it."}})]
    )

    assert lines[0] == "#### Reviews summary"
    assert [line for line in lines if line.startswith("##### ")] == [
        "##### 8. Conclusion"
    ]


def test_reviews_summary_renders_nothing_when_absent() -> None:
    assert _render_reviews_summary([_full_row()]) == []
    assert _render_reviews_summary([]) == []


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
    lines = _render_deep_verification([_probe_row()])

    assert lines[0] == "#### Deep verification"
    assert "**Verdict:** weakened" in lines
    assert "Question: Is CXCR1/2 inhibition alone sufficient?" in lines
    assert "Answer: It targets a key node of the microenvironment." in lines
    assert "Reasoning: Not incoherent, but it needs care." in lines


def test_deep_verification_numbers_probes_and_marks_fundamentals() -> None:
    lines = _render_deep_verification([_probe_row()])

    assert "**Probe 1 (fundamental assumption)**" in lines
    assert "**Probe 2 (non-fundamental assumption)**" in lines


def test_deep_verification_omits_a_probes_empty_parts() -> None:
    lines = _render_deep_verification([_probe_row()])

    assert not [line for line in lines if line == "Reasoning: "]


def test_deep_verification_renders_nothing_without_a_probe_row() -> None:
    assert _render_deep_verification([_initial_row()]) == []
    assert _render_deep_verification([]) == []


def test_critiques_rollup_renders_the_published_heading_and_label() -> None:
    lines = _render_critiques_rollup([_summary_row()])

    assert lines[0] == "#### Critiques"
    assert "Here's a summary of the negative critiques from the reviews:" in (
        lines
    )


def test_critiques_rollup_gathers_the_two_negative_summary_parts() -> None:
    lines = _render_critiques_rollup([_summary_row()])

    assert "- The pore benchmark is wrong." in lines
    assert "- Parameter covariance is untreated." in lines
    assert "- The theoretical basis is right." not in lines
    assert "- Squarely on the goal." not in lines


def test_critiques_rollup_handles_a_string_valued_part() -> None:
    lines = _render_critiques_rollup(
        [
            _row(
                "full_review",
                {"reviews_summary": {"critical_flaws": "Single prose flaw."}},
            )
        ]
    )

    assert "- Single prose flaw." in lines


def test_critiques_rollup_prefers_the_latest_full_review() -> None:
    stale = _row(
        "full_review",
        {"reviews_summary": {"critical_flaws": ["Stale flaw."]}},
    )
    fresh = _row(
        "recurrent_review",
        {"reviews_summary": {"critical_flaws": ["Fresh flaw."]}},
    )
    lines = _render_critiques_rollup([stale, fresh])

    assert "- Fresh flaw." in lines
    assert "- Stale flaw." not in lines


def test_critiques_rollup_renders_nothing_when_absent() -> None:
    assert _render_critiques_rollup([]) == []
    assert (
        _render_critiques_rollup(
            [_row("full_review", {"reviews_summary": {"conclusion": "Ship."}})]
        )
        == []
    )
    assert _render_critiques_rollup([_row("review", {})]) == []


def _summary_markdown(critical_criteria: list[Any] | None) -> str:
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            critical_criteria=critical_criteria,
        )
    )


def test_renders_from_the_structured_shape() -> None:
    markdown = _summary_markdown(
        [
            {
                "name": "Kinetic Feasibility and Experimental Readouts",
                "questions": [
                    {
                        "name": "Biological Timeframe Consistency",
                        "question": (
                            "Does the design account for the mechanism's"
                            " kinetics?"
                        ),
                    },
                    {
                        "name": "Kinetic Competition",
                        "question": "Does degradation outpace synthesis?",
                    },
                ],
            },
            {
                "name": "Human Data Integration and Accuracy",
                "questions": [
                    {
                        "name": "Dataset Grounding",
                        "question": "Is the hypothesis grounded in human data?",
                    }
                ],
            },
        ]
    )

    assert "## Review Summary" in markdown
    assert "### 1. Kinetic Feasibility and Experimental Readouts" in markdown
    assert (
        "- **Biological Timeframe Consistency:** Does the design account"
        " for the mechanism's kinetics?" in markdown
    )
    assert "- **Kinetic Competition:** Does degradation outpace synthesis?" in (
        markdown
    )
    assert "### 2. Human Data Integration and Accuracy" in markdown
    assert (
        "- **Dataset Grounding:** Is the hypothesis grounded in human data?"
        in markdown
    )


def test_renders_from_the_legacy_string_list() -> None:
    markdown = _summary_markdown(
        [
            "Kinetic Feasibility and Experimental Readouts",
            "Human Data Integration and Accuracy",
        ]
    )

    assert "## Review Summary" in markdown
    assert "### 1. Kinetic Feasibility and Experimental Readouts" in markdown
    assert "### 2. Human Data Integration and Accuracy" in markdown


def test_absent_criteria_renders_no_section() -> None:
    assert "Review Summary" not in _summary_markdown(None)
    assert "Review Summary" not in _summary_markdown([])


def test_malformed_criteria_render_no_section() -> None:
    assert "Review Summary" not in _summary_markdown("not a list")  # type: ignore[arg-type]
    assert "Review Summary" not in _summary_markdown(
        [42, None, {"questions": []}]
    )
    assert "Review Summary" not in _summary_markdown([{"name": "   "}])


def test_malformed_entries_are_skipped_alongside_valid_ones() -> None:
    markdown = _summary_markdown(
        [
            {"name": "Valid Criterion", "questions": [{"question": "Q1?"}]},
            {"name": ""},
            42,
            None,
        ]
    )

    assert "## Review Summary" in markdown
    assert "### 1. Valid Criterion" in markdown
    assert "- Q1?" in markdown


def test_malformed_question_entries_are_skipped() -> None:
    markdown = _summary_markdown(
        [
            {
                "name": "Valid Criterion",
                "questions": [
                    {"name": "Named", "question": "Named text?"},
                    {"question": ""},
                    "not a question object",
                    42,
                ],
            }
        ]
    )

    assert "- **Named:** Named text?" in markdown
    assert "not a question object" not in markdown


def _final_state_with_mature_enrichments() -> dict[str, Any]:
    state = _final_state_with_features()
    state["hypotheses"][0]["enrichments"] = {
        "full": {"verdict": "sound", "justification": "holds together"},
        "simulation": {"verdict": "holds", "decisive_step": "step two"},
    }
    return state


def test_report_payload_carries_every_persisted_review(
    isolated_db: str,
) -> None:
    run = seed_run("review goal")

    _persist_and_finalize(
        run, _final_state_with_mature_enrichments(), isolated_db
    )

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    agents = sorted(
        row["reviewer_agent"] for row in report["payload"]["reviews"]
    )
    assert "deep_verification" in agents
    assert "full_review" in agents
    assert "simulation_review" in agents


def test_report_payload_reviews_default_empty(isolated_db: str) -> None:
    run = seed_run("no review goal")

    _persist_and_finalize(run, _final_state_with_lineage(), isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["reviews"] == []


def test_mature_review_rows_are_distinctly_labeled(isolated_db: str) -> None:
    run = seed_run("labeled goal")

    _persist(
        run_id=run.id,
        final_state=_final_state_with_mature_enrichments(),
        db_path=isolated_db,
    )

    reviews = records.list_reviews(run.id, db_path=isolated_db)
    summaries = {
        r["reviewer_agent"]: r["summary"]
        for r in reviews
        if r["reviewer_agent"] in ("full_review", "simulation_review")
    }
    assert summaries == {
        "full_review": "Full review verdict: sound",
        "simulation_review": "Simulation review verdict: holds",
    }


# Unbounded transcripts for every pairing can exceed the report they accompany.


_TITLES = {"h1": "SGLT2 inhibition in fibroblasts", "h2": "NHE1 screening"}


def _transcript(verdict: str, turns: list[tuple[int, str, str]]) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "turns": [
                {"turn": turn, "favored": favored, "text": text}
                for turn, favored, text in turns
            ],
        }
    )


def _match(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "winner_id": "h1",
        "loser_id": "h2",
        "debate_turns": 2,
        "rationale": "Idea 1 prevails.",
        "debate_transcript": _transcript(
            "1",
            [
                (1, "1", "Idea 1 names a measurable target."),
                (2, "1", "The counter-argument does not survive."),
            ],
        ),
    }
    row.update(overrides)
    return row


def _debate_markdown(matches: list[dict[str, Any]] | None) -> str:
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[{"id": "h1", "title": _TITLES["h1"]}],
            matches=matches,
            hypothesis_title_by_id=dict(_TITLES),
        )
    )


def test_a_stored_debate_renders_turns_and_one_closing_verdict() -> None:
    markdown = _debate_markdown([_match()])

    assert "## Tournament debates" in markdown
    assert (
        "### Debate 1: 1. SGLT2 inhibition in fibroblasts "
        "vs 2. NHE1 screening" in markdown
    )
    assert "**Turn 1 (favors idea 1):** Idea 1 names a measurable target." in (
        markdown
    )
    assert "**Turn 2 (favors idea 1):** The counter-argument does not" in (
        markdown
    )
    assert "Better idea: 1" in markdown
    assert markdown.count("Better idea:") == 1


def test_idea_numbering_follows_the_verdict_not_the_winner() -> None:
    # Verdict numbers follow the judge's presentation order, not winner-first
    # order.
    markdown = _debate_markdown(
        [
            _match(
                debate_transcript=_transcript(
                    "2",
                    [
                        (1, "2", "Idea 2 is better grounded."),
                        (2, "2", "It stays better grounded."),
                    ],
                )
            )
        ]
    )

    assert (
        "### Debate 1: 1. NHE1 screening "
        "vs 2. SGLT2 inhibition in fibroblasts" in markdown
    )
    assert "Better idea: 2" in markdown


def test_a_match_with_no_stored_transcript_renders_as_it_did() -> None:
    markdown = _debate_markdown([_match(debate_transcript=None)])

    assert "## Tournament debates" not in markdown
    assert "Tournament debates" not in markdown


def test_no_matches_at_all_render_nothing() -> None:
    assert "## Tournament debates" not in _debate_markdown(None)
    assert "## Tournament debates" not in _debate_markdown([])


def test_a_single_turn_comparison_is_not_a_debate() -> None:
    # Single-turn matches would crowd multi-turn debates out of the capped
    # transcript section.
    markdown = _debate_markdown(
        [
            _match(
                debate_turns=1,
                debate_transcript=_transcript(
                    "1", [(1, "1", "Idea 1 is stronger.")]
                ),
            )
        ]
    )

    assert "## Tournament debates" not in markdown


def test_a_match_whose_idea_left_the_report_is_not_rendered() -> None:
    # Transcripts quote both ideas in full; including withheld participants
    # republishes gated content.
    markdown = _debate_markdown([_match(loser_id="h-withheld")])

    assert "## Tournament debates" not in markdown


def test_the_section_caps_how_many_debates_it_renders() -> None:
    matches = [
        _match(
            debate_turns=2 + index,
            debate_transcript=_transcript(
                "1",
                [
                    (turn, "1", f"Debate {index} turn {turn}.")
                    for turn in range(1, 3 + index)
                ],
            ),
        )
        for index in range(8)
    ]

    markdown = _debate_markdown(matches)

    assert markdown.count("### Debate ") == 5
    assert "Debate 7 turn 1." in markdown
    assert "Debate 0 turn 1." not in markdown


def test_a_pathologically_long_turn_is_truncated() -> None:
    markdown = _debate_markdown(
        [
            _match(
                debate_transcript=_transcript(
                    "1",
                    [
                        (1, "1", "word " * 900),
                        (2, "1", "Short close."),
                    ],
                )
            )
        ]
    )

    assert "…" in markdown
    assert len(markdown) < 6000


def test_only_the_first_turns_of_a_very_long_debate_render() -> None:
    markdown = _debate_markdown(
        [
            _match(
                debate_turns=10,
                debate_transcript=_transcript(
                    "1",
                    [
                        (turn, "1", f"Turn {turn} argument.")
                        for turn in range(1, 11)
                    ],
                ),
            )
        ]
    )

    assert "Turn 5 argument." in markdown
    assert "Turn 6 argument." not in markdown


def _ordered_transcript(
    verdict: str, turns: list[tuple[int, str, str, str]]
) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "turns": [
                {"turn": t, "favored": f, "text": x, "first": first}
                for t, f, x, first in turns
            ],
        }
    )


def test_a_swapped_turn_names_the_numbering_its_own_text_uses() -> None:
    # Turn order swaps hypothesis numbers; headers must explain the numbering
    # used by each argument.
    markdown = _debate_markdown(
        [
            _match(
                debate_transcript=_ordered_transcript(
                    "2",
                    [
                        (1, "2", "Hypothesis 2 is superior on impact.", "1"),
                        (2, "2", "Hypothesis 1 is superior on impact.", "2"),
                    ],
                )
            )
        ]
    )

    assert (
        '**Turn 1 (favors idea 2; this turn\'s "Hypothesis 1" is idea 1):**'
        " Hypothesis 2 is superior on impact." in markdown
    )
    assert (
        '**Turn 2 (favors idea 2; this turn\'s "Hypothesis 1" is idea 2):**'
        " Hypothesis 1 is superior on impact." in markdown
    )


def test_a_turn_without_a_recorded_order_renders_as_it_did() -> None:
    markdown = _debate_markdown([_match()])

    assert "**Turn 1 (favors idea 1):** Idea 1 names" in markdown


def test_supported_renders_as_the_published_plausible_label() -> None:
    line = _assumption_line(
        {"assumption": "KIRA6 inhibits IRE1a.", "support": "supported"}
    )

    assert line == "Assumption (Plausible): KIRA6 inhibits IRE1a."


def test_uncertain_renders_as_the_published_careful_investigation_label() -> (
    None
):
    line = _assumption_line(
        {
            "assumption": "AML cells are more ER-stress sensitive.",
            "support": "uncertain",
        }
    )

    assert line == (
        "Assumption (Plausible, but requires careful investigation):"
        " AML cells are more ER-stress sensitive."
    )


def test_likely_false_renders_as_implausible_not_the_published_unknown() -> (
    None
):
    # Unknown means untested, whereas likely_false means evidence points against
    # the assumption.
    line = _assumption_line(
        {
            "assumption": "The drug is non-toxic at the proposed dose.",
            "support": "likely_false",
        }
    )

    assert line == (
        "Assumption (Implausible): The drug is non-toxic at the proposed dose."
    )
    assert "Unknown" not in line


def test_missing_support_falls_back_to_unrated() -> None:
    line = _assumption_line({"assumption": "An untagged assumption."})

    assert line == "Assumption (unrated): An untagged assumption."


def test_reasoning_is_appended_after_the_label() -> None:
    line = _assumption_line(
        {
            "assumption": "KIRA6 inhibits IRE1a.",
            "support": "supported",
            "reasoning": "Prior work in other cell types supports this.",
        }
    )

    assert line == (
        "Assumption (Plausible): KIRA6 inhibits IRE1a. —"
        " Prior work in other cell types supports this."
    )


def test_an_unnamed_assumption_renders_nothing() -> None:
    assert _assumption_line({"support": "supported"}) is None


def test_the_full_review_critique_carries_the_published_labels() -> None:
    critique = "\n".join([])
    lines: list[str] = []
    _append_full_critique(
        lines,
        {
            "correctness": "Sound.",
            "assumptions": [
                {"assumption": "A", "support": "supported"},
                {"assumption": "B", "support": "uncertain"},
                {"assumption": "C", "support": "likely_false"},
            ],
        },
    )
    critique = "\n".join(lines)

    assert "Assumption (Plausible): A" in critique
    assert (
        "Assumption (Plausible, but requires careful investigation): B"
        in critique
    )
    assert "Assumption (Implausible): C" in critique


def test_simulation_detail_renders_points_and_decisive_step() -> None:
    points = ["Off-target editing risk.", "Delivery inefficiency."]
    review = {
        "failure_points": points,
        "decisive_step": "Step 3: enzyme binds substrate.",
        "verdict": "breaks_down",
    }
    assert _simulation_detail(review) == {
        "failure_points": points,
        "decisive_step": "Step 3: enzyme binds substrate.",
    }


def test_simulation_detail_empty_when_mechanism_holds() -> None:
    review = {"failure_points": [], "decisive_step": "", "verdict": "holds"}
    assert _simulation_detail(review) == {}


def test_simulation_detail_degrades_on_malformed_shapes() -> None:
    review = {
        "failure_points": "not a list",
        "decisive_step": 42,
    }
    detail = _simulation_detail(review)
    assert "failure_points" not in detail
    assert detail["decisive_step"] == "42"


def test_simulation_detail_caps_item_count_and_length() -> None:
    review = {
        "failure_points": [f"point {i}" for i in range(20)],
        "decisive_step": "x" * 1000,
    }
    detail = _simulation_detail(review)
    assert len(detail["failure_points"]) == 10
    assert len(detail["decisive_step"]) == 200


def test_verdict_detail_renders_go_no_go_and_timeframe() -> None:
    review = {
        "go_no_go_recommendation": "Go — pursue wet-lab validation.",
        "time_to_verdict": "2-4 weeks",
    }
    assert _verdict_detail(review) == {
        "go_no_go": "Go — pursue wet-lab validation.",
        "time_to_verdict": "2-4 weeks",
    }


def test_verdict_detail_empty_when_absent() -> None:
    assert _verdict_detail({"verdict": "sound"}) == {}


def test_review_detail_json_dispatches_by_key() -> None:
    simulation = {"failure_points": ["A flaw."], "decisive_step": "Step 1."}
    full = {"go_no_go_recommendation": "Go", "time_to_verdict": "Short"}

    sim_json = _review_detail_json("simulation", simulation)
    full_json = _review_detail_json("full", full)
    recurrent_json = _review_detail_json("recurrent", full)

    assert sim_json is not None
    assert json.loads(sim_json)["decisive_step"] == "Step 1."
    assert full_json is not None
    assert json.loads(full_json)["go_no_go"] == "Go"
    assert recurrent_json == full_json


def test_review_detail_json_none_when_nothing_structured() -> None:
    assert _review_detail_json("simulation", {"verdict": "holds"}) is None
    assert _review_detail_json("full", {"verdict": "sound"}) is None
    assert _review_detail_json("deep_verification", {"anything": "x"}) is None


def test_drain_persists_detail_json_on_the_review_row(
    isolated_db: str,
) -> None:
    state = _final_state_with_features()
    state["hypotheses"][0]["enrichments"] = {
        "full": {
            "verdict": "sound",
            "go_no_go_recommendation": "Go",
            "time_to_verdict": "Short",
        },
        "simulation": {
            "verdict": "breaks_down",
            "failure_points": ["Substrate saturation."],
            "decisive_step": "Step 4.",
        },
    }
    run = seed_run("detail-json goal")
    _persist_and_finalize(run, state, isolated_db)

    rows = records.list_reviews(run.id, db_path=isolated_db)
    reviews = {r["reviewer_agent"]: r for r in rows}
    full_detail = json.loads(reviews["full_review"]["detail_json"])
    sim_detail = json.loads(reviews["simulation_review"]["detail_json"])
    assert full_detail == {"go_no_go": "Go", "time_to_verdict": "Short"}
    assert sim_detail == {
        "failure_points": ["Substrate saturation."],
        "decisive_step": "Step 4.",
    }
    dv = [
        r
        for r in records.list_reviews(run.id, db_path=isolated_db)
        if r["reviewer_agent"] == "deep_verification"
    ]
    dv_detail = json.loads(dv[0]["detail_json"])
    assert dv_detail["verdict"] == "weakened"
    assert set(dv_detail["probes"][0]) == {
        "question",
        "answer",
        "reasoning",
        "fundamental",
    }

    # Drain/store/render catches reviewer-key mismatches isolated helpers miss.
    # Persistence uses asyncio.run internally, so this check stays synchronous.
    _payload, markdown = asyncio.run(_build_report(run, isolated_db))
    assert "#### Simulation review" in markdown
    assert "**Verdict:** Go" in markdown
    assert "**Time to Verdict:** Short" in markdown
    assert "1. **Failure point:** Substrate saturation." in markdown
