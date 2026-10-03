"""Offline contracts for reflection."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import reflection
from co_scientist.agents.reflection import review_evidence as ev
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.reflection.reflection_helpers import (
    _build_enrichment_items,
    _ev_count_str,
    _format_single_statement,
    _normalize_entity,
    _parse_tool_result,
    extract_entity_names,
    fetch_indra_evidence,
    get_kg_tools_for_workflow,
)
from co_scientist.agents.reflection.review_evidence import ReviewResearch
from co_scientist.agents.reflection.review_gate import ReviewType
from co_scientist.config import ToolRegistry
from co_scientist.config.schema import ToolConfig
from co_scientist.models import Article
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state

# Literature context that satisfies the node's ``articles_with_reasoning``
# guard so reflection actually runs (an empty/None value short-circuits the
# whole node).
_ARTICLES = "Article 1: observation A supports pathway X."


async def test_empty_hypotheses_returns_empty() -> None:
    """With articles present but no hypotheses, the node returns cleanly.

    The articles guard is satisfied so the hypotheses guard is the one that
    fires; the node returns an empty dict and never calls the LLM.
    """
    state = make_state(hypotheses=[], articles_with_reasoning=_ARTICLES)
    result = await reflection_node(state)
    assert result == {}


async def test_missing_articles_skips_node() -> None:
    """Without articles_with_reasoning the node short-circuits to an empty dict.

    The default state leaves ``articles_with_reasoning`` as None, so reflection
    is skipped even when hypotheses are present.
    """
    state = make_state(hypotheses=[make_hypothesis(text="a hypothesis")])
    result = await reflection_node(state)
    assert result == {}


async def test_hypotheses_get_reflection_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each hypothesis gets reflection_notes built from the LLM response.

    The note interleaves the ``reasoning`` and ``classification`` keys read by
    ``analyze_single_hypothesis``; with no tool_registry the INDRA enrichment
    stays empty, so the ``indra_evidence`` key is never written.
    """
    hyp_a = make_hypothesis(text="alpha pathway drives growth")
    hyp_b = make_hypothesis(text="beta pathway drives growth")
    state = make_state(
        hypotheses=[hyp_a, hyp_b], articles_with_reasoning=_ARTICLES
    )
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "missing piece",
            "reasoning": "fills a gap",
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"]
    expected_notes = "fills a gap\n\nClassification: missing piece"
    assert len(returned) == 2
    for hyp in returned:
        assert hyp.reflection_notes == expected_notes
        # LLM-only path: no INDRA enrichment was fetched.
        assert "indra_evidence" not in hyp.enrichments
    # The node mutates the same Hypothesis objects in place.
    assert hyp_a.reflection_notes == expected_notes
    assert hyp_b.reflection_notes == expected_notes
    # A reflection-phase assistant message is appended.
    assert result["messages"][0]["metadata"]["phase"] == "reflection"


async def test_empty_llm_response_defaults_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""An LLM response missing classification/reasoning uses safe defaults.

    ``analyze_single_hypothesis`` defaults ``classification`` to "neutral" and
    ``reasoning`` to "", so the note is exactly "\n\nClassification: neutral".
    """
    hyp = make_hypothesis(text="some hypothesis")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(monkeypatch, reflection, {})

    result = await reflection_node(state)

    assert result["hypotheses"][0].reflection_notes == (
        "\n\nClassification: neutral"
    )
    assert "indra_evidence" not in result["hypotheses"][0].enrichments


async def test_positive_observations_accumulate_on_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed strengths are appended to the idea's stored notes (K8).

    The paper's observation review both critiques and confirms: positive
    observations are summarized and appended to the hypothesis. They land
    in reflection_notes -- the accumulated-feedback field the ranking
    prompts read -- ahead of the "Classification:" suffix that
    agents/ranking/ranking_debate_turns.py parses back out, and are recorded
    under enrichments["observation"].
    """
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "missing piece",
            "reasoning": "fills a gap",
            "positive_observations": ["explains the resistance phenotype"],
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    notes = returned.reflection_notes or ""
    assert "fills a gap" in notes
    assert "explains the resistance phenotype" in notes
    # The strengths accumulate ahead of the parseable classification suffix.
    assert notes.index("explains the resistance phenotype") < notes.index(
        "Classification: missing piece"
    )
    assert notes.endswith("Classification: missing piece")
    assert returned.enrichments["observation"]["positive_observations"] == [
        "explains the resistance phenotype"
    ]


