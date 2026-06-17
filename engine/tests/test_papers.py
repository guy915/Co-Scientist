"""Tests for the pure paper-grounding helpers in nodes/generation/papers.py.

These functions perform no LLM or network calls: they convert article and
novelty-analysis metadata into candidate dicts and match author-year citations
against literature-grounding text. The tests assert the candidate dict shape,
the ``used_in_analysis`` / ``paper_id`` gates, and the decoupled
(author-last-name AND year) substring match precisely.
"""

from typing import Any

from co_scientist.nodes.generation.papers import analyses_to_candidates
from co_scientist.nodes.generation.papers import articles_to_candidates
from co_scientist.nodes.generation.papers import filter_papers_by_grounding
from tests._state import make_article


# --- articles_to_candidates -------------------------------------------------
def test_articles_to_candidates_builds_expected_dict() -> None:
    """A used article becomes a candidate dict with title/url/authors/year."""
    article = make_article(
        title="Tumor pathway analysis",
        url="https://example.org/paper1",
        authors=["A. Roepert", "B. Carter"],
        year=2020,
        used_in_analysis=True,
    )
    result = articles_to_candidates([article])
    assert result == [{
        "title": "Tumor pathway analysis",
        "url": "https://example.org/paper1",
        "authors": ["A. Roepert", "B. Carter"],
        "year": 2020,
    }]


def test_articles_to_candidates_skips_unused_articles() -> None:
    """Only articles flagged used_in_analysis are converted; others drop out."""
    used = make_article(title="Used", authors=["X. Smith"], year=2020,
                        used_in_analysis=True)
    unused = make_article(title="Unused", authors=["Y. Jones"], year=2021,
                          used_in_analysis=False)
    result = articles_to_candidates([used, unused])
    assert [c["title"] for c in result] == ["Used"]


def test_articles_to_candidates_default_used_flag_excludes() -> None:
    """The used_in_analysis flag defaults to False, so an unflagged article."""
    article = make_article(title="No flag", authors=["A. Roepert"], year=2020)
    assert articles_to_candidates([article]) == []


def test_articles_to_candidates_none_url_becomes_empty_string() -> None:
    """A None url falls back to an empty string in the candidate dict."""
    article = make_article(title="No url", url=None, authors=["A. Roepert"],
                          year=2020, used_in_analysis=True)
    result = articles_to_candidates([article])
    assert result[0]["url"] == ""


def test_articles_to_candidates_none_and_empty_return_empty() -> None:
    """None or an empty article list yields an empty candidate list."""
    assert articles_to_candidates(None) == []
    assert articles_to_candidates([]) == []


# --- analyses_to_candidates -------------------------------------------------
def test_analyses_to_candidates_builds_expected_dict() -> None:
    """paper_metadata maps to a candidate with url drawn from paper_id."""
    analyses = [{
        "paper_metadata": {
            "paper_id": "PMID:123",
            "title": "Novelty study",
            "authors": ["A. Roepert"],
            "year": 2020,
        }
    }]
    result = analyses_to_candidates(analyses)
    assert result == [{
        "title": "Novelty study",
        "url": "PMID:123",
        "authors": ["A. Roepert"],
        "year": 2020,
    }]


def test_analyses_to_candidates_skips_missing_paper_id() -> None:
    """An analysis with no paper_id is skipped by the truthiness guard."""
    analyses: list[dict[str, Any]] = [
        {"paper_metadata": {"title": "No id", "authors": ["X"], "year": 2020}},
        {"paper_metadata": {"paper_id": "", "title": "Empty id"}},
        {"paper_metadata": {"paper_id": "PMID:9", "title": "Has id"}},
    ]
    result = analyses_to_candidates(analyses)
    assert [c["title"] for c in result] == ["Has id"]


def test_analyses_to_candidates_dedupes_by_paper_id() -> None:
    """Two analyses sharing a paper_id collapse to a single candidate."""
    analyses = [
        {"paper_metadata": {"paper_id": "PMID:5", "title": "First"}},
        {"paper_metadata": {"paper_id": "PMID:5", "title": "Second"}},
    ]
    result = analyses_to_candidates(analyses)
    assert len(result) == 1
    assert result[0]["title"] == "First"
    assert result[0]["url"] == "PMID:5"


