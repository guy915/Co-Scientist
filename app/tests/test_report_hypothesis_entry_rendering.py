"""Pins one 'Top hypotheses' entry's full rendered markdown, line for line.

``_render_hypothesis_entry`` composes a mandatory title+disclaimer (R14-13)
and twelve optional subsections (scene-setting, proposed hypothesis,
mechanism, steps to test the idea, references, safety, the eight-part
Reviews summary, Go/No-Go verdict, the Appendix's All reviews block,
simulation review, deep verification, claim evidence) into one entry.
Every other report test
asserts a substring or a heading's presence/absence; none pin the
assembled entry exactly, so a refactor of the composition itself --
reordering, an extra blank line, a dropped separator -- could pass every
existing test while still changing what a reader sees. This test exercises
all twelve optional subsections on one hypothesis (including both the
dict-with-url and bare-string evidence-span shapes
``_render_evidence_span`` renders differently) and pins the exact
line-by-line output.
"""

import json

from app.report.markdown import hypothesis as report_markdown_hypothesis
from app.report.markdown.hypothesis import _HYPOTHESIS_DISCLAIMER


def test_hypothesis_entry_renders_every_subsection_verbatim() -> None:
    """Every optional subsection populated renders the exact pinned lines."""
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
    """No optional field renders only title + disclaimer -- no stray blanks.

    The disclaimer is not itself optional (R14-13): it renders even when
    every field-derived subsection is absent.
    """
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
    """R14-12: the title carries Google's bold/prefixed structure, adapted.

    Published shape is ``# **<Product> - <Title>**`` -- an H1. Ours keeps
    the entry's existing ``###`` level (a subsection of one combined
    report, not a standalone per-hypothesis document -- see the docstring
    on ``_render_hypothesis_entry``) while mirroring bold + product-name
    prefix + concise title.
    """
    hyp = {"id": "h3", "title": "Rate-limiting feedback."}

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        3, hyp, [], [], []
    )

    assert lines[0] == (
        "### 3. **Co-Scientist - Rate-limiting feedback.**  _Elo: _"
    )


_NOTICE_PREFIX = "**Scientist-contributed — not yet reviewed:**"


def test_unreviewed_scientist_admission_notice_leads_the_entry() -> None:
    """A scientist idea with no peer review is labeled under the disclaimer.

    HITL-MANUAL-HYP-001 residual window: the notice sits right after the
    disclaimer, before the idea's own body, so provenance reads first.
    """
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
    # The idea's own body still follows the notice.
    assert "**Proposed hypothesis:** A contributed statement." in lines


def test_scientist_admission_notice_absent_once_peer_reviewed() -> None:
    """A non-scientist review clears the notice; a scientist's own does not."""
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
    """An agent-generated idea never carries the notice, reviewed or not."""
    hyp = {"id": "h7", "title": "Agent idea.", "created_by_agent": "generation"}

    lines = report_markdown_hypothesis._render_hypothesis_entry(
        1, hyp, [], [], []
    )

    assert not any(line.startswith(_NOTICE_PREFIX) for line in lines)


def test_hypothesis_title_falls_back_to_untitled_when_absent() -> None:
    """A hypothesis with neither ``title`` nor ``text`` still renders safely.

    Covers the json_object downgrade: a required field can simply be
    missing, and ``hypothesis_title`` degrades to "Untitled" rather than
    raising.
    """
    lines = report_markdown_hypothesis._render_hypothesis_entry(
        1, {"id": "h4"}, [], [], []
    )

    assert lines[0] == "### 1. **Co-Scientist - Untitled**  _Elo: _"