async def test_no_positive_observations_keeps_notes_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without confirmed strengths the notes are unchanged (no-op)."""
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "missing piece", "reasoning": "fills a gap"},
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    assert returned.reflection_notes == (
        "fills a gap\n\nClassification: missing piece"
    )
    assert "positive_observations" not in returned.enrichments["observation"]


async def test_blank_positive_observations_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank or whitespace-only positives never reach the notes."""
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "neutral",
            "reasoning": "no signal",
            "positive_observations": ["", "   "],
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    assert returned.reflection_notes == "no signal\n\nClassification: neutral"
    assert "positive_observations" not in returned.enrichments["observation"]


def test_observation_schema_bounds_positive_observations() -> None:
    """The positives field is a bounded optional string array (K8)."""
    from co_scientist.schemas.review import (
        REFLECTION_MAX_POSITIVE_OBSERVATIONS,
        REFLECTION_SCHEMA,
    )

    properties = REFLECTION_SCHEMA["schema"]["properties"]
    field = properties["positive_observations"]
    assert field["type"] == "array"
    assert field["items"] == {"type": "string"}
    assert field["maxItems"] == REFLECTION_MAX_POSITIVE_OBSERVATIONS
    assert (
        "positive_observations" not in REFLECTION_SCHEMA["schema"]["required"]
    )


def test_observation_prompt_asks_for_positive_observations() -> None:
    """The observation prompt instructs the model to confirm strengths."""
    from co_scientist.prompts import get_reflection_prompt

    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="lit", hypothesis_text="H"
    )
    assert "Positive observations" in prompt


def _validation_article() -> Article:
    """The single retrieved article a targeted full review evaluates."""
    return Article(
        title="Targeted validation",
        source_id="validation-1",
        abstract="The proposed mechanism survived direct testing.",
        used_in_analysis=True,
    )


async def test_full_and_simulation_run_for_every_viable_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every idea passing initial review receives both mature review modes.

    A blocked idea gets neither: its one call is the recheck, a single
    recurrent review it is owed once for the whole run
    (``review_recheck``), not the two-review cascade.
    """
    fake = AsyncMock(return_value={"verdict": "sound"})
    monkeypatch.setattr(cr, "call_llm_json", fake)
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"
    rejected = make_hypothesis(text="rejected")
    rejected.review_disposition = "non_novel"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=[*viable, rejected], current_iteration=0)
    )

    assert fake.await_count == 5
    assert all("full" in h.enrichments for h in viable)
    assert all("simulation" in h.enrichments for h in viable)
    assert "full" not in rejected.enrichments
    assert "recurrent" in rejected.enrichments
    assert result["metrics"].llm_calls == 5


async def test_later_cycle_runs_recurrent_review_with_tournament_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mature hypotheses are re-reviewed once per later tournament cycle."""
    fake = AsyncMock(return_value={"verdict": "needs_revision"})
    monkeypatch.setattr(cr, "call_llm_json", fake)
    hypothesis = make_hypothesis(text="mature", elo_rating=1337)
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    state = make_state(
        hypotheses=[hypothesis],
        current_iteration=2,
        meta_review={"common_weaknesses": ["missing control"]},
    )

    await cr.comprehensive_reflection_node(state)
    await cr.comprehensive_reflection_node(state)

    assert fake.await_count == 1
    call = fake.await_args
    assert call is not None
    prompt = call.kwargs["prompt"]
    assert "recurrent/tournament review" in prompt
    assert "1337" in prompt
    assert hypothesis.enrichments["recurrent_review_iteration"] == 2


