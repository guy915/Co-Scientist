import json

from app.report import content as report_content
from app.report import markdown as report_markdown
from app.report.build import _hypothesis_title_by_id
from app.report.markdown import hypothesis as report_markdown_hypothesis
from app.report.markdown.hypothesis import (
    _HYPOTHESIS_DISCLAIMER,
    _render_hypothesis_simulation_review,
    _render_hypothesis_verdict,
    _reviews_by_hypothesis,
)
from app.report.markdown.overview import render_research_overview_markdown

# Contact examples can reference the full synthesis pool, beyond the five-item
# report slice.


def test_maps_every_hypothesis_with_both_fields() -> None:
    hyps = [
        {"id": "h1", "title": "HDAC inhibition reverses fibrosis"},
        {"id": "h2", "title": "SIRT1 activation blocks deposition"},
    ]

    result = _hypothesis_title_by_id(hyps)

    assert result == {
        "h1": "HDAC inhibition reverses fibrosis",
        "h2": "SIRT1 activation blocks deposition",
    }


def test_skips_a_hypothesis_missing_an_id_or_title() -> None:
    hyps = [
        {"id": "h1", "title": ""},
        {"id": "", "title": "Untitled but id-less"},
        {"id": "h3", "title": "Complete"},
    ]

    result = _hypothesis_title_by_id(hyps)

    assert result == {"h3": "Complete"}


def test_an_empty_pool_maps_to_nothing() -> None:
    assert _hypothesis_title_by_id([]) == {}


def _meta_review_markdown(meta_review: dict[str, object]) -> str:
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
            meta_review=meta_review,
        )
    )


def test_a_populated_comparison_renders_summary_and_idea_columns() -> None:
    markdown = _meta_review_markdown(
        {
            "candidate_comparison": {
                "thematic_summary": (
                    "The ideas split into two mechanistic themes."
                ),
                "ideas": [
                    {
                        "idea": "Hypothesis 1: NHE1 blockade",
                        "distinguishing_attribute": (
                            "Targets an established clinical checkpoint."
                        ),
                        "computational_scalability": "Low compute burden.",
                        "supporting_evidence_basis": (
                            "Human scRNA-seq co-localization."
                        ),
                        "primary_novelty_parameter": (
                            "First to link NHE1 to RSK in this context."
                        ),
                    }
                ],
            }
        }
    )

    assert "### Comparison of candidate ideas" in markdown
    assert "The ideas split into two mechanistic themes." in markdown
    assert "Hypothesis 1: NHE1 blockade" in markdown
    assert "Targets an established clinical checkpoint." in markdown
    assert "Low compute burden." in markdown
    assert "Human scRNA-seq co-localization." in markdown
    assert "First to link NHE1 to RSK in this context." in markdown


def test_comparison_a_populated_comparison_renders_domain_aware_axes() -> None:
    markdown = _meta_review_markdown(
        {
            "candidate_comparison": {
                "thematic_summary": (
                    "The ideas split into two mechanistic themes."
                ),
                "axes": ["Off-target risk", "Model system"],
                "ideas": [
                    {
                        "idea": "Hypothesis 1: NHE1 blockade",
                        "values": [
                            "Low -- selective for cardiac NHE1.",
                            "Isogenic organoid pairs.",
                        ],
                    }
                ],
            }
        }
    )

    assert "### Comparison of candidate ideas" in markdown
    assert "The ideas split into two mechanistic themes." in markdown
    assert "Hypothesis 1: NHE1 blockade" in markdown
    assert "**Off-target risk:** Low -- selective for cardiac NHE1." in markdown
    assert "**Model system:** Isogenic organoid pairs." in markdown
    assert "Computational scalability" not in markdown


def test_an_idea_with_more_values_than_axes_pairs_up_to_the_shorter_side() -> (
    None
):
    markdown = _meta_review_markdown(
        {
            "candidate_comparison": {
                "axes": ["Off-target risk"],
                "ideas": [
                    {
                        "idea": "Hypothesis 1: NHE1 blockade",
                        "values": ["Low.", "An orphaned second value."],
                    }
                ],
            }
        }
    )

    assert "**Off-target risk:** Low." in markdown
    assert "An orphaned second value." not in markdown


def test_no_candidate_comparison_renders_no_section() -> None:
    markdown = _meta_review_markdown(
        {"summary": "A synthesis with no comparison."}
    )

    assert "Comparison of candidate ideas" not in markdown


