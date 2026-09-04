"""The reader is told which third-party databases a run queried.

The vendored science skills reach sources whose terms are separate from
the bundle's Apache licence, and most of those sources require the user
be notified of their terms. ``skills/licences.py`` satisfies the literal
condition the skills themselves state -- a file in the workspace -- and
records why that is not enough: the workspace is deleted, so the notice
reaches nobody. The run's report is the surface a person reads, which is
what these pin, along with the two properties that make the notice
honest: it names only the sources actually queried, and it is absent
entirely from a run that queried none.
"""

from typing import Any

from app import report_markdown


def _markdown(skills_used: dict[str, int] | None) -> str:
    """Render a minimal report with the given skill attribution."""
    hypothesis: dict[str, Any] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            skills_used=skills_used,
        )
    )


def test_a_queried_source_is_named_with_its_terms() -> None:
    """A run that used a skill attributes it and points at the terms."""
    markdown = _markdown({"string-database": 2})

    assert "## Data sources" in markdown
    assert "string-database" in markdown
    assert "SKILL_LICENSES.md" in markdown


def test_a_source_the_run_never_touched_is_not_claimed() -> None:
    """Only what the run queried is named, not the whole catalogue.

    A blanket list of every installed skill would be the easy thing to
    render and would attribute the run's work to databases it never
    reached, which is a worse disclosure than none.
    """
    markdown = _markdown({"string-database": 1})

    assert "chembl-database" not in markdown


def test_a_run_without_skills_carries_no_notice() -> None:
    """The section is absent, not empty, when nothing was queried.

    Every run without ``COSCIENTIST_SKILLS_DIR`` is this run, so an
    always-rendered heading would put a data-source section on reports
    that used no data source.
    """
    assert "## Data sources" not in _markdown(None)
    assert "## Data sources" not in _markdown({})
