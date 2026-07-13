"""PubMed corpus selection tests."""

from pathlib import Path

from mcp_server.literature_review import PubmedSource


def test_final_results_fill_fulltext_shortfall_with_abstracts(
    tmp_path: Path,
) -> None:
    """PMC papers lead, while abstract-only records fill the corpus target."""
    source = PubmedSource(tmp_path)
    metadata = {
        "abstract-1": {"title": "Recent abstract", "abstract": "A1"},
        "fulltext-1": {
            "title": "Open paper",
            "abstract": "A2",
            "fulltext": "Complete article",
        },
        "abstract-2": {"title": "Older abstract", "abstract": "A3"},
    }

    result = source._assemble_final_results(
        ["fulltext-1"], metadata, max_papers=3
    )

    assert list(result) == ["fulltext-1", "abstract-1", "abstract-2"]
    assert len(result) == 3


def test_final_results_respect_total_corpus_limit(tmp_path: Path) -> None:
    """The abstract fallback never expands beyond the requested paper count."""
    source = PubmedSource(tmp_path)
    metadata = {
        "fulltext-1": {"fulltext": "One"},
        "fulltext-2": {"fulltext": "Two"},
        "abstract-1": {"abstract": "Three"},
    }

    result = source._assemble_final_results(
        ["fulltext-1", "fulltext-2"], metadata, max_papers=2
    )

    assert list(result) == ["fulltext-1", "fulltext-2"]