def test_a_malformed_idea_entry_is_skipped_not_stringified() -> None:
    markdown = _meta_review_markdown(
        {"candidate_comparison": {"ideas": ["not a dict"]}}
    )

    assert "not a dict" not in markdown


def test_an_idea_with_no_label_is_skipped() -> None:
    markdown = _meta_review_markdown(
        {
            "candidate_comparison": {
                "ideas": [{"distinguishing_attribute": "orphaned"}]
            }
        }
    )

    assert "orphaned" not in markdown


def _groups_markdown(
    contacts: list[dict[str, object]],
    groups: list[dict[str, object]] | None = None,
    hypothesis_title_by_id: dict[str, str] | None = None,
) -> str:
    payload: dict[str, object] = {"research_contacts": contacts}
    if groups is not None:
        payload["research_contact_groups"] = groups
    return "\n".join(
        render_research_overview_markdown(payload, hypothesis_title_by_id)
    )


def test_a_group_heading_and_rationale_render() -> None:
    markdown = _groups_markdown(
        contacts=[
            {
                "name": "Ada Researcher",
                "expertise": "Chromatin biology",
                "justification": "Authored the analyzed source.",
                "research_direction": "Epigenetic control of fibrosis",
            },
        ],
        groups=[
            {
                "research_direction": "Epigenetic control of fibrosis",
                "rationale": "Both bring complementary expertise.",
            }
        ],
    )

    assert "### Epigenetic control of fibrosis" in markdown
    assert (
        "**Why they are best for this direction:** Both bring"
        " complementary expertise." in markdown
    )
    assert "#### Ada Researcher" in markdown
    assert "**Research direction:**" not in markdown


def test_a_group_with_two_contacts_lists_both_beneath_it() -> None:
    markdown = _groups_markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"},
            {"name": "Bo Scientist", "research_direction": "Direction A"},
        ],
        groups=[{"research_direction": "Direction A", "rationale": "Why."}],
    )

    heading_index = markdown.index("### Direction A")
    ada_index = markdown.index("#### Ada Researcher")
    bo_index = markdown.index("#### Bo Scientist")
    assert heading_index < ada_index
    assert heading_index < bo_index


def test_example_hypothesis_titles_resolve_by_id() -> None:
    markdown = _groups_markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"}
        ],
        groups=[
            {
                "research_direction": "Direction A",
                "rationale": "Why.",
                "example_hypothesis_ids": ["h1", "h2", "missing"],
            }
        ],
        hypothesis_title_by_id={
            "h1": "HDAC inhibition reverses fibrosis",
            "h2": "SIRT1 activation blocks collagen deposition",
        },
    )

    assert "**Example Hypothesis Titles:**" in markdown
    assert "- HDAC inhibition reverses fibrosis" in markdown
    assert "- SIRT1 activation blocks collagen deposition" in markdown
    assert "missing" not in markdown


def test_no_example_titles_omits_the_bullet_heading() -> None:
    markdown = _groups_markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"}
        ],
        groups=[{"research_direction": "Direction A", "rationale": "Why."}],
    )

    assert "Example Hypothesis Titles" not in markdown


def test_a_contact_matching_no_group_falls_back_to_the_flat_shape() -> None:
    markdown = _groups_markdown(
        contacts=[
            {
                "name": "Cy Unaffiliated",
                "expertise": "Independent review",
                "justification": "Cited widely in this area.",
                "research_direction": "Direction Z",
            }
        ],
        groups=[{"research_direction": "Direction A", "rationale": "Why."}],
    )

    assert "### Cy Unaffiliated" in markdown
    assert "**Research direction:** Direction Z" in markdown
    assert "Direction A" not in markdown


def test_a_report_with_no_groups_field_is_unaffected() -> None:
    markdown = _groups_markdown(
        contacts=[
            {
                "name": "Ada Researcher",
                "expertise": "Chromatin biology",
                "justification": "Authored the analyzed source.",
                "research_direction": "Epigenetic control of fibrosis",
            }
        ]
    )

    assert "### Ada Researcher" in markdown
    assert "**Research direction:** Epigenetic control of fibrosis" in markdown
    assert "Why they are best for this direction" not in markdown