async def test_a_fatal_full_review_changes_the_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fatal finding is no longer write-only (audit E1).

    The cascade reviews ideas the initial gate marked viable; when the
    full review then rejects one, the disposition flips to a blocking
    value and the idea leaves the tournament, exactly as if the initial
    gate had scored it not viable. The sound simulation beside it cannot
    outvote the rejection.
    """

    async def fake_llm(**kwargs: object) -> dict[str, object]:
        prompt = str(kwargs.get("prompt", ""))
        if "simulation review" in prompt:
            return {"verdict": "holds"}
        return {"verdict": "rejected", "justification": "circular mechanism"}

    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(side_effect=fake_llm))
    hypothesis = make_hypothesis(text="idea")
    hypothesis.review_disposition = "viable"

    await cr.comprehensive_reflection_node(
        make_state(hypotheses=[hypothesis], current_iteration=0)
    )

    assert hypothesis.enrichments["full"]["verdict"] == "rejected"
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


async def test_evolved_hypothesis_receives_missing_observation_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-evolution cascade restores the observation-review invariant."""
    hypothesis = make_hypothesis(text="evolved child")
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    observation = AsyncMock(
        return_value={
            "classification": "missing_piece",
            "reasoning": "explains x",
        }
    )
    monkeypatch.setattr(cr, "observe_hypothesis", observation)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(return_value={}))

    await cr.comprehensive_reflection_node(
        make_state(
            hypotheses=[hypothesis],
            current_iteration=0,
            articles_with_reasoning="retrieved observations",
        )
    )

    observation.assert_awaited_once()
    assert (
        hypothesis.enrichments["observation"]["classification"]
        == "missing_piece"
    )
    assert "explains x" in (hypothesis.reflection_notes or "")


async def test_missing_observation_review_appends_confirmed_strengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-evolution observation positives reach the idea too (K8)."""
    hypothesis = make_hypothesis(text="evolved child")
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    observation = AsyncMock(
        return_value={
            "classification": "missing_piece",
            "reasoning": "explains x",
            "positive_observations": ["accounts for the late onset"],
        }
    )
    monkeypatch.setattr(cr, "observe_hypothesis", observation)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(return_value={}))

    await cr.comprehensive_reflection_node(
        make_state(
            hypotheses=[hypothesis],
            current_iteration=0,
            articles_with_reasoning="retrieved observations",
        )
    )

    notes = hypothesis.reflection_notes or ""
    assert "accounts for the late onset" in notes
    assert notes.index("accounts for the late onset") < notes.index(
        "Classification: missing_piece"
    )
    assert hypothesis.enrichments["observation"]["positive_observations"] == [
        "accounts for the late onset"
    ]


@pytest.mark.asyncio
async def test_full_review_executes_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full review searches and evaluates evidence specific to the idea.

    The search runs on keywords formulated from the hypothesis, not on the
    hypothesis text itself: the literature back end ANDs every term, so prose
    would retrieve nothing and leave the review ungrounded.
    """
    # First call formulates the queries, second is the review itself.
    call = AsyncMock(return_value={"verdict": "sound"})
    retrieve = AsyncMock(return_value=([_validation_article()], []))
    monkeypatch.setattr(cr, "call_llm_json", call)
    monkeypatch.setattr(
        ev,
        "call_llm_json",
        AsyncMock(return_value={"queries": ["mechanism X response Y"]}),
    )
    monkeypatch.setattr(ev, "_retrieve_probe_evidence", retrieve)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=True,
    )

    _, result, _ = await cr._run_review(state, hypothesis, ReviewType.FULL)

    retrieve.assert_awaited_once_with(state, ["mechanism X response Y"])
    assert result is not None
    assert result["retrieval_queries"] == ["mechanism X response Y"]
    assert result["retrieved_articles"][0]["source_id"] == "validation-1"
    # The retrieved evidence reaches the review prompt (the last call).
    prompt = call.await_args_list[-1].kwargs["prompt"]
    assert "Targeted validation" in prompt
    assert "survived direct testing" in prompt


