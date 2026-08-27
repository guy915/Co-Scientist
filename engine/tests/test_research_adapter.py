"""Assigning the standalone research loop to this engine.

``co_scientist.research`` is deliberately ignorant of MCP, of prompts and
of run tiers; ``research_adapter`` is what supplies all three. These tests
cover the seam itself -- that a source's own ranking survives, that a
search failure becomes a recorded failed call rather than an exception
escaping into the loop, that the extractor identifies documents by index
instead of echoing them back, and that only the tiers which bought depth
get any.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from co_scientist.generator.run_setup import _resolve_research_tier
from co_scientist.research import Document, RetrievalError, SourceHit
from co_scientist.research_adapter import (
    LlmResearchModel,
    McpRetrieval,
    budget_for_tier,
)
from co_scientist.research_adapter.retrieval import ResearchRun
from tests._research_tools import (
    FakeResearchClient,
    research_registry,
    research_workflow,
)


def _retrieval(tmp_path: Path, client: Any) -> McpRetrieval:
    """Retrieval bound to that registry's literature-review workflow."""
    registry = research_registry(tmp_path)
    workflow = research_workflow(registry)
    return McpRetrieval(
        client,
        registry,
        workflow,
        ResearchRun(run_id="run-1", research_goal="fibrosis reversal"),
    )


_HITS = {
    "doc-a": {"title": "First", "abstract": "About a", "pdf_url": "u/a"},
    "doc-b": {"title": "Second", "abstract": "About b", "doi": "10.1/b"},
}


# --- Retrieval --------------------------------------------------------------


async def test_search_keeps_the_source_ordering_it_was_given(
    tmp_path: Path,
) -> None:
    """Rank is the source's, not ours -- a replay has to reproduce it."""
    retrieval = _retrieval(
        tmp_path, FakeResearchClient({"search_alpha": _HITS})
    )

    hits = await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert [hit.locator for hit in hits] == ["doc-a", "doc-b"]
    assert [hit.rank for hit in hits] == [0, 1]
    assert hits[0].title == "First"
    assert hits[1].metadata["doi"] == "10.1/b"
    assert hits[0].metadata["source"] == "alpha"


async def test_search_takes_no_more_hits_than_it_was_asked_for(
    tmp_path: Path,
) -> None:
    """The evidence budget is the loop's, and the port must honour it."""
    retrieval = _retrieval(
        tmp_path, FakeResearchClient({"search_alpha": _HITS})
    )

    hits = await retrieval.search(query="fibrosis", source="alpha", limit=1)

    assert [hit.locator for hit in hits] == ["doc-a"]


async def test_an_unconfigured_source_is_a_retrieval_error(
    tmp_path: Path,
) -> None:
    """Naming a source the run does not have is a failed call, not a crash.

    The loop searches every source in its budget; one that has been
    disabled or renamed must cost that source's call and nothing more.
    """
    retrieval = _retrieval(tmp_path, FakeResearchClient({}))

    with pytest.raises(RetrievalError) as caught:
        await retrieval.search(query="q", source="gamma", limit=2)

    assert caught.value.source == "gamma"