def test_a_group_naming_no_matching_contact_renders_nothing() -> None:
    markdown = _groups_markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"}
        ],
        groups=[
            {"research_direction": "Direction Never Tagged", "rationale": "X"}
        ],
    )

    assert "Direction Never Tagged" not in markdown
    assert "### Direction A" not in markdown
    assert "### Ada Researcher" in markdown


def test_justification_renders_under_its_published_label() -> None:
    markdown = _groups_markdown(
        [
            {
                "name": "Ada Researcher",
                "justification": "Authored the analyzed source.",
            }
        ]
    )

    assert "**Justification:** Authored the analyzed source." in markdown


def test_the_evidence_citing_field_renders_under_a_fixed_name() -> None:
    markdown = _groups_markdown(
        [
            {
                "name": "Ada Researcher",
                "justification": "Authored the analyzed source.",
                "source_title": "A biofilm study",
                "source_url": "https://example.org/paper",
            }
        ]
    )

    assert (
        "**Supporting article:** [A biofilm study]"
        "(https://example.org/paper)" in markdown
    )
    assert "Evidence:" not in markdown


def test_an_unsourced_contact_renders_no_supporting_article_line() -> None:
    markdown = _groups_markdown(
        [{"name": "Ada Researcher", "justification": "Relevant background."}]
    )

    assert "Supporting article" not in markdown


def test_expertise_is_the_one_field_no_exemplar_supports() -> None:
    # Expertise is real model output; removing its rendering requires a
    # schema/prompt change too.
    markdown = _groups_markdown(
        [
            {
                "candidate_id": "author-1-1",
                "name": "Ada Researcher",
                "expertise": "Biofilm metabolism",
                "justification": "Authored the analyzed source.",
                "research_direction": "Direction one",
            }
        ]
    )

    assert "**Relevant expertise:** Biofilm metabolism" in markdown
    # candidate_id is selection provenance against verified candidates, never
    # reader-facing text.
    assert "author-1-1" not in markdown
    for label in (
        "Research direction:",
        "Relevant expertise:",
        "Justification:",
    ):
        assert markdown.count(label) == 1
    assert "Supporting article:" not in markdown


def test_a_contact_renders_its_research_direction() -> None:
    markdown = _groups_markdown(
        [
            {
                "name": "Ada Researcher",
                "expertise": "Mitochondrial base excision repair",
                "justification": "Authored the analyzed source.",
                "research_direction": (
                    "Oxidative DNA Damage & Mitochondrial Base Excision"
                    " Repair (BER) in ALS"
                ),
            }
        ]
    )

    assert (
        "**Research direction:** Oxidative DNA Damage & Mitochondrial Base"
        " Excision Repair (BER) in ALS" in markdown
    )


def test_a_contact_with_no_research_direction_omits_the_line() -> None:
    markdown = _groups_markdown(
        [
            {
                "name": "Ada Researcher",
                "expertise": "Mitochondrial base excision repair",
                "justification": "Authored the analyzed source.",
            }
        ]
    )

    assert "Research direction" not in markdown
    assert "Ada Researcher" in markdown


def test_a_populated_comparison_renders_summary_and_row_columns() -> None:
    markdown = _meta_review_markdown(
        {
            "existing_solutions_comparison": {
                "summary": (
                    "Current care slows progression rather than reversing it."
                ),
                "rows": [
                    {
                        "method": "Beta-blockade (standard of care)",
                        "approach": "Reduce afterload pharmacologically.",
                        "sensitivity_to_novelty": (
                            "Does not address the RSK-NHE1 axis."
                        ),
                        "scalability": "Widely available, low cost.",
                    }
                ],
            }
        }
    )

    assert "### Comparison to existing solutions" in markdown
    assert (
        "Current care slows progression rather than reversing it." in markdown
    )
    assert "Beta-blockade (standard of care)" in markdown
    assert "Reduce afterload pharmacologically." in markdown
    assert "Does not address the RSK-NHE1 axis." in markdown
    assert "Widely available, low cost." in markdown


def test_solutions_a_populated_comparison_renders_domain_aware_axes() -> None:
    markdown = _meta_review_markdown(
        {
            "existing_solutions_comparison": {
                "summary": (
                    "Current care slows progression rather than reversing it."
                ),
                "axes": ["Mechanism targeted", "Availability"],
                "rows": [
                    {
                        "method": "Beta-blockade (standard of care)",
                        "values": [
                            "Afterload, not the RSK-NHE1 axis.",
                            "Widely available, low cost.",
                        ],
                    }
                ],
            }
        }
    )

    assert "### Comparison to existing solutions" in markdown
    assert "Beta-blockade (standard of care)" in markdown
    assert (
        "**Mechanism targeted:** Afterload, not the RSK-NHE1 axis." in markdown
    )
    assert "**Availability:** Widely available, low cost." in markdown
    assert "Sensitivity to novelty" not in markdown