@pytest.mark.asyncio
async def test_query_generation_is_skipped_without_a_search_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP means no search, so the review must not pay to write queries."""
    call = AsyncMock(return_value={"verdict": "sound"})
    monkeypatch.setattr(cr, "call_llm_json", call)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=False,
    )

    _, result, _ = await cr._run_review(state, hypothesis, ReviewType.FULL)

    assert result is not None
    assert result["retrieval_queries"] == []
    # The review call only -- no query-generation call was spent.
    assert call.await_count == 1


async def test_full_and_simulation_share_one_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One hypothesis costs one query-generation call and one retrieval.

    Both reviews ask the same question of the same literature: queries come
    from the hypothesis text and the research goal, neither of which varies
    by review mode. Run independently they paid for it twice, on the run's
    critical path.
    """
    query_calls = 0
    retrievals = 0

    async def _queries(
        _state: object, _hypothesis: object
    ) -> dict[str, object]:
        nonlocal query_calls
        query_calls += 1
        # Yield, so a stampeding second caller has the chance to start its
        # own retrieval before this one records a result to share.
        await asyncio.sleep(0)
        return {"queries": ["targeted query"]}

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        nonlocal retrievals
        retrievals += 1
        await asyncio.sleep(0)
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_call_hypothesis_query_llm", _queries)
    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        cr,
        "call_llm_json",
        AsyncMock(return_value={"assessment": "ok", "score": 4}),
    )

    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, _ = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    assert query_calls == 1
    assert retrievals == 1
    # Both reviews persist the shared evidence, so it survives the
    # checkpoint without depending on the in-process cache.
    for mode in (ReviewType.FULL, ReviewType.SIMULATION):
        stored = hypothesis.enrichments[mode.value]["retrieved_articles"]
        assert [item["source_id"] for item in stored] == ["validation-1"]


async def test_rewritten_hypothesis_does_not_reuse_stale_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evolution rewrites a hypothesis; old evidence no longer answers it."""
    hypothesis = make_hypothesis(text="original claim")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    before = ev._evidence_key(state, hypothesis)
    hypothesis.text = "a materially different claim"

    assert ev._evidence_key(state, hypothesis) != before


# =============================================================================
# Research: the second retrieval round the deep tiers buy
# =============================================================================


def _stub_review_research(
    monkeypatch: pytest.MonkeyPatch, *, fails: bool = False
) -> None:
    """Make research return one article and a ledger, or blow up."""

    async def fake_research(_state: object, _hypothesis: object) -> object:
        if fails:
            raise RuntimeError("source unreachable")
        return ReviewResearch(
            articles=[
                Article(
                    title="Researched paper",
                    source_id="researched-1",
                    abstract="Human evidence for the mechanism.",
                    retrieval_call_id="call-1",
                )
            ],
            ledger={"goal": "g", "threads": [], "calls": [], "findings": []},
        )

    monkeypatch.setattr(ev, "research_for_review", fake_research)


async def test_research_adds_to_the_probe_round_rather_than_replacing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A funded review keeps what its first search found and gains more."""

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        ev,
        "_call_hypothesis_query_llm",
        AsyncMock(return_value={"queries": ["targeted query"]}),
    )
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    _stub_review_research(monkeypatch)
    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, ledgers = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    stored = hypothesis.enrichments["full"]["retrieved_articles"]
    assert [item["source_id"] for item in stored] == [
        "validation-1",
        "researched-1",
    ]
    # Both reviews share one retrieval, so the run is billed one ledger.
    assert len(ledgers) == 1