async def test_a_broken_source_is_a_retrieval_error_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable source has to reach the ledger as that source."""
    monkeypatch.setattr(
        "co_scientist.agents.generation.literature_review."
        "search_retry._search_retry_delay",
        lambda attempt: 0.0,
    )
    client = FakeResearchClient(
        {"search_alpha": RuntimeError("connection refused")}
    )
    retrieval = _retrieval(tmp_path, client)

    with pytest.raises(RetrievalError) as caught:
        await retrieval.search(query="q", source="alpha", limit=2)

    assert caught.value.source == "alpha"
    assert "connection refused" in str(caught.value)


async def test_only_enabled_sources_are_offered_to_the_caller(
    tmp_path: Path,
) -> None:
    """The registry has already reconciled what is on; do not re-filter."""
    retrieval = _retrieval(tmp_path, FakeResearchClient({}))

    assert retrieval.sources == ("alpha",)


async def test_reading_a_hit_fetches_its_full_text(tmp_path: Path) -> None:
    """A locator alone carries no URL, so the search record has to."""
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": {"content": "the whole paper"}}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    text = await retrieval.read(locator="doc-a")

    assert text == "the whole paper"
    assert client.calls[-1][1]["url"] == "u/a"


async def test_a_hit_with_no_url_reads_as_nothing_not_as_an_error(
    tmp_path: Path,
) -> None:
    """Unreadable is a normal answer: the loop falls back to the snippet."""
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": {"content": "x"}}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert await retrieval.read(locator="doc-b") is None
    assert await retrieval.read(locator="never-seen") is None


async def test_a_failed_read_does_not_lose_the_document(
    tmp_path: Path,
) -> None:
    """The document still has its snippet; a raised error would drop it."""
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": RuntimeError("timeout")}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert await retrieval.read(locator="doc-a") is None


# --- Model ------------------------------------------------------------------


class _FakeLlm:
    """Stands in for call_llm_json, recording what each call was sent."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.specs: list[Any] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.specs.append(spec)
        return self.answers.pop(0) if self.answers else {}


def _model(
    monkeypatch: pytest.MonkeyPatch, *answers: dict[str, Any]
) -> tuple[LlmResearchModel, _FakeLlm]:
    """A research model whose LLM calls are scripted."""
    fake = _FakeLlm(*answers)
    monkeypatch.setattr(
        "co_scientist.research_adapter.model.call_llm_json", fake
    )
    return LlmResearchModel("offline/test", run_id="run-1"), fake


def _document(locator: str, text: str = "body") -> Document:
    """One admitted document, as the loop hands it to the extractor."""
    return Document(
        hit=SourceHit(
            locator=locator, title=f"T {locator}", snippet="s", rank=0
        ),
        text=text,
        full_text=True,
    )


async def test_stances_and_questions_stay_inside_their_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that over-answers must not widen the level it was funding."""
    model, _ = _model(
        monkeypatch,
        {"stances": ["mechanism", "counter-evidence", "prior art", "extra"]},
        {"questions": ["q1", "q2", "q3"]},
    )

    stances = await model.plan_stances(goal="fibrosis", limit=3)
    questions = await model.ask_questions(
        goal="fibrosis", stance="mechanism", limit=2
    )

    assert list(stances) == ["mechanism", "counter-evidence", "prior art"]
    assert list(questions) == ["q1", "q2"]


async def test_a_query_the_model_would_not_write_falls_back_to_the_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing query is a worse search, never a dropped thread."""
    model, _ = _model(monkeypatch, {})

    assert await model.to_query(question="What drives fibrosis?") == (
        "What drives fibrosis?"
    )


async def test_findings_are_bound_by_index_not_by_echoed_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output length must track what was found, not what was read.

    A schema that names documents by title makes the reply scale with the
    pool, which truncates identically on every retry. The prompt numbers
    the documents and the schema answers with the number.
    """
    model, fake = _model(
        monkeypatch,
        {
            "findings": [
                {"document": 1, "claim": "B causes X", "quote": "b says so"}
            ],
            "follow_ups": ["what about Y?"],
        },
    )
    documents = [_document("doc-a"), _document("doc-b")]

    extraction = await model.extract(question="why X?", documents=documents)

    assert "[0] T doc-a" in fake.prompts[0]
    assert "[1] T doc-b" in fake.prompts[0]
    assert [f.locator for f in extraction.findings] == ["doc-b"]
    assert extraction.findings[0].span == "b says so"
    assert extraction.follow_ups == ("what about Y?",)


async def test_extraction_prompt_strips_citation_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read document's own citations do not reach the extraction prompt.

    Left in, the extraction model can copy one into a reported finding --
    a real-looking reference attached to a claim the cited source never
    made.
    """
    model, fake = _model(monkeypatch, {"findings": [], "follow_ups": []})
    original = "This confirms prior work (Smith et al. 2019) [12]."
    documents = [_document("doc-a", text=original)]

    await model.extract(question="why X?", documents=documents)

    assert "(Smith et al. 2019)" not in fake.prompts[0]
    assert "[12]" not in fake.prompts[0]
    assert documents[0].text == original


