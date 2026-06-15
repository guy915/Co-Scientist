# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the structured citation utilities.

These tests lock in the *current* behavior of the citation-resolution helpers
in ``co_scientist.nodes.generation.citations`` - ``resolve_citation_keys``,
``build_reference_index``, and ``ReferenceIndex`` - as a regression net for
upcoming refactors. They exercise only pure functions: no LLM or network calls
are involved, so no mocking is required.

Note: the four-state citation classifier the UI surfaces
(verified/partial/unsupported/unavailable) lives in the *app* package
(``app/app/citations.py``), not in the engine, and is covered by the app's own
test suite. The engine's citation module is concerned solely with parsing
``[C*]`` keys and building the reference index, which is what these tests cover.
"""

from co_scientist.models import Article
from co_scientist.nodes.generation.citations import build_reference_index
from co_scientist.nodes.generation.citations import ReferenceIndex
from co_scientist.nodes.generation.citations import resolve_citation_keys


def _used_article(title="Title", authors=None, year=2023, url="") -> Article:
    """Build an Article flagged for analysis (the only kind indexed)."""
    return Article(
        title=title,
        authors=authors if authors is not None else ["Jane Q. Smith"],
        year=year,
        url=url,
        used_in_analysis=True,
    )


# --- resolve_citation_keys: happy path -------------------------------------


def test_resolve_single_existing_key():
    """A single ``[C*]`` key present in sources resolves to its metadata."""
    sources = {"C1": {"type": "paper", "title": "A"}}
    result = resolve_citation_keys("Grounded in [C1].", sources)
    assert result == {"C1": {"type": "paper", "title": "A"}}


def test_resolve_returns_same_dict_object():
    """Resolved value is the exact source dict (not a copy)."""
    payload = {"type": "paper", "title": "A"}
    sources = {"C1": payload}
    result = resolve_citation_keys("see [C1]", sources)
    assert result["C1"] is payload


def test_resolve_multiple_keys():
    """Multiple distinct keys all resolve."""
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("[C1] and [C2]", sources)
    assert set(result) == {"C1", "C2"}


def test_resolve_multi_digit_key():
    """Multi-digit keys such as ``[C10]`` resolve correctly."""
    sources = {"C10": {"title": "ten"}, "C1": {"title": "one"}}
    result = resolve_citation_keys("[C10] then [C1]", sources)
    assert list(result) == ["C10", "C1"]


# --- resolve_citation_keys: unresolved / missing handling ------------------


def test_resolve_missing_key_silently_dropped():
    """A key in the text but absent from sources is silently dropped."""
    sources = {"C1": {"title": "A"}}
    result = resolve_citation_keys("cite [C99] and [C1]", sources)
    assert list(result) == ["C1"]


def test_resolve_all_keys_missing_returns_empty():
    """When no cited key exists in sources, the result is empty."""
    sources = {"C1": {"title": "A"}}
    result = resolve_citation_keys("[C7] [C8]", sources)
    assert result == {}


# --- resolve_citation_keys: ordering and duplicates ------------------------


def test_resolve_preserves_first_occurrence_order():
    """Keys are returned in first-occurrence order, not source order."""
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("uses [C2] then [C1]", sources)
    assert list(result) == ["C2", "C1"]


def test_resolve_deduplicates_repeated_keys():
    """A key cited more than once appears exactly once in the result."""
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("[C2] ... [C1] ... [C2]", sources)
    assert list(result) == ["C2", "C1"]


# --- resolve_citation_keys: guards -----------------------------------------


def test_resolve_none_grounding_returns_empty():
    """``None`` grounding short-circuits to an empty map."""
    assert resolve_citation_keys(None, {"C1": {"title": "A"}}) == {}


def test_resolve_empty_grounding_returns_empty():
    """Empty-string grounding short-circuits to an empty map."""
    assert resolve_citation_keys("", {"C1": {"title": "A"}}) == {}


def test_resolve_empty_sources_returns_empty():
    """Empty sources short-circuit to an empty map even with cited keys."""
    assert resolve_citation_keys("[C1]", {}) == {}


# --- resolve_citation_keys: malformed keys ---------------------------------
# The matching regex is ``\[C\d+\]`` - uppercase C, one-or-more digits, with
# the brackets immediately abutting. The following must NOT match.


def test_resolve_lowercase_key_not_matched():
    """``[c1]`` (lowercase c) is not a valid key."""
    assert resolve_citation_keys("[c1]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_without_digit_not_matched():
    """``[C]`` (no digit) is not a valid key."""
    assert resolve_citation_keys("[C]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_with_trailing_char_not_matched():
    """``[C1x]`` (trailing non-digit before ``]``) is not a valid key."""
    assert resolve_citation_keys("[C1x]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_with_inner_space_not_matched():
    """``[ C1]`` and ``[C 1]`` (whitespace inside brackets) are not valid."""
    assert resolve_citation_keys("[ C1]", {"C1": {"title": "A"}}) == {}
    assert resolve_citation_keys("[C 1]", {"C1": {"title": "A"}}) == {}


def test_resolve_unbracketed_key_not_matched():
    """A bare ``C1`` without brackets is not a valid key."""
    assert resolve_citation_keys("C1", {"C1": {"title": "A"}}) == {}


def test_resolve_double_c_key_not_matched():
    """``[CC1]`` (double C) is not a valid key."""
    assert resolve_citation_keys("[CC1]", {"C1": {"title": "A"}}) == {}


# --- ReferenceIndex --------------------------------------------------------


def test_reference_index_is_empty_true_when_no_sources():
    """``is_empty`` is True when the sources dict is empty."""
    assert ReferenceIndex(text="").is_empty() is True


def test_reference_index_is_empty_false_with_sources():
    """``is_empty`` is False when at least one source is present."""
    idx = ReferenceIndex(text="[C1] foo", sources={"C1": {"title": "A"}})
    assert idx.is_empty() is False


# --- build_reference_index: basic shape ------------------------------------


def test_build_index_paper_label_with_year():
    """A paper with authors and a year uses the ``Last et al., YEAR`` label."""
    idx = build_reference_index([_used_article(title="T")], None)
    assert idx.text == "[C1] Smith et al., 2023 — T"
    assert idx.sources == {
        "C1": {
            "type": "paper",
            "title": "T",
            "url": "",
            "authors": ["Jane Q. Smith"],
            "year": 2023,
        }
    }


def test_build_index_first_author_is_last_token():
    """The label author is the last whitespace-delimited token of authors[0]."""
    art = _used_article(title="T", authors=["Mary van der Berg"])
    idx = build_reference_index([art], None)
    assert idx.text == "[C1] Berg et al., 2023 — T"


def test_build_index_no_authors_uses_unknown():
    """With no authors, the label author falls back to ``Unknown``."""
    art = _used_article(title="T", authors=[], year=2020)
    idx = build_reference_index([art], None)
    assert idx.text == "[C1] Unknown et al., 2020 — T"


def test_build_index_no_year_label_falls_back_to_title():
    """Without a year, the label uses the first 50 characters of the title."""
    long_title = "A very long title that exceeds fifty chars for the fallback"
    art = _used_article(title=long_title, authors=["Bob Lee"], year=None)
    idx = build_reference_index([art], None)
    assert idx.text == f"[C1] {long_title[:50]} — {long_title[:80]}"


# --- build_reference_index: used_in_analysis filtering ---------------------


def test_build_index_skips_unused_articles():
    """Articles without ``used_in_analysis`` are excluded and not numbered."""
    skip = Article(title="Skip",
                   authors=["A B"],
                   year=2000,
                   used_in_analysis=False)
    use = _used_article(title="Use", authors=["C D"], year=2001)
    idx = build_reference_index([skip, use], None)
    assert list(idx.sources) == ["C1"]
    assert idx.sources["C1"]["title"] == "Use"


# --- build_reference_index: shared key namespace ---------------------------


def test_build_index_papers_numbered_before_enrichment():
    """Papers occupy the leading keys; enrichment sources follow in one space."""
    art = _used_article(title="Use", authors=["C D"], year=2001)
    enrichment = [{
        "display": "INDRA: KRAS -> RAF1",
        "tool_id": "indra",
        "data": {
            "belief": 0.9
        },
    }]
    idx = build_reference_index([art], enrichment)
    assert list(idx.sources) == ["C1", "C2"]
    assert idx.sources["C1"]["type"] == "paper"
    assert idx.sources["C2"] == {
        "type": "knowledge_graph",
        "display": "INDRA: KRAS -> RAF1",
        "tool_id": "indra",
        "data": {
            "belief": 0.9
        },
    }


def test_build_index_enrichment_display_defaults():
    """An enrichment item missing fields gets default display and empty data."""
    idx = build_reference_index(None, [{}])
    assert idx.text == "[C1] External source"
    assert idx.sources["C1"] == {
        "type": "knowledge_graph",
        "display": "External source",
        "tool_id": "",
        "data": {},
    }


# --- build_reference_index: empty inputs -----------------------------------


def test_build_index_none_inputs_is_empty():
    """Passing ``None`` for both inputs yields an empty index."""
    idx = build_reference_index(None, None)
    assert idx.text == ""
    assert idx.sources == {}
    assert idx.is_empty() is True


def test_build_index_empty_lists_is_empty():
    """Passing empty lists for both inputs yields an empty index."""
    idx = build_reference_index([], [])
    assert idx.is_empty() is True


# --- round-trip contract ---------------------------------------------------


def test_round_trip_build_then_resolve():
    """Keys produced by build_reference_index resolve back to their sources."""
    art = _used_article(title="Use", authors=["C D"], year=2001)
    enrichment = [{"display": "KG fact", "tool_id": "indra", "data": {}}]
    idx = build_reference_index([art], enrichment)
    grounding = "Supported by [C1] and [C2]."
    resolved = resolve_citation_keys(grounding, idx.sources)
    assert list(resolved) == ["C1", "C2"]
    assert resolved["C1"] is idx.sources["C1"]
    assert resolved["C2"] is idx.sources["C2"]