def test_no_existing_solutions_comparison_renders_no_section() -> None:
    markdown = _meta_review_markdown(
        {"summary": "A synthesis with no comparison."}
    )

    assert "Comparison to existing solutions" not in markdown


def test_a_malformed_row_entry_is_skipped_not_stringified() -> None:
    markdown = _meta_review_markdown(
        {"existing_solutions_comparison": {"rows": ["not a dict"]}}
    )

    assert "not a dict" not in markdown


def test_a_row_with_no_method_is_skipped() -> None:
    markdown = _meta_review_markdown(
        {"existing_solutions_comparison": {"rows": [{"approach": "orphaned"}]}}
    )

    assert "orphaned" not in markdown


# The assembled snapshot catches ordering/separator drift that subsection-only
# tests miss.


def test_hypothesis_entry_renders_every_subsection_verbatim() -> None:
    hyp = {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "elo_rating": 1487,
        "introduction": "Metabolic disease is a major cause of morbidity.",
        "recent_findings": "Aldolase inhibitors show early promise.",
        "statement": "The loop raises steady-state flux.",
        "mechanism": "Its product inhibits the enzyme allosterically [C1].",
        "expected_effect": "Flux increases at least twofold.",
        "experimental_context": (
            "1. Script the assay.\n2. Run the pilot.\n"
            "**Go:** Effect size >= 0.5.\n**No-Go:** Effect size < 0.2."
        ),
        "safety_and_toxicity": "Limited safety data exists for this class.",
    }
    edges = [
        {
            "hypothesis_id": "h1",
            "claim_role": "fundamental",
            "claim": "The product inhibits the enzyme.",
            "label": "supports",
            "supporting": [
                {
                    "quote": "Product X inhibits enzyme Y.",
                    "source_title": "Smith 2020",
                    "url": "https://example.com/smith",
                },
                "A bare string span with   extra   whitespace.",
            ],
            "contradicting": [
                {
                    "quote": "No inhibition seen in vitro.",
                    "source": "Jones 2019",
                },
            ],
        },
    ]
    references = [
        (
            "C1",
            {
                "title": "Allosteric inhibition review",
                "authors": ["Doe"],
                "year": 2018,
                "url": "https://example.com/doe",
            },
        ),
    ]
    reviews = [
        {
            "hypothesis_id": "h1",
            "reviewer_agent": "review",
            "detail_json": json.dumps(
                {
                    "scores": {"scientific_soundness": 8, "novelty": 6},
                    "detailed_feedback": {
                        "scientific_soundness": "The mechanism is consistent.",
                        "novelty": "The pairing is unusual.",
                    },
                    "already_explored": ["Target engagement is documented."],
                    "novel_aspects": ["The stress response is new."],
                    "constructive_feedback": "Name the control arm.",
                }
            ),
        },
        {
            "hypothesis_id": "h1",
            "reviewer_agent": "full_review",
            "detail_json": json.dumps(
                {
                    "go_no_go": "Go — pursue wet-lab validation.",
                    "time_to_verdict": "2-4 weeks",
                    "correctness": "The logic holds throughout.",
                    "assumptions": [
                        {
                            "assumption": "The receptor is expressed.",
                            "reasoning": "Two cohorts detect it.",
                            "support": "Plausible",
                        }
                    ],
                    "reviews_summary": {
                        "executive_verdict": "Well conceived, mis-calibrated.",
                        "critical_flaws": ["The pore benchmark is wrong."],
                        "conclusion": "Recalibrate before testing.",
                    },
                }
            ),
        },
        {
            "hypothesis_id": "h1",
            "reviewer_agent": "deep_verification",
            "detail_json": json.dumps(
                {
                    "verdict": "weakened",
                    "probes": [
                        {
                            "question": "Is inhibition alone sufficient?",
                            "answer": "It targets a key node.",
                            "reasoning": "Not incoherent, but it needs care.",
                            "fundamental": True,
                        }
                    ],
                }
            ),
        },
        {
            "hypothesis_id": "h1",
            "reviewer_agent": "simulation_review",
            "detail_json": json.dumps(
                {
                    "failure_points": ["Off-target editing risk."],
                    "decisive_step": "Step 3: enzyme binds substrate.",
                }
            ),
        },
    ]

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        1, hyp, edges, references, reviews
    )

    assert lines == [
        "### 1. **Co-Scientist - Feedback control is rate-limiting.**"
        "  _Elo: 1487_",
        _HYPOTHESIS_DISCLAIMER,
        "",
        "#### Introduction",
        "",
        "Metabolic disease is a major cause of morbidity.",
        "",
        "#### Recent findings and related research",
        "",
        "Aldolase inhibitors show early promise.",
        "",
        "**Proposed hypothesis:** The loop raises steady-state flux.",
        "",
        "**Mechanism:** Its product inhibits the enzyme allosterically [C1].",
        "",
        "**Predicted effect:** Flux increases at least twofold.",
        "",
        "#### Steps to test the idea",
        "",
        "1. Script the assay.\n2. Run the pilot.\n"
        "**Go:** Effect size >= 0.5.\n**No-Go:** Effect size < 0.2.",
        "",
        "#### References",
        "",
        "- **[C1]** [Doe et al., 2018 — Allosteric inhibition review]"
        "(https://example.com/doe)",
        "",
        "#### Safety and toxicity",
        "",
        "Limited safety data exists for this class.",
        "",
        "#### Reviews summary",
        "",
        "##### 1. Executive Verdict",
        "",
        "Well conceived, mis-calibrated.",
        "",
        "##### 2. Critical Flaws",
        "",
        "- The pore benchmark is wrong.",
        "",
        "##### 8. Conclusion",
        "",
        "Recalibrate before testing.",
        "",
        "**Verdict:** Go — pursue wet-lab validation.",
        "",
        "**Time to Verdict:** 2-4 weeks",
        "",
        "#### Appendix:",
        "",
        "**All reviews:**",
        "",
        "##### Correctness",
        "",
        "**Related Article Abstracts**",
        "",
        "- **[C1]** Doe et al., 2018 — Allosteric inhibition review",
        "",
        "The mechanism is consistent.",
        "",
        "**Detailed Assumptions**",
        "",
        "- **Plausible:** The receptor is expressed. — Two cohorts detect it.",
        "",
        "**Reasoning about Correctness**",
        "",
        "The logic holds throughout.",
        "",
        "**Suggested Improvements**",
        "",
        "Name the control arm.",
        "",
        "**Answer: 8**",
        "",
        "##### Novelty",
        "",
        "**Related Article Abstract Titles**",
        "",
        "- **[C1]** Doe et al., 2018 — Allosteric inhibition review",
        "",
        "The pairing is unusual.",
        "",
        "Aspects already explored:",
        "- Target engagement is documented.",
        "",
        "Novel Aspects:",
        "- The stress response is new.",
        "",
        "**Answer: 6**",
        "",
        "#### Simulation review",
        "",
        "1. **Failure point:** Off-target editing risk.",
        "",
        "**Decisive step:** Step 3: enzyme binds substrate.",
        "",
        "#### Deep verification",
        "",
        "**Verdict:** weakened",
        "",
        "**Probe 1 (fundamental assumption)**",
        "",
        "Question: Is inhibition alone sufficient?",
        "",
        "Answer: It targets a key node.",
        "",
        "Reasoning: Not incoherent, but it needs care.",
        "",
        "#### Critiques",
        "",
        "Here's a summary of the negative critiques from the reviews:",
        "",
        "- The pore benchmark is wrong.",
        "",
        "**Claim evidence:**",
        "",
        "- **Supported · fundamental** — The product inhibits the enzyme.",
        "  Assessment method: not recorded.",
        "  - Supporting span — [Smith 2020](https://example.com/smith):"
        " “Product X inhibits enzyme Y.”",
        "  - Supporting span: “A bare string span with extra whitespace.”",
        "  - Contradicting span — Jones 2019: “No inhibition seen in vitro.”",
        "",
    ]