async def test_a_finding_that_names_no_real_document_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plausible wrong source is worse than one fewer finding."""
    model, _ = _model(
        monkeypatch,
        {
            "findings": [
                {"document": 7, "claim": "c", "quote": "q"},
                {"document": 0, "claim": "kept", "quote": "q"},
                {"document": 0, "claim": "no quote", "quote": "  "},
            ]
        },
    )

    extraction = await model.extract(
        question="why X?", documents=[_document("doc-a")]
    )

    assert [f.text for f in extraction.findings] == ["kept"]


async def test_nothing_to_read_or_summarize_costs_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thread whose searches came back empty must not pay for a model."""
    model, fake = _model(monkeypatch)

    assert await model.extract(question="q", documents=[]) == (
        await model.extract(question="q", documents=[])
    )
    assert await model.compress(question="q", findings=[]) == ""
    assert fake.prompts == []


async def test_every_call_sets_its_own_token_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """These are thinking calls; an unset budget takes the provider's.

    Reading several documents is the one call here that writes a long
    answer, so it is funded above the rest rather than all five sharing
    one number.
    """
    model, fake = _model(
        monkeypatch, {"query": "fibrosis mechanism"}, {"findings": []}
    )

    await model.to_query(question="what drives fibrosis?")
    await model.extract(question="q", documents=[_document("doc-a")])

    assert all(spec.max_tokens > 0 for spec in fake.specs)
    assert fake.specs[1].max_tokens > fake.specs[0].max_tokens


# --- Budget -----------------------------------------------------------------


def test_only_the_deep_tiers_buy_research() -> None:
    """Switching this on everywhere multiplies an express run's cost."""
    assert budget_for_tier("express", ["alpha"]) is None
    assert budget_for_tier("standard", ["alpha"]) is None
    assert budget_for_tier("unknown-tier", ["alpha"]) is None


def test_a_tier_states_its_thread_count_before_spending_anything() -> None:
    """The whole point of the arithmetic budget is a quotable ceiling."""
    extended = budget_for_tier("extended", ["alpha"])
    ultra = budget_for_tier("ultra", ["alpha", "beta"])

    assert extended is not None and ultra is not None
    assert extended.max_threads() == 6
    assert ultra.max_threads() == 11
    assert ultra.sources == ("alpha", "beta")


def test_a_run_with_no_search_source_researches_nothing() -> None:
    """No source is a configuration state, not a budget to raise on."""
    assert budget_for_tier("ultra", []) is None


# --- The gate the run passes through ----------------------------------------


def test_a_run_that_names_no_tier_researches_nothing() -> None:
    """Silence is not a request; a caller has to ask by name."""
    assert _resolve_research_tier({}, True) == ""
    assert _resolve_research_tier({"research_tier": ""}, True) == ""


def test_research_is_refused_where_there_is_nothing_to_search() -> None:
    """The loop's whole shape is search, read, search again.

    Without MCP the run has no reachable source at all -- so this is
    refused up front rather than discovered one empty call at a time.
    Note what is *not* a refusal: the literature review node being off.
    Research has a second owner in the deep reviews, which resolve the
    run's sources from its tool registry
    themselves.
    """
    assert _resolve_research_tier({"research_tier": "ultra"}, False) == ""


def test_the_offline_backend_still_researches() -> None:
    """Unlike the tool loops, these are ordinary schema-shaped calls.

    The offline responder answers them deterministically, so an offline
    run exercises the whole path rather than skipping it -- which is what
    makes this testable without a provider key.
    """
    assert _resolve_research_tier({"research_tier": "ultra"}, True) == "ultra"