async def test_a_review_whose_research_broke_is_still_a_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grounding in what the first round found beats failing the item."""

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        ev,
        "_call_hypothesis_query_llm",
        AsyncMock(return_value={"queries": ["targeted query"]}),
    )
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    _stub_review_research(monkeypatch, fails=True)
    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, ledgers = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    assert ledgers == []
    stored = hypothesis.enrichments["full"]["retrieved_articles"]
    assert [item["source_id"] for item in stored] == ["validation-1"]


async def test_the_node_carries_every_hypothesis_ledger_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ledgers are the run's, so the node returns them on its update.

    Left inside the reviews they would never reach the drain, and the
    searches a review paid for would be unrecorded.
    """
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    _stub_review_research(monkeypatch)
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=viable, current_iteration=0)
    )

    # One per hypothesis: identical ledgers here, deduplicated by the
    # state's own reducer rather than by the node.
    assert len(result["research_ledgers"]) == 2


class _FakeRegistry:
    """Minimal duck-typed stand-in for the ToolRegistry methods used.

    ``get_kg_tools_for_workflow`` calls ``get_tools_for_workflow``,
    ``get_tool`` (to read each tool's declared source type) and
    ``get_mcp_tool_names``, so the test fake implements just those.
    ``get_tools_for_workflow`` may be configured to raise, to exercise the
    helper's exception swallow, and ``source_type`` sets what kind of tool
    the configured ids resolve to.
    """

    def __init__(
        self,
        tool_ids: list[str],
        mcp_names: list[str],
        raise_on_workflow: bool = False,
        source_type: str = "knowledge_graph",
    ) -> None:
        self._tool_ids = tool_ids
        self._mcp_names = mcp_names
        self._raise_on_workflow = raise_on_workflow
        self._source_type = source_type

    def get_tool(self, tool_id: str) -> ToolConfig:
        """Return a config for tool_id, typed as this fake was configured."""
        return ToolConfig(
            server="default_pubmed",
            mcp_tool_name=tool_id,
            source_type=self._source_type,
        )

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        """Return configured tool IDs, or raise if asked to."""
        del workflow_name
        if self._raise_on_workflow:
            raise RuntimeError("boom")
        return self._tool_ids

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        """Resolve the given IDs -- only those -- to MCP tool names.

        Resolves per id rather than returning the whole configured list, so
        a test can tell an id the helper filtered out from one it kept.
        """
        names = dict(zip(self._tool_ids, self._mcp_names, strict=False))
        return [names[tool_id] for tool_id in tool_ids if tool_id in names]


def _fake(
    tool_ids: list[str],
    mcp_names: list[str],
    raise_on_workflow: bool = False,
    source_type: str = "knowledge_graph",
) -> ToolRegistry:
    """Build a fake registry typed as ToolRegistry for the helper signature."""
    return cast(
        ToolRegistry,
        _FakeRegistry(tool_ids, mcp_names, raise_on_workflow, source_type),
    )


# --- extract_entity_names -------------------------------------------------


def test_extract_entity_names_basic() -> None:
    """All-caps tokens and hyphenated bio names are extracted and normalized."""
    result = extract_entity_names("IL-6 activates TREM2 in microglia")
    # IL-6 -> IL6 (hyphen stripped, captured in pass 1); TREM2 in pass 2.
    assert result == ["IL6", "TREM2"]


def test_extract_entity_names_requires_all_caps() -> None:
    """Title/lowercase gene names are not extracted: the rule is all-caps."""
    assert extract_entity_names("Kras drives growth") == []


def test_extract_entity_names_no_entities_returns_empty() -> None:
    """Ordinary prose with no all-caps tokens yields an empty list."""
    assert extract_entity_names("the quick brown fox jumps") == []


def test_extract_entity_names_filters_stopwords() -> None:
    """All-caps non-gene abbreviations in the stop set are dropped."""
    # DNA and RNA are both in _STOP; AND is too.
    assert extract_entity_names("DNA and RNA bind") == []