def test_hypothesis_entry_omits_every_optional_subsection_when_absent() -> None:
    # Research-purpose disclosure is unconditional even when every optional idea
    # field is absent.
    hyp = {"id": "h2", "title": "Bare hypothesis.", "elo_rating": 1200}

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        2, hyp, [], [], []
    )

    assert lines == [
        "### 2. **Co-Scientist - Bare hypothesis.**  _Elo: 1200_",
        _HYPOTHESIS_DISCLAIMER,
        "",
    ]


def test_hypothesis_title_is_bold_and_product_prefixed() -> None:
    hyp = {"id": "h3", "title": "Rate-limiting feedback."}

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        3, hyp, [], [], []
    )

    assert lines[0] == (
        "### 3. **Co-Scientist - Rate-limiting feedback.**  _Elo: _"
    )


_NOTICE_PREFIX = "**Scientist-contributed — not yet reviewed:**"


def test_unreviewed_scientist_admission_notice_leads_the_entry() -> None:
    hyp = {
        "id": "h5",
        "title": "Scientist idea.",
        "elo_rating": 1300,
        "created_by_agent": "scientist_manual",
        "statement": "A contributed statement.",
    }

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        1, hyp, [], [], []
    )

    assert lines[1] == _HYPOTHESIS_DISCLAIMER
    assert lines[2] == ""
    assert lines[3].startswith(_NOTICE_PREFIX)
    assert lines[4] == ""
    assert "**Proposed hypothesis:** A contributed statement." in lines


