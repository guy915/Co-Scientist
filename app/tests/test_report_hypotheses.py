import json

import pytest

from app.report import content as report_content
from app.report.markdown import hypothesis as report_markdown_hypothesis
from app.report.markdown.hypothesis import (
    _HYPOTHESIS_DISCLAIMER,
    _render_hypothesis_simulation_review,
    _render_hypothesis_verdict,
)
from app.report.markdown.overview import render_research_overview_markdown
from tests._report_helpers import meta_review_markdown as _meta_review_markdown
from tests._report_helpers import render_markdown

# Contact examples can reference the full synthesis pool, beyond the five-item
# report slice.


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


def _review(agent: str, detail: dict[str, object] | None) -> dict[str, object]:
    row: dict[str, object] = {"hypothesis_id": "h1", "reviewer_agent": agent}
    if detail is not None:
        row["detail_json"] = json.dumps(detail)
    return row


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


def test_rejected_idea_reason_attributes_non_novelty_to_the_reviewer() -> None:
    # Novelty scores are unaided model judgments; rejection reasons must
    # attribute rather than assert them.
    rejected = _hypothesis("h1", "Unsound idea", status="rejected")
    reasons = report_content._non_viable_reasons(rejected, {})
    assert len(reasons) == 1
    assert "reviewer judged" in reasons[0]
    assert "not a literature search" in reasons[0]


@pytest.mark.parametrize(
    "meta_review",
    [
        {"candidate_comparison": {"ideas": ["not a dict"]}},
        {
            "candidate_comparison": {
                "ideas": [{"distinguishing_attribute": "orphaned"}]
            }
        },
        {"existing_solutions_comparison": {"rows": ["not a dict"]}},
        {"existing_solutions_comparison": {"rows": [{"approach": "orphaned"}]}},
    ],
)
def test_a_malformed_or_unlabelled_comparison_entry_is_skipped(
    meta_review: dict[str, object],
) -> None:
    markdown = _meta_review_markdown(meta_review)

    assert "not a dict" not in markdown
    assert "orphaned" not in markdown


def test_the_verdict_prefers_the_recurrent_review_and_degrades_quietly() -> (
    None
):
    recurrent = [
        _review("full_review", {"go_no_go": "stale framing"}),
        _review("recurrent_review", {"go_no_go": "fresh framing"}),
    ]
    malformed = {
        "hypothesis_id": "h1",
        "reviewer_agent": "full_review",
        "detail_json": "{not valid json",
    }

    assert _render_hypothesis_verdict(recurrent) == [
        "**Verdict:** fresh framing",
        "",
    ]
    assert _render_hypothesis_verdict([malformed]) == []
    assert _render_hypothesis_verdict([]) == []


def test_the_simulation_review_skips_blank_points_and_holds_its_tongue() -> (
    None
):
    blank = _review(
        "simulation_review", {"failure_points": ["", "   ", "A real point."]}
    )

    assert _render_hypothesis_simulation_review([blank]) == [
        "#### Simulation review",
        "",
        "1. **Failure point:** A real point.",
        "",
    ]
    assert (
        _render_hypothesis_simulation_review([_review("simulation_review", {})])
        == []
    )


@pytest.mark.parametrize(
    ("extra", "disclosed"),
    [
        ({}, True),
        ({"novelty_validation": "Checked against 4 retrieved papers."}, False),
    ],
)
def test_novelty_is_disclosed_as_unverified_unless_checked_against_literature(
    extra: dict[str, object], disclosed: bool
) -> None:
    markdown = render_markdown(
        research_goal="Map the feedback loop.",
        top_hypotheses=[_hypothesis("h1", "Feedback control", **extra)],
    )

    assert ("reviewing model's own judgment" in markdown) is disclosed
