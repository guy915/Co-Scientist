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
            "introduction": (
                '{"context": "Targets tolerance", "scope": "in vitro"}'
            ),
            "aims": [
                {
                    "aim": "Aim 1: Delete relA",
                    "rationale": {"why": "Guards against artefacts"},
                    "approach": "Static and flow-cell assays.",
                }
            ],
            "impact": "Converts the lead hypothesis into a research program.",
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