def test_extract_entity_names_skips_mutation_notation() -> None:
    """Standalone tokens whose 2nd char is a digit (e.g. G12C) are skipped."""
    # KRAS survives; the mutation notation G12C is dropped.
    assert extract_entity_names("KRAS G12C variant") == ["KRAS"]


def test_extract_entity_names_digit_skip_precedes_alias() -> None:
    """P53 is dropped by the pass-2 digit-skip before alias mapping runs."""
    # Second char of "P53" is a digit, so it is skipped before _ALIAS_MAP
    # (P53 -> TP53) would ever apply.
    assert extract_entity_names("P53 pathway") == []


def test_extract_entity_names_applies_alias_map() -> None:
    """Known informal aliases are mapped to canonical symbols (RAGE -> AGER)."""
    assert extract_entity_names("RAGE signaling") == ["AGER"]


def test_extract_entity_names_two_letter_only_via_hyphen() -> None:
    """Two-letter symbols match only through the hyphenated form, not in prose.

    The standalone regex requires >=3 chars, so a bare "IL" never matches; the
    "IL" inside "IL-6" is captured (as IL6) and its prefix is marked seen.
    """
    assert extract_entity_names("IL-6 and IL together") == ["IL6"]


def test_extract_entity_names_deduplicates() -> None:
    """A repeated hyphenated name yields a single normalized entry."""
    # YKL-40 -> CHI3L1 via alias; the duplicate is collapsed.
    assert extract_entity_names("YKL-40 and YKL-40 again") == ["CHI3L1"]


def test_extract_entity_names_respects_max_entities_cap() -> None:
    """The final result is capped at max_entities."""
    text = "KRAS TREM2 APOE TP53 BRAF"
    assert extract_entity_names(text, max_entities=2) == ["KRAS", "TREM2"]
    assert len(extract_entity_names(text, max_entities=4)) == 4


# --- _normalize_entity ----------------------------------------------------


def test_normalize_entity_strips_hyphen() -> None:
    """Hyphens are removed from bio names with no alias entry."""
    assert _normalize_entity("IL-6") == "IL6"


def test_normalize_entity_applies_alias() -> None:
    """An informal name is rewritten to its canonical symbol."""
    assert _normalize_entity("RAGE") == "AGER"


# --- get_kg_tools_for_workflow --------------------------------------------


def test_get_kg_tools_none_registry_returns_empty() -> None:
    """No registry configured means no KG tools, so the gate stays closed."""
    assert get_kg_tools_for_workflow(None, "reflection") == []


def test_get_kg_tools_no_tool_ids_returns_empty() -> None:
    """A registry that lists no tools for the workflow returns an empty list."""
    registry = _fake(tool_ids=[], mcp_names=["unused"])
    assert get_kg_tools_for_workflow(registry, "reflection") == []


def test_get_kg_tools_returns_mcp_names() -> None:
    """With configured tools, the resolved MCP tool names are returned."""
    registry = _fake(
        tool_ids=["indra_a", "indra_b"],
        mcp_names=["get_relations", "get_complexes"],
    )
    assert get_kg_tools_for_workflow(registry, "reflection") == [
        "get_relations",
        "get_complexes",
    ]


def test_get_kg_tools_swallows_exception() -> None:
    """A registry that raises is caught and yields an empty list."""
    registry = _fake(tool_ids=["x"], mcp_names=["y"], raise_on_workflow=True)
    assert get_kg_tools_for_workflow(registry, "reflection") == []


# --- fetch_indra_evidence short-circuit -----------------------------------


async def test_fetch_indra_evidence_none_registry_short_circuits() -> None:
    """With no registry the coroutine returns the empty result without I/O."""
    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=None
    )
    assert result == {"prompt_text": "", "enrichment_items": []}


# --- _parse_tool_result ---------------------------------------------------


def test_parse_tool_result_valid_json_string() -> None:
    """A JSON string is decoded into a dict."""
    assert _parse_tool_result('{"statements": [1, 2]}') == {
        "statements": [1, 2]
    }