def test_analyses_to_candidates_none_and_empty_return_empty() -> None:
    """None or an empty analyses list yields an empty candidate list."""
    assert analyses_to_candidates(None) == []
    assert analyses_to_candidates([]) == []


# --- filter_papers_by_grounding ---------------------------------------------
def _candidate(**overrides: Any) -> dict[str, Any]:
    """Build a candidate dict with the four keys the filter reads."""
    base: dict[str, Any] = {
        "title": "A paper",
        "url": "https://example.org/p",
        "authors": ["A. Roepert"],
        "year": 2020,
    }
    base.update(overrides)
    return base


def test_filter_matches_author_lastname_and_year() -> None:
    """A candidate whose lastname and year both appear is returned."""
    candidates = [_candidate()]
    grounding = "Our reasoning rests on (Roepert et al., 2020)."
    result = filter_papers_by_grounding(candidates, grounding)
    assert result == [{"title": "A paper", "url": "https://example.org/p"}]


def test_filter_excludes_when_year_absent() -> None:
    """The lastname matches but the year does not, so the AND fails."""
    candidates = [_candidate(year=1999)]
    grounding = "Our reasoning rests on (Roepert et al., 2020)."
    assert filter_papers_by_grounding(candidates, grounding) == []


def test_filter_excludes_when_author_absent() -> None:
    """The year matches but no lastname does, so the AND fails."""
    candidates = [_candidate(authors=["X. Smith"])]
    grounding = "Our reasoning rests on (Roepert et al., 2020)."
    assert filter_papers_by_grounding(candidates, grounding) == []


def test_filter_excludes_short_lastname_under_len_guard() -> None:
    """A two-character lastname is ignored even when the year is present."""
    candidates = [_candidate(authors=["Jane Ng"], year=2021)]
    grounding = "As shown in (Ng et al., 2021), the effect holds."
    assert filter_papers_by_grounding(candidates, grounding) == []


def test_filter_skips_candidate_without_authors() -> None:
    """A candidate with an empty authors list is skipped entirely."""
    candidates = [_candidate(authors=[])]
    grounding = "Our reasoning rests on (Roepert et al., 2020)."
    assert filter_papers_by_grounding(candidates, grounding) == []


def test_filter_dedupes_identical_title_and_url() -> None:
    """Two matching candidates with the same (title, url) yield one result."""
    candidates = [_candidate(), _candidate()]
    grounding = "Our reasoning rests on (Roepert et al., 2020)."
    result = filter_papers_by_grounding(candidates, grounding)
    assert result == [{"title": "A paper", "url": "https://example.org/p"}]


def test_filter_returns_only_matching_subset() -> None:
    """Across mixed candidates, only the cited one survives."""
    cited = _candidate(title="Cited", url="u1", authors=["A. Roepert"],
                       year=2020)
    uncited = _candidate(title="Uncited", url="u2", authors=["B. Wexler"],
                         year=2015)
    result = filter_papers_by_grounding([cited, uncited],
                                        "See (Roepert et al., 2020).")
    assert result == [{"title": "Cited", "url": "u1"}]


def test_filter_none_grounding_returns_empty() -> None:
    """None grounding text short-circuits to an empty list."""
    assert filter_papers_by_grounding([_candidate()], None) == []


def test_filter_empty_grounding_returns_empty() -> None:
    """Empty grounding text short-circuits to an empty list."""
    assert filter_papers_by_grounding([_candidate()], "") == []


def test_filter_empty_candidates_returns_empty() -> None:
    """An empty candidate list short-circuits to an empty list."""
    assert filter_papers_by_grounding([], "(Roepert et al., 2020)") == []


def test_filter_matching_is_case_insensitive() -> None:
    """Matching lowercases the grounding, so uppercase citations still match."""
    candidates = [_candidate()]
    grounding = "PER (ROEPERT ET AL., 2020), THE PATHWAY ACTIVATES."
    result = filter_papers_by_grounding(candidates, grounding)
    assert result == [{"title": "A paper", "url": "https://example.org/p"}]
