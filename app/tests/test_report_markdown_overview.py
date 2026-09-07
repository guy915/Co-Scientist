"""Tests for research-overview markdown coercion.

Research-overview fields are produced by the model in json_object mode with no
server-side schema enforcement, so a string field can arrive as a dict, or as
a string that is itself serialized JSON. These tests pin that such shapes are
flattened into readable text rather than leaking raw JSON into the report.
"""

from typing import Any

from app.report_markdown_overview import render_research_overview_markdown


def _markdown(payload: dict[str, Any]) -> str:
    """Render the overview payload to a single markdown string."""
    return "\n".join(render_research_overview_markdown(payload))


def test_json_string_importance_is_flattened() -> None:
    """An importance field that arrived as serialized JSON is flattened."""
    payload = {
        "overview": {
            "summary": "A coherent program emerges.",
            "research_directions": [
                {
                    "title": "Validate in an orthogonal model",
                    "importance": (
                        '{"significance": "Guards against artefacts", '
                        '"gap": "None known"}'
                    ),
                    "suggested_experiments": ["Run a perturbation series."],
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "Guards against artefacts - None known" in text
    assert '{"significance"' not in text
    assert "Run a perturbation series." in text


def test_object_and_json_array_experiments_are_flattened() -> None:
    """Experiments arriving as objects or a JSON-array string are flattened."""
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Probe pathway redundancy",
                    "importance": "Determines whether routes compensate.",
                    "suggested_experiments": [
                        {"experiment": "Delete relA", "rationale": "tolerance"}
                    ],
                },
                {
                    "title": "Establish causality",
                    "importance": "Confirms the shared assumption.",
                    "suggested_experiments": '["Assay A", "Assay B"]',
                },
            ],
        }
    }

    text = _markdown(payload)

    assert "- Delete relA - tolerance" in text
    assert "- Assay A" in text and "- Assay B" in text
    assert '{"experiment"' not in text
    assert '["Assay A"' not in text


def test_malformed_aims_and_contacts_are_flattened() -> None:
    """NIH aims and research contacts flatten object/JSON-string fields too."""
    payload = {
        "nih_specific_aims": {
            "disease_description": (
                '{"context": "Targets tolerance", "scope": "in vitro"}'
            ),
            "aims": [
                {
                    "overarching_goal": "Aim 1: Delete relA",
                    "hypothesis": {"why": "Guards against artefacts"},
                    "reasoning": "Static and flow-cell assays.",
                }
            ],
            "pilot_evaluation": (
                "Converts the lead hypothesis into a research program."
            ),
        },
        "research_contacts": [
            {
                "name": "Ada Researcher",
                "expertise": '{"field": "Biofilm metabolism"}',
                "justification": "Authored an analyzed paper.",
                "source_title": "A biofilm study",
                "source_url": "https://example.org/paper",
            }
        ],
    }

    text = _markdown(payload)

    assert "Targets tolerance - in vitro" in text
    assert "Guards against artefacts" in text
    assert "Biofilm metabolism" in text
    assert '{"context"' not in text
    assert '{"field"' not in text
    assert '{"why"' not in text
    # A real URL is preserved verbatim, not flattened.
    assert "https://example.org/paper" in text