def test_scientist_admission_notice_absent_once_peer_reviewed() -> None:
    hyp = {
        "id": "h6",
        "title": "Scientist idea.",
        "created_by_agent": "scientist_manual",
    }
    own_review = [{"hypothesis_id": "h6", "reviewer_agent": "scientist"}]
    peer_review = [{"hypothesis_id": "h6", "reviewer_agent": "review"}]

    still_flagged = report_markdown_hypothesis._render_hypothesis_entry(
        1, hyp, [], [], own_review
    )
    cleared = report_markdown_hypothesis._render_hypothesis_entry(
        1, hyp, [], [], peer_review
    )

    assert any(line.startswith(_NOTICE_PREFIX) for line in still_flagged)
    assert not any(line.startswith(_NOTICE_PREFIX) for line in cleared)


def test_scientist_admission_notice_absent_for_agent_ideas() -> None:
    hyp = {"id": "h7", "title": "Agent idea.", "created_by_agent": "generation"}

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        1, hyp, [], [], []
    )

    assert not any(line.startswith(_NOTICE_PREFIX) for line in lines)


def test_hypothesis_title_falls_back_to_untitled_when_absent() -> None:
    lines = report_markdown_hypothesis._render_hypothesis_entry(
        1, {"id": "h4"}, [], [], []
    )

    assert lines[0] == "### 1. **Co-Scientist - Untitled**  _Elo: _"


def _review(agent: str, detail: dict[str, object] | None) -> dict[str, object]:
    row: dict[str, object] = {"hypothesis_id": "h1", "reviewer_agent": agent}
    if detail is not None:
        row["detail_json"] = json.dumps(detail)
    return row


def test_verdict_renders_both_fields_when_present() -> None:
    reviews = [
        _review(
            "full_review",
            {"go_no_go": "Go — pursue validation.", "time_to_verdict": "Short"},
        )
    ]
    assert _render_hypothesis_verdict(reviews) == [
        "**Verdict:** Go — pursue validation.",
        "",
        "**Time to Verdict:** Short",
        "",
    ]


def test_verdict_prefers_recurrent_over_full() -> None:
    reviews = [
        _review("full_review", {"go_no_go": "stale framing"}),
        _review("recurrent_review", {"go_no_go": "fresh framing"}),
    ]
    lines = _render_hypothesis_verdict(reviews)
    assert lines[0] == "**Verdict:** fresh framing"


def test_verdict_omits_entirely_when_no_review_row() -> None:
    assert _render_hypothesis_verdict([]) == []


def test_verdict_omits_entirely_when_detail_json_absent() -> None:
    reviews = [{"hypothesis_id": "h1", "reviewer_agent": "full_review"}]
    assert _render_hypothesis_verdict(reviews) == []


def test_verdict_renders_only_the_field_present() -> None:
    reviews = [_review("full_review", {"time_to_verdict": "2-3 months"})]
    assert _render_hypothesis_verdict(reviews) == [
        "**Time to Verdict:** 2-3 months",
        "",
    ]


