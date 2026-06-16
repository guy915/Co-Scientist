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
"""Tests for literature_review_node orchestration and in-file helpers.

The leaf helpers in ``literature_review_helpers`` are covered separately by
``test_literature_review_helpers``; here we exercise the node's orchestration
and the pure functions defined in ``literature_review.py`` itself.

External seams stubbed (all bound on the ``literature_review`` module
namespace):

* ``get_node_cache`` -> a no-op cache (always miss / no-op set), so the global
  on-disk node cache never interferes and tests stay deterministic.
* ``check_literature_source_available`` -> bool, the MCP-gate the node consults
  before doing any work; ``False`` drives the unavailable fallback, ``True`` the
  happy path (without it the node would dial ``localhost:8888``).
* ``get_mcp_client`` -> a fake whose ``call_tool`` returns canned search papers,
  standing in for the real MCP search/tool path.
* ``call_llm_json`` -> shared by query-generation (returns ``queries``) and
  per-paper analysis (the dict is stored opaquely and fed to synthesis).
* ``call_llm`` -> phase-4 synthesis text.
* ``save_prompt_to_disk`` -> no-op (its node-local binding is NOT covered by the
  autouse conftest fixture, which patches a different binding).

With ``tool_registry=None`` the multi-source/PDF-discovery/content-fetch/
context-enrichment phases (2.4/2.5/2.6) all early-return, so the node runs in
its real single-source, LLM-only orchestration.
"""

from typing import Any

import pytest

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.nodes import literature_review as lr
from co_scientist.nodes.literature_review import literature_review_node
from tests._state import make_state


class _NoOpNodeCache:
    """A node cache that never hits and never writes.

    Substituted for the global on-disk ``NodeCache`` so orchestration tests
    neither read stale results nor leave pickles behind.
    """

    def get(self, *_: Any, **__: Any) -> None:
        """Always miss."""
        return None

    def set(self, *_: Any, **__: Any) -> None:
        """No-op store."""
        return None


