"""K3: the reader must be told when novelty was not corpus-verified.

``novelty_validation`` is populated only by the engine's tool-calling
generation path (``literature_tools/validate_novelty.py``), which the app
never enables for a real run (``app/app/engine_adapter/opts.py`` builds no
such kwarg). So a Goal Report markdown document must carry an explicit
disclosure that novelty reflects an unverified model judgment whenever no
hypothesis in it carries a corpus-checked result -- which is every real
report today -- and must drop that disclosure the one place a corpus-
checked result is actually present. Silently falling back to definitive
novelty language when verification did not run is the defect this pins.
"""

from app import report_content, report_markdown


def _hypothesis(
    identifier: str, title: str, **extra: object
) -> dict[str, object]:
    """Build one report-ready hypothesis fixture."""
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        **extra,
    }


def test_report_markdown_discloses_unverified_novelty_by_default() -> None:
    """A report with no corpus-checked hypothesis carries the disclosure."""
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
    """A hypothesis carrying a corpus-checked result silences the disclosure.

    Exercises the forward-compatible branch: if a future run threads
    ``novelty_validation`` through, the blanket disclosure must not still
    claim nothing was checked.
    """
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
    """An empty 'Top hypotheses' section carries no novelty commentary."""
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[],
        )
    )
    assert "reviewing model's own judgment" not in markdown


def test_rejected_idea_reason_attributes_non_novelty_to_the_reviewer() -> None:
    """A rejected idea's reason must not assert non-novelty as settled fact.

    The review's novelty score is an unaided model judgment (K3): telling a
    reader an idea "is not novel" states that judgment as fact. The reason
    must attribute it to the review instead.
    """
    rejected = _hypothesis("h1", "Unsound idea", status="rejected")
    reasons = report_content._non_viable_reasons(rejected, {})
    assert len(reasons) == 1
    assert "reviewer judged" in reasons[0]
    assert "not a literature search" in reasons[0]
