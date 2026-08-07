"""Unit tests for prompts._common._format_meta_review_context (I2).

Every generation strategy, plus review/ranking/proximity/safety/
literature-review, splices this one function's output into its prompt
(see the module docstring of ``prompts/_common.py``), so a field it
drops never reaches any downstream surface no matter how many callers
pass it through ``PromptRunContext``. These tests pin the two fields
that make the run's own synthesis carry "what's already covered" /
"what's still open" forward, per fidelity audit finding I2.
"""

from co_scientist.prompts._common import _format_meta_review_context


def test_emerging_themes_render_as_covered_areas() -> None:
    """Recurring themes render under an explicit already-covered header."""
    prompt = _format_meta_review_context(
        {"emerging_themes": ["mitochondrial dysfunction pathway"]}
    )
    assert "Research Areas Already Covered" in prompt
    assert "mitochondrial dysfunction pathway" in prompt


def test_emerging_themes_absent_when_empty() -> None:
    """No themes -> no covered-areas header, and no empty section either."""
    prompt = _format_meta_review_context({"common_strengths": ["x"]})
    assert "Research Areas Already Covered" not in prompt


def test_potential_connections_render_as_open_directions() -> None:
    """Potential connections render under an open-directions header."""
    prompt = _format_meta_review_context(
        {
            "potential_connections": [
                {
                    "connection_type": "complementary_mechanism",
                    "synthesis_opportunity": (
                        "combine autophagy and proteasome targeting"
                    ),
                }
            ]
        }
    )
    assert "Open Directions Flagged for Further Exploration" in prompt
    assert "complementary_mechanism" in prompt
    assert "combine autophagy and proteasome targeting" in prompt


def test_potential_connections_absent_when_empty() -> None:
    """No connections -> no open-directions header."""
    prompt = _format_meta_review_context({"common_strengths": ["x"]})
    assert "Open Directions Flagged for Further Exploration" not in prompt


def test_potential_connection_tolerates_partial_fields() -> None:
    """A connection missing one of the two prose fields still renders."""
    prompt = _format_meta_review_context(
        {
            "potential_connections": [
                {"synthesis_opportunity": "only an opportunity, no type"}
            ]
        }
    )
    assert "only an opportunity, no type" in prompt


def test_potential_connection_tolerates_non_dict_entries() -> None:
    """A model ignoring the schema and returning bare strings still renders."""
    prompt = _format_meta_review_context(
        {"potential_connections": ["a bare string connection"]}
    )
    assert "a bare string connection" in prompt


def test_no_meta_review_renders_nothing() -> None:
    """Absent meta-review still yields the byte-clean empty string."""
    assert _format_meta_review_context(None) == ""
    assert _format_meta_review_context({}) == ""
