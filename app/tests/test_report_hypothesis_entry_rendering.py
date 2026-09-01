"""Pins one 'Top hypotheses' entry's full rendered markdown, line for line.

``_render_hypothesis_entry`` composes a mandatory title+disclaimer (R14-13)
and nine optional subsections (scene-setting, proposed hypothesis,
mechanism, steps to test the idea, references, safety, Go/No-Go verdict,
simulation review, claim evidence) into one entry. Every other report test
asserts a substring or a heading's presence/absence; none pin the
assembled entry exactly, so a refactor of the composition itself --
reordering, an extra blank line, a dropped separator -- could pass every
existing test while still changing what a reader sees. This test exercises
all nine optional subsections on one hypothesis (including both the
dict-with-url and bare-string evidence-span shapes
``_render_evidence_span`` renders differently) and pins the exact
line-by-line output.
"""

import json

from app import report_markdown
from app.report_markdown_hypothesis import _HYPOTHESIS_DISCLAIMER


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
            "reviewer_agent": "full_review",
            "detail_json": json.dumps(
                {
                    "go_no_go": "Go — pursue wet-lab validation.",
                    "time_to_verdict": "2-4 weeks",
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

    lines = report_markdown._render_hypothesis_entry(
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
        "**Verdict:** Go — pursue wet-lab validation.",
        "",
        "**Time to Verdict:** 2-4 weeks",
        "",
        "#### Simulation review",
        "",
        "1. **Failure point:** Off-target editing risk.",
        "",
        "**Decisive step:** Step 3: enzyme binds substrate.",
        "",
        "**Claim evidence:**",
        "",
        "- **Supported · fundamental** — The product inhibits the enzyme.",
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

    lines = report_markdown._render_hypothesis_entry(2, hyp, [], [], [])

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

    lines = report_markdown._render_hypothesis_entry(3, hyp, [], [], [])

    assert lines[0] == (
        "### 3. **Co-Scientist - Rate-limiting feedback.**  _Elo: _"
    )


def test_hypothesis_title_falls_back_to_untitled_when_absent() -> None:
    """A hypothesis with neither ``title`` nor ``text`` still renders safely.

    Covers the json_object downgrade: a required field can simply be
    missing, and ``hypothesis_title`` degrades to "Untitled" rather than
    raising.
    """
    lines = report_markdown._render_hypothesis_entry(
        1, {"id": "h4"}, [], [], []
    )

    assert lines[0] == "### 1. **Co-Scientist - Untitled**  _Elo: _"
