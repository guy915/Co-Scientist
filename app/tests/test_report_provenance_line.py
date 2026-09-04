"""R12-20: the report header carries a provenance and caution line.

Google's published report carries this line right after its Research Goal
Details block: "Prepared by AI co-scientist on 2026-06-12. For research
purposes only." (MASH report L41, ``docs/CORPUS-EXTRACTION.md`` R12-20).
Our header emitted no date, no system attribution, and no caution -- grep
for "For research purposes only" across the app returned zero hits. This
pins that the line now renders, naming this system rather than Google's.
"""

import datetime

from app import report_markdown


def _markdown(prepared_at: float | None) -> str:
    """Render a minimal report carrying only the given prepared_at."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            prepared_at=prepared_at,
        )
    )


def test_the_header_carries_the_research_purposes_only_caution() -> None:
    """The caution line renders verbatim."""
    markdown = _markdown(1_700_000_000.0)

    assert "For research purposes only." in markdown


def test_the_header_names_this_system_not_googles() -> None:
    """Provenance is attributed to this system, never "AI co-scientist"."""
    markdown = _markdown(1_700_000_000.0)

    assert "Prepared by Co-Scientist on" in markdown
    assert "AI co-scientist" not in markdown


def test_the_date_is_derived_from_prepared_at_not_wall_clock() -> None:
    """The rendered date matches the supplied timestamp, not datetime.now()."""
    timestamp = 1_700_000_000.0
    expected = (
        datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        .date()
        .isoformat()
    )

    markdown = _markdown(timestamp)

    assert expected in markdown


def test_no_prepared_at_renders_no_provenance_line() -> None:
    """A report with no known preparation time carries no caution line.

    Covers a report persisted before this field existed rather than
    stating a date this system does not actually know. Checks the
    provenance line's own wording, not the bare "For research purposes
    only" phrase -- the R14-4 About disclosure (report_markdown_header.py)
    carries that same closing phrase unconditionally, on every render.
    """
    markdown = _markdown(None)

    assert "Prepared by" not in markdown