def test_parse_tool_result_invalid_json_string() -> None:
    """A non-JSON string falls back to an empty dict."""
    assert _parse_tool_result("not json") == {}


def test_parse_tool_result_dict_passthrough() -> None:
    """An already-parsed dict is returned unchanged."""
    payload: dict[str, Any] = {"statements": []}
    assert _parse_tool_result(payload) == payload


def test_parse_tool_result_other_type_returns_empty() -> None:
    """A non-string, non-dict input yields an empty dict."""
    assert _parse_tool_result(42) == {}


# --- _ev_count_str --------------------------------------------------------


def test_ev_count_str_below_limit() -> None:
    """Counts below the fetch limit render as a plain number."""
    assert _ev_count_str(24) == "24"


def test_ev_count_str_at_limit_marks_truncation() -> None:
    """Counts at or above the limit gain a trailing '+' to signal truncation."""
    assert _ev_count_str(25) == "25+"


# --- _format_single_statement ---------------------------------------------


def test_format_single_statement_subject_object() -> None:
    """A subj/obj statement renders as a directed relationship line."""
    line = _format_single_statement(
        {
            "type": "Activation",
            "belief": 0.9,
            "evidence": [1, 2],
            "subj": {"name": "KRAS"},
            "obj": {"name": "BRAF"},
        }
    )
    assert line == "- KRAS --[Activation]--> BRAF (belief: 0.90, 2 papers)"


def test_format_single_statement_complex_members() -> None:
    """A members-only statement renders as a Complex(...) line."""
    line = _format_single_statement(
        {
            "type": "Complex",
            "belief": 0.8,
            "evidence": [],
            "members": [{"name": "A"}, {"name": "B"}],
        }
    )
    assert line == "- Complex(A, B) [Complex] (belief: 0.80, 0 papers)"


def test_format_single_statement_empty_when_no_agents() -> None:
    """A statement with neither subj/obj nor members renders as empty."""
    assert _format_single_statement({"type": "Unknown"}) == ""


# --- _build_enrichment_items ----------------------------------------------


def test_build_enrichment_items_injects_queried_entities_on_first() -> None:
    """Only the first item carries the queried_entities annotation."""
    items = _build_enrichment_items(
        [
            {
                "type": "Activation",
                "belief": 0.9,
                "evidence": [1, 2],
                "subj": {"name": "KRAS"},
                "obj": {"name": "BRAF"},
            },
            {
                "type": "Complex",
                "belief": 0.8,
                "evidence": [],
                "members": [{"name": "A"}, {"name": "B"}],
            },
        ],
        ["KRAS", "TREM2"],
    )
    assert len(items) == 2
    assert items[0]["relationship"] == "KRAS → BRAF"
    assert items[0]["belief"] == "90%"
    assert items[0]["evidence_count"] == "2"
    assert items[0]["queried_entities"] == "KRAS, TREM2"
    assert items[1]["relationship"] == "Complex(A, B)"
    assert "queried_entities" not in items[1]


def test_build_enrichment_items_empty_input_returns_empty() -> None:
    """No statements (or only unconvertible ones) yields an empty list."""
    assert _build_enrichment_items([], ["KRAS"]) == []
    assert _build_enrichment_items([{"type": "X"}], ["KRAS"]) == []


def test_get_kg_tools_skips_tools_that_are_not_knowledge_graphs() -> None:
    """A literature tool listed for this workflow is never queried.

    Workflow tool lists mix both kinds -- the shipped config lists PubMed and
    the biomedical databases under ``reflection`` for prompt context -- and
    this path sends INDRA's own entity arguments, which those tools reject.
    """
    registry = _fake(
        tool_ids=["pubmed_fulltext"],
        mcp_names=["pubmed_search_with_fulltext"],
        source_type="academic",
    )
    assert get_kg_tools_for_workflow(registry, "reflection") == []
