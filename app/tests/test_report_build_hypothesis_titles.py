"""R14-6: report.build resolves the run's hypothesis-title lookup.

``_hypothesis_title_by_id`` builds the id -> title map
``ReportMarkdownInputs.hypothesis_title_by_id`` needs to resolve a
research-contact-group's example hypotheses (see
``test_report_contact_groups.py`` for the renderer side). Built from the
whole published pool, not the 5-item report slice, since the engine's
synthesis draws examples from up to ``RESEARCH_OVERVIEW_TOP_K`` (10).
"""

from app.report.build import _hypothesis_title_by_id


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