class _FakeMCPClient:
    """Minimal stand-in for ``MCPToolClient`` used by the node.

    ``call_tool`` returns a fixed payload regardless of tool name/args; the node
    only uses it for searching here (query generation falls back to the stubbed
    LLM, and the no-registry path disables every other tool phase).
    """

    def __init__(self, search_payload: dict[str, dict[str, Any]]) -> None:
        """Store the dict that every ``call_tool`` invocation returns.

        Args:
            search_payload: The ``{paper_id: metadata}`` dict returned for any
                tool call (passed through unchanged by ``normalize_search_
                response`` when there is no tool config).
        """
        self._search_payload = search_payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the canned search payload."""
        self.calls.append((tool_name, kwargs))
        return self._search_payload

    def has_tool(self, _tool_name: str) -> bool:
        """No enrichment tools are exposed by the fake client."""
        return False


def _stub_node(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_available: bool,
    search_payload: dict[str, dict[str, Any]] | None = None,
    queries: list[str] | None = None,
    synthesis: str = "SYNTHESIZED REVIEW",
) -> _FakeMCPClient:
    """Patch every external seam of ``literature_review_node``.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        source_available: Value returned by ``check_literature_source_
            available``.
        search_payload: ``{paper_id: metadata}`` the fake MCP client returns
            from ``call_tool``.
        queries: Queries returned by the stubbed query-generation LLM. Defaults
            to a single query.
        synthesis: Text returned by the stubbed synthesis ``call_llm``.

    Returns:
        The ``_FakeMCPClient`` instance wired into the node (so the test can
        inspect ``.calls``).
    """
    fake_client = _FakeMCPClient(search_payload or {})

    monkeypatch.setattr(lr, "get_node_cache", lambda: _NoOpNodeCache())
    monkeypatch.setattr(lr, "save_prompt_to_disk", lambda **_: None)

    async def fake_available(**_: Any) -> bool:
        return source_available

    monkeypatch.setattr(lr, "check_literature_source_available", fake_available)

    async def fake_get_client(**_: Any) -> _FakeMCPClient:
        return fake_client

    monkeypatch.setattr(lr, "get_mcp_client", fake_get_client)

    async def fake_llm_json(**_: Any) -> dict[str, Any]:
        # Shared by query-generation (reads "queries") and paper analysis
        # (stores the whole dict opaquely for synthesis).
        return {"queries": queries if queries is not None else ["query one"]}

    monkeypatch.setattr(lr, "call_llm_json", fake_llm_json)

    async def fake_llm(**_: Any) -> str:
        return synthesis

    monkeypatch.setattr(lr, "call_llm", fake_llm)

    return fake_client


# =============================================================================
# No-MCP / source-unavailable fallback
# =============================================================================


async def test_source_unavailable_returns_failure_without_search(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """When the literature source is unavailable the node fails fast.

    It returns the documented failure result (``articles_with_reasoning`` set to
    the failure sentinel, empty queries/articles) and never touches the MCP
    search client.
    """
    fake_client = _stub_node(monkeypatch, source_available=False)
    state = make_state(research_goal="cancer immunotherapy resistance")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == []
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True
    # The search seam was never reached.
    assert fake_client.calls == []


# =============================================================================
# Happy path
# =============================================================================


async def test_happy_path_populates_synthesis_and_articles(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A full single-source run yields synthesis, queries and Article objects.

    Two papers (both with ``fulltext``) are returned by the stubbed search, the
    query LLM yields two queries, the per-paper analysis LLM is stubbed, and the
    synthesis LLM returns canned text that lands in ``articles_with_reasoning``.
    """
    papers = {
        "PMID1": {
            "title": "Tumor microenvironment review",
            "authors": ["Smith J"],
            "year": "2021",
            "fulltext": "Full body one.",
            "abstract": "Abstract one.",
        },
        "PMID2": {
            "title": "Immune checkpoint blockade",
            "authors": ["Doe A"],
            "year": "2022",
            "fulltext": "Full body two.",
            "abstract": "Abstract two.",
        },
    }
    _stub_node(
        monkeypatch,
        source_available=True,
        search_payload=papers,
        queries=["query alpha", "query beta"],
        synthesis="SYNTHESIZED REVIEW",
    )
    state = make_state(research_goal="immune checkpoint resistance")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == "SYNTHESIZED REVIEW"
    # Queries are capped at 3; both stubbed queries survive.
    assert result["literature_review_queries"] == ["query alpha", "query beta"]
    # One Article per collected paper.
    articles = result["articles"]
    assert len(articles) == 2
    assert {a.source_id for a in articles} == {"PMID1", "PMID2"}
    assert {a.title for a in articles} == {
        "Tumor microenvironment review",
        "Immune checkpoint blockade",
    }
    # The success message records the counts.
    assert result["messages"][0]["metadata"]["phase"] == "literature_review"
    assert "error" not in result["messages"][0]["metadata"]