def test_well_formed_overview_is_unchanged() -> None:
    """A clean overview renders without alteration."""
    payload = {
        "overview": {
            "summary": "Top hypotheses converge on cross-pathway interference.",
            "research_directions": [
                {
                    "title": "Validate in an orthogonal model",
                    "importance": "Guards against assay-specific artefacts.",
                    "suggested_experiments": [
                        "Run a controlled perturbation series.",
                        "Quantify the readout against baseline.",
                    ],
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "Guards against assay-specific artefacts." in text
    assert "- Run a controlled perturbation series." in text
    assert "- Quantify the readout against baseline." in text
    assert "converge on cross-pathway interference" in text


def test_sub_topics_render() -> None:
    """MO-1: a direction's nested sub-topics render.

    Mirrors the published exemplars' nested "Areas of Research" /
    "What to Research in This Area?" layer, one level below the
    direction: a named sub-topic with its own why/what/specific
    questions.
    """
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                    "suggested_experiments": ["Profile ROS in patient iPSCs."],
                    "sub_topics": [
                        {
                            "title": "Mitochondrial DNA repair defects",
                            "why": "A deficiency could be a primary driver.",
                            "what": "Assay BER activity in iPSC neurons.",
                            "example_idea": "Knock down OGG1 in iPSC neurons.",
                            "specific_questions": [
                                "Does OGG1 activity correlate with damage?",
                                "Does release activate cGAS-STING?",
                            ],
                        }
                    ],
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "#### Mitochondrial DNA repair defects" in text
    assert "A deficiency could be a primary driver." in text
    assert "Assay BER activity in iPSC neurons." in text
    assert "**Example idea:** Knock down OGG1 in iPSC neurons." in text
    assert "- Does OGG1 activity correlate with damage?" in text
    assert "- Does release activate cGAS-STING?" in text


def test_malformed_sub_topics_are_flattened() -> None:
    """A sub-topic arriving as JSON-string or malformed fields still render.

    Stored/persisted overviews may predate this schema or arrive from a
    model in json_object mode, so the renderer -- not the engine -- is
    the backstop: this must never raise, matching the existing
    tolerance for importance/suggested_experiments.
    """
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Direction",
                    "importance": "I",
                    "suggested_experiments": ["E"],
                    "sub_topics": [
                        {
                            "title": "Sub-topic",
                            "why": '["stress", "damage"]',
                            "what": "Investigate.",
                            "specific_questions": "not a list",
                        },
                        "not a dict",
                    ],
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "stress damage" in text
    assert '["stress"' not in text
    assert "#### Sub-topic" in text


def test_recent_findings_renders() -> None:
    """MO-12: a direction's recent_findings paragraph renders.

    ALS's "Recent Findings" is the "what is already known" slot our
    schema restores alongside the cf-PICI Why/What pair we already mirror.
    """
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                    "recent_findings": (
                        "mtDNA repair defects are already implicated."
                    ),
                    "suggested_experiments": ["Profile ROS in patient iPSCs."],
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "mtDNA repair defects are already implicated." in text


def test_malformed_recent_findings_is_flattened() -> None:
    """A recent_findings field arriving as a dict still renders as text."""
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Direction",
                    "importance": "I",
                    "recent_findings": {"gap": "None known"},
                    "suggested_experiments": ["E"],
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "None known" in text
    assert '{"gap"' not in text


def test_two_or_more_directions_get_a_preview_list() -> None:
    """MO-12: 2+ directions front-load a named preview before the detail.

    Both published exemplars (ALS, cf-PICI) open with a compact list
    naming every direction before the full per-direction detail. The
    preview must name every direction and precede the first full
    ``### {title}`` detail heading.
    """
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                },
                {
                    "title": "RNA processing defects",
                    "importance": "Implicated across ALS subtypes.",
                },
            ],
        }
    }

    text = _markdown(payload)

    assert "We will be focusing on these research directions:" in text
    assert "- Mitochondrial dysfunction" in text
    assert "- RNA processing defects" in text
    preview_at = text.index("We will be focusing")
    detail_at = text.index("### Mitochondrial dysfunction")
    assert preview_at < detail_at


def test_a_single_direction_gets_no_preview_list() -> None:
    """One direction is not previewed -- naming it twice just repeats it."""
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                }
            ],
        }
    }

    text = _markdown(payload)

    assert "We will be focusing on these research directions:" not in text
    assert "### Mitochondrial dysfunction" in text


def test_an_untitled_direction_is_dropped_from_the_preview_count() -> None:
    """A malformed/untitled direction does not count toward the preview."""
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {"title": "Mitochondrial dysfunction", "importance": "I"},
                {"title": "", "importance": "No name given"},
                "not a dict",
            ],
        }
    }

    text = _markdown(payload)

    # Only one named direction -- same as the single-direction case.
    assert "We will be focusing on these research directions:" not in text
    assert "### Mitochondrial dysfunction" in text


def test_published_aims_vocabulary_renders_every_block() -> None:
    """The aims page renders the blocks Google's exemplars print."""
    payload = {
        "nih_specific_aims": {
            "disease_description": "An aggressive malignancy.",
            "unmet_need": "Current therapies relapse.",
            "proposed_solution": "Repurpose an approved inhibitor.",
            "aims": [
                {
                    "overarching_goal": "Determine anti-tumour activity.",
                    "hypothesis": "Treatment reduces viability.",
                    "reasoning": "The pathway is upregulated.",
                }
            ],
            "pilot_evaluation": "A xenograft study measures tumour growth.",
        }
    }

    text = _markdown(payload)

    assert "### Disease Description" in text
    assert "### Unmet Need" in text
    assert "### Proposed Solution" in text
    assert "### Specific Aims 1" in text
    assert "**Overarching goal:** Determine anti-tumour activity." in text
    assert "**Hypothesis:** Treatment reduces viability." in text
    assert "**Reasoning:** The pathway is upregulated." in text
    assert "### Pilot Evaluation" in text


def test_stored_reports_in_the_previous_aims_shape_still_render() -> None:
    """A report written before the exemplar vocabulary keeps its aims page.

    Reports are persisted as the engine produced them, so runs that predate
    the schema change still carry introduction/aim/rationale/approach/impact.
    Rendering must not silently drop their Specific Aims section.
    """
    payload = {
        "nih_specific_aims": {
            "introduction": "Significance and the gap.",
            "aims": [
                {
                    "aim": "Aim 1: Establish the baseline.",
                    "rationale": "Nothing else measures it.",
                    "approach": "Knockdown in a matched model.",
                }
            ],
            "impact": "A decision framework for the mechanism.",
        }
    }

    text = _markdown(payload)

    assert "## NIH Specific Aims" in text
    assert "Significance and the gap." in text
    assert "### Specific Aims 1" in text
    assert "**Aim:** Aim 1: Establish the baseline." in text
    assert "**Rationale:** Nothing else measures it." in text
    assert "**Approach:** Knockdown in a matched model." in text
    assert "### Impact" in text
