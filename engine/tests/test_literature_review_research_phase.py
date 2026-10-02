"""Phase 6: the literature review going back for what it did not answer.

The review searches once, from the goal. This phase reads what came back,
takes the gaps the papers themselves stated, and researches those within
the run's tier. These tests pin the parts that make the assignment
correct rather than merely present: research is off unless a tier asked
for it, the first questions come from the reading rather than from a
fresh guess, only papers something was drawn from enter the pool, and
every one of them carries the id of the search that found it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review.research_phase import (
    _seed_questions,
    run_research_phase,
)
from co_scientist.evidence.helpers import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.research import result_from_dict
from tests._research_tools import (
    FakeResearchClient,
    research_registry,
    research_workflow,
)
from tests._state import make_state

_PAPERS = {
    "doc-a": {
        "title": "Fibrosis mechanisms",
        "abstract": "TGF-beta signalling drives fibrosis.",
        "pdf_url": "u/a",
    },
    "doc-b": {
        "title": "A second look",
        "abstract": "Contradicting evidence in mice.",
    },
}


def _config(tmp_path: Path) -> SearchConfig:
    """A search config over the shared research tool fixture."""
    registry = research_registry(tmp_path)
    return SearchConfig(
        tool_registry=registry,
        workflow=research_workflow(registry),
        is_multi_source=True,
        search_tool_name="search_alpha",
        search_tool_config=registry.get_tool("alpha"),
        source_name="alpha",
        papers_to_read_count=4,
        is_dev_mode=False,
        research_goal="reverse fibrosis",
        model_name="offline/test",
    )


class _ScriptedModel:
    """Answers each of the five research prompts by what it was asked."""

    def __init__(self) -> None:
        """Start with nothing asked."""
        self.prompts: list[str] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Answer one prompt, recording it."""
        self.prompts.append(prompt)
        if "perspectives to research" in prompt:
            return {"stances": ["mechanism"]}
        if "questions this perspective needs" in prompt:
            return {"questions": ["what drives fibrosis?"]}
        if "search query" in prompt:
            return {"query": "fibrosis TGF-beta"}
        if "retrieved documents" in prompt:
            return {
                "findings": [
                    {
                        "document": 0,
                        "claim": "TGF-beta drives fibrosis",
                        "quote": "TGF-beta signalling drives fibrosis.",
                    }
                ],
                "follow_ups": [],
            }
        return {"summary": "TGF-beta is the consensus driver."}


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    """Route the adapter's model calls to a scripted answerer."""
    model = _ScriptedModel()
    monkeypatch.setattr(
        "co_scientist.research_adapter.model.call_llm_json", model
    )
    return model


def _client() -> MCPToolClient:
    """A client whose search returns two papers and reads one of them."""
    return cast(
        MCPToolClient,
        FakeResearchClient(
            {
                "search_alpha": _PAPERS,
                "read_pdf": {"content": "TGF-beta signalling drives fibrosis."},
            }
        ),
    )


async def test_a_run_that_asked_for_no_research_does_none(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """Off unless a tier asked: the loop is a multiplier on run cost."""
    client = _client()

    outcome = await run_research_phase(
        make_state(research_tier=""), _config(tmp_path), client, []
    )

    assert outcome is None
    assert cast(FakeResearchClient, client).calls == []
    assert scripted.prompts == []


async def test_research_seeds_its_first_level_from_what_was_read(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """The gaps the papers stated beat a fresh guess from the goal."""
    analyses = [
        {"analysis": {"gaps_identified": "No human data on TGF-beta blockade"}}
    ]

    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        analyses,
    )

    assert outcome is not None
    asked = [thread["question"]["text"] for thread in outcome.ledger["threads"]]
    assert "No human data on TGF-beta blockade" in asked
    # Seeded, so no stance planning call was made.
    assert not any("perspectives to research" in p for p in scripted.prompts)


async def test_research_plans_its_own_coverage_when_nothing_was_stated(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """An analysis with no gaps is not a reason to skip the phase."""
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [{"analysis": {"key_findings": "much is known"}}],
    )

    assert outcome is not None
    assert any("perspectives to research" in p for p in scripted.prompts)


async def test_only_papers_something_was_drawn_from_join_the_pool(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """A hit that was merely listed must not enter every later prompt."""
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [],
    )

    assert outcome is not None
    assert list(outcome.records) == ["doc-a"]
    assert outcome.records["doc-a"]["title"] == "Fibrosis mechanisms"


async def test_every_researched_paper_names_the_search_that_found_it(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """This is the link that makes the stored provenance resolvable."""
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [],
    )

    assert outcome is not None
    made = result_from_dict(outcome.ledger).calls
    assert outcome.records["doc-a"]["retrieval_call_id"] in {
        call.id for call in made
    }
    assert outcome.records["doc-a"]["_source_name"] == "alpha"


async def test_the_findings_reach_the_text_every_later_agent_reads(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """A finding that lives only in the ledger was recorded, not used."""
    outcome = await run_research_phase(
        make_state(research_tier="extended", run_id="run-1"),
        _config(tmp_path),
        _client(),
        [],
    )

    assert outcome is not None
    assert "TGF-beta drives fibrosis" in outcome.section
    assert "TGF-beta is the consensus driver." in outcome.section


async def test_a_run_with_no_enabled_source_researches_nothing(
    tmp_path: Path, scripted: _ScriptedModel
) -> None:
    """No source to search is a configuration state, not a failure."""
    config = _config(tmp_path)
    assert config.workflow is not None
    for source in config.workflow.search_sources:
        source.enabled = False

    outcome = await run_research_phase(
        make_state(research_tier="ultra", run_id="run-1"),
        config,
        _client(),
        [],
    )

    assert outcome is None


def test_seed_questions_stop_at_the_first_level_breadth() -> None:
    """More seeds than the level can fund would be declined anyway."""
    analyses = [
        {"analysis": {"gaps_identified": f"gap {n}", "unexplored_areas": ""}}
        for n in range(6)
    ]

    assert _seed_questions(analyses, 3) == ["gap 0", "gap 1", "gap 2"]


def test_the_same_gap_stated_twice_is_one_question() -> None:
    """Two papers naming the same hole must not buy two searches."""
    analyses = [
        {"analysis": {"gaps_identified": "No human data"}},
        {"analysis": {"gaps_identified": "no human data  "}},
        {"analysis": {"unexplored_areas": "Dosing is unstudied"}},
    ]

    assert _seed_questions(analyses, 4) == [
        "No human data",
        "Dosing is unstudied",
    ]