async def test_happy_path_falls_back_to_research_goal_query(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty query LLM response falls back to the research goal as a query.

    ``_phase1_generate_queries`` uses ``[research_goal]`` when neither the MCP
    nor the LLM path produces queries.
    """
    papers = {
        "PMID9": {
            "title": "Single paper",
            "fulltext": "Body text.",
        },
    }
    _stub_node(
        monkeypatch,
        source_available=True,
        search_payload=papers,
        queries=[],  # forces the research-goal fallback
        synthesis="REVIEW",
    )
    state = make_state(research_goal="rare query fallback goal")

    result = await literature_review_node(state)

    assert result["literature_review_queries"] == ["rare query fallback goal"]
    assert result["articles_with_reasoning"] == "REVIEW"
    assert len(result["articles"]) == 1


# =============================================================================
# Edge cases
# =============================================================================


async def test_no_papers_found_returns_failure_with_queries(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty search result returns failure but still surfaces the queries.

    The node reaches the ``len(all_paper_metadata) == 0`` gate and returns the
    failure sentinel with the generated queries and no articles.
    """
    _stub_node(
        monkeypatch,
        source_available=True,
        search_payload={},  # no papers
        queries=["only query"],
    )
    state = make_state(research_goal="empty result goal")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == ["only query"]
    assert result["articles"] == []
    assert result["messages"][0]["metadata"]["error"] is True


async def test_papers_without_fulltext_fail_but_keep_articles(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Papers found but none with fulltext fail analysis yet keep Article rows.

    ``count_papers_with_fulltext`` finds zero fulltext (abstract alone does not
    count), so the node hits the ``with_fulltext == 0`` gate: failure sentinel,
    but ``articles`` is built from the collected metadata.
    """
    papers = {
        "PMID5": {
            "title": "Abstract-only paper",
            "abstract": "Just an abstract, no body.",
        },
    }
    _stub_node(
        monkeypatch,
        source_available=True,
        search_payload=papers,
        queries=["q"],
    )
    state = make_state(research_goal="abstract only goal")

    result = await literature_review_node(state)

    assert result["articles_with_reasoning"] == LITERATURE_REVIEW_FAILED
    assert result["literature_review_queries"] == ["q"]
    # Articles are still built even though analysis could not run.
    assert len(result["articles"]) == 1
    assert result["articles"][0].source_id == "PMID5"
    assert result["messages"][0]["metadata"]["error"] is True


async def test_progress_callback_receives_events(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured progress callback receives start and completion events.

    Exercises the ``emit_progress`` seam along the happy path: the callback is
    invoked with at least the start and completion event names.
    """
    events: list[str] = []

    async def callback(event: str, _payload: dict[str, Any]) -> None:
        events.append(event)

    papers = {"PMID7": {"title": "P", "fulltext": "body"}}
    _stub_node(
        monkeypatch,
        source_available=True,
        search_payload=papers,
        queries=["q"],
        synthesis="REVIEW",
    )
    state = make_state(research_goal="callback goal",
                       progress_callback=callback)

    await literature_review_node(state)

    assert "literature_review_start" in events
    assert "literature_review_complete" in events


# =============================================================================
# In-file pure helpers
# =============================================================================


def test_get_search_config_defaults_single_source() -> None:
    """With no tool registry the config defaults to single-source pubmed."""
    config = lr._get_search_config(make_state())  # pylint: disable=protected-access
    assert config.is_multi_source is False
    assert config.source_name == "pubmed"
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.search_tool_config is None
    assert config.tool_registry is None
    assert config.papers_to_read_count > 0


def test_format_kg_section_empty_returns_empty_string() -> None:
    """No enrichment sources produces no knowledge-graph section."""
    assert lr._format_kg_section_with_keys([], 0) == ""  # pylint: disable=protected-access


def test_format_kg_section_keys_start_after_paper_count() -> None:
    """KG keys continue the [C*] numbering after the analyzed papers."""
    sources = [{"display": "Gene X -> Gene Y"}, {"display": "Gene Y -> Gene Z"}]
    section = lr._format_kg_section_with_keys(sources, 2)  # pylint: disable=protected-access
    assert "## Knowledge Graph Evidence" in section
    # paper_count == 2, so the first KG key is C3, the second C4.
    assert "[C3] Gene X -> Gene Y" in section
    assert "[C4] Gene Y -> Gene Z" in section


def test_format_kg_section_missing_display_uses_default() -> None:
    """An item lacking a ``display`` key falls back to a default label."""
    section = lr._format_kg_section_with_keys([{}], 0)  # pylint: disable=protected-access
    assert "[C1] External source" in section


def test_parse_enrichment_indra_empty_statements() -> None:
    """An INDRA response with empty ``statements`` yields no text or items."""
    text, items = lr._parse_enrichment_result({"statements": []})  # pylint: disable=protected-access
    assert text == ""
    assert items == []


def test_parse_enrichment_indra_statements_formatted() -> None:
    """INDRA statements format as 'subj -> obj [type] (belief: ..)' lines."""
    raw = {
        "statements": [{
            "subj": {"name": "KRAS"},
            "obj": {"name": "MAPK1"},
            "type": "Activation",
            "belief": 0.97,
        }]
    }
    text, items = lr._parse_enrichment_result(raw)  # pylint: disable=protected-access
    assert "KRAS" in text and "MAPK1" in text
    assert "Activation" in text
    assert len(items) == 1
    assert items[0]["display"].startswith("INDRA:")


def test_parse_enrichment_results_list_caps_items() -> None:
    """A generic ``results`` list is capped to the per-entity limit."""
    raw = {"results": [{"n": i} for i in range(10)]}
    text, items = lr._parse_enrichment_result(raw)  # pylint: disable=protected-access
    cap = lr._CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY  # pylint: disable=protected-access
    assert len(items) == cap
    assert text  # non-empty formatted text


def test_parse_enrichment_plain_string_non_json() -> None:
    """A non-JSON string becomes a single display item of truncated text."""
    text, items = lr._parse_enrichment_result("free-form text")  # pylint: disable=protected-access
    assert text == "free-form text"
    assert items == [{"display": "free-form text", "data": {}}]