def test_verdict_degrades_on_malformed_json() -> None:
    reviews = [
        {
            "hypothesis_id": "h1",
            "reviewer_agent": "full_review",
            "detail_json": "{not valid json",
        }
    ]
    assert _render_hypothesis_verdict(reviews) == []


def test_verdict_degrades_when_detail_json_is_not_an_object() -> None:
    reviews = [_review("full_review", None)]
    reviews[0]["detail_json"] = json.dumps(["go", "short"])
    assert _render_hypothesis_verdict(reviews) == []


def test_verdict_coerces_non_string_field_values() -> None:
    detail: dict[str, object] = {"go_no_go": 42, "time_to_verdict": None}
    reviews = [_review("full_review", detail)]
    assert _render_hypothesis_verdict(reviews) == [
        "**Verdict:** 42",
        "",
    ]


def test_simulation_review_renders_numbered_points_and_decisive_step() -> None:
    reviews = [
        _review(
            "simulation_review",
            {
                "failure_points": [
                    "Off-target editing risk.",
                    "Delivery inefficiency.",
                ],
                "decisive_step": "Step 4: vector reaches target tissue.",
            },
        )
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "1. **Failure point:** Off-target editing risk.",
        "2. **Failure point:** Delivery inefficiency.",
        "",
        "**Decisive step:** Step 4: vector reaches target tissue.",
        "",
    ]


def test_simulation_review_omits_when_mechanism_holds() -> None:
    reviews = [_review("simulation_review", {})]
    assert _render_hypothesis_simulation_review(reviews) == []


def test_simulation_review_omits_when_no_review_row() -> None:
    assert _render_hypothesis_simulation_review([]) == []


def test_simulation_review_renders_decisive_step_alone() -> None:
    reviews = [
        _review("simulation_review", {"decisive_step": "Step 1: binding."})
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "**Decisive step:** Step 1: binding.",
        "",
    ]


def test_simulation_review_degrades_when_failure_points_not_a_list() -> None:
    reviews = [
        _review(
            "simulation_review",
            {"failure_points": "a single string", "decisive_step": "Step 2."},
        )
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "**Decisive step:** Step 2.",
        "",
    ]


def test_simulation_review_skips_blank_points() -> None:
    reviews = [
        _review(
            "simulation_review",
            {"failure_points": ["", "   ", "A real point."]},
        )
    ]
    assert _render_hypothesis_simulation_review(reviews) == [
        "#### Simulation review",
        "",
        "1. **Failure point:** A real point.",
        "",
    ]


def test_reviews_by_hypothesis_keeps_each_hypothesis_separate() -> None:
    reviews: list[dict[str, object]] = [
        _review("simulation_review", {"decisive_step": "for h1"}),
        {
            "hypothesis_id": "h2",
            "reviewer_agent": "simulation_review",
            "detail_json": json.dumps({"decisive_step": "for h2"}),
        },
    ]
    grouped = _reviews_by_hypothesis(reviews)
    assert [r["hypothesis_id"] for r in grouped["h1"]] == ["h1"]
    assert [r["hypothesis_id"] for r in grouped["h2"]] == ["h2"]
    assert "h3" not in grouped


# Absent corpus verification must be disclosed; model novelty judgments are not
# settled facts.


def _hypothesis(
    identifier: str, title: str, **extra: object
) -> dict[str, object]:
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        **extra,
    }


def test_report_markdown_discloses_unverified_novelty_by_default() -> None:
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[_hypothesis("h1", "Feedback control")],
        )
    )
    assert "not a" in markdown
    assert "reviewing model's own judgment" in markdown


def test_report_markdown_omits_disclosure_when_novelty_is_verified() -> None:
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[
                _hypothesis(
                    "h1",
                    "Feedback control",
                    novelty_validation="Checked against 4 retrieved papers.",
                )
            ],
        )
    )
    assert "reviewing model's own judgment" not in markdown


def test_report_markdown_omits_disclosure_with_no_hypotheses() -> None:
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[],
        )
    )
    assert "reviewing model's own judgment" not in markdown


def test_rejected_idea_reason_attributes_non_novelty_to_the_reviewer() -> None:
    # Novelty scores are unaided model judgments; rejection reasons must
    # attribute rather than assert them.
    rejected = _hypothesis("h1", "Unsound idea", status="rejected")
    reasons = report_content._non_viable_reasons(rejected, {})
    assert len(reasons) == 1
    assert "reviewer judged" in reasons[0]
    assert "not a literature search" in reasons[0]
