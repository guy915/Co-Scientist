"""Offline contracts for research overview directions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review import (
    research_overview_direction_calls as calls,
)
from co_scientist.agents.meta_review import research_overview_evidence as ev
from co_scientist.constants import RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
from co_scientist.llm import ModelCallStats, record_call, scoped_telemetry
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_MAX_DIRECTIONS,
    RESEARCH_OVERVIEW_TARGET_DIRECTIONS,
)
from tests._state import make_article, make_hypothesis, make_state


def _context() -> calls.DirectionWaveContext:
    """The run material every writing call in these tests shares."""
    return calls.DirectionWaveContext(
        state=make_state(
            research_goal="Reverse liver fibrosis",
            supervisor_model_name="test/model",
        ),
        hypotheses_summary="1. an idea",
        evidence_corpus_text="evidence-1: a paper",
    )


def _drafted(count: int) -> list[dict[str, Any]]:
    """A draft's directions: named and argued, bodies left unwritten."""
    return [
        {
            "title": f"Direction {index}",
            "importance": f"Why direction {index} matters.",
            "recent_findings": "",
            "suggested_experiments": [],
            "sub_topics": [],
        }
        for index in range(count)
    ]


def _body() -> dict[str, Any]:
    """One writing call's answer."""
    return {
        "importance": "The developed argument.",
        "recent_findings": "What is already established.",
        "suggested_experiments": ["Knock it down and read out the marker."],
        "sub_topics": [
            {
                "title": "Sub-topic A",
                "why": "Because Y.",
                "what": "Investigate Z.",
                "example_idea": "Knock Z down and read out Y.",
                "specific_questions": ["Does Z cause Y?"],
            }
        ],
    }


async def test_the_ask_is_the_published_exemplar_s_own_count() -> None:
    """The draft asks for six, which is also what it is allowed to keep."""
    assert RESEARCH_OVERVIEW_TARGET_DIRECTIONS == 6
    assert (
        RESEARCH_OVERVIEW_TARGET_DIRECTIONS == RESEARCH_OVERVIEW_MAX_DIRECTIONS
    )


async def test_every_drafted_direction_buys_its_own_call() -> None:
    """Six directions are six concurrent calls, not one long stream."""
    ask = AsyncMock(return_value=_body())

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(RESEARCH_OVERVIEW_TARGET_DIRECTIONS), ask
    )

    assert spent == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert ask.await_count == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert len(developed) == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert all(direction["sub_topics"] for direction in developed)


async def test_each_call_is_bounded_well_inside_the_per_call_clock() -> None:
    """The budget is the split's whole point; a floor-sized one is not it."""
    ask = AsyncMock(return_value=_body())

    await calls.develop_research_directions(_context(), _drafted(1), ask)

    sent = ask.await_args_list[0].kwargs
    assert sent["spec"].max_tokens == RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
    assert sent["options"].enable_thinking is False


async def test_a_writing_call_can_never_rename_its_direction() -> None:
    """The overview's contacts cross-reference a direction by its title."""
    ask = AsyncMock(return_value={**_body(), "title": "Renamed"})

    developed, _ = await calls.develop_research_directions(
        _context(), _drafted(1), ask
    )

    assert developed[0]["title"] == "Direction 0"


async def test_one_failing_call_costs_only_its_own_direction() -> None:
    """A raising sibling under one gather would cancel the rest of them."""
    ask = AsyncMock(side_effect=[RuntimeError("provider exploded"), _body()])

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(2), ask
    )

    assert spent == 2
    # The failed direction keeps what the draft gave it and publishes.
    assert developed[0]["title"] == "Direction 0"
    assert developed[0]["importance"] == "Why direction 0 matters."
    assert developed[0]["sub_topics"] == []
    assert developed[1]["sub_topics"]


async def test_a_field_the_writer_omitted_keeps_the_draft_s_own() -> None:
    """json_object mode enforces no required field, so a gap costs a field."""
    ask = AsyncMock(return_value={"sub_topics": _body()["sub_topics"]})

    developed, _ = await calls.develop_research_directions(
        _context(), _drafted(1), ask
    )

    assert developed[0]["importance"] == "Why direction 0 matters."
    assert developed[0]["sub_topics"]


async def test_a_direction_the_draft_developed_is_not_bought_twice() -> None:
    """A model that ignored the ask and wrote the body already did the work."""
    ask = AsyncMock(return_value=_body())
    drafted = _drafted(2)
    drafted[0] = {**drafted[0], **_body(), "title": "Direction 0"}

    developed, spent = await calls.develop_research_directions(
        _context(), drafted, ask
    )

    assert spent == 1
    assert ask.await_count == 1
    assert developed[0]["title"] == "Direction 0"


async def test_a_half_written_direction_is_still_bought_its_call() -> None:
    """One placeholder sub-topic is not a developed direction.

    A schema-enforcing provider requires every field whatever the prompt
    asks, so "the draft already wrote it" has to mean the whole body.
    """
    ask = AsyncMock(return_value=_body())
    drafted = _drafted(1)
    drafted[0]["sub_topics"] = [{"title": "Placeholder"}]

    _, spent = await calls.develop_research_directions(_context(), drafted, ask)

    assert spent == 1


async def test_every_call_is_told_the_whole_set_of_directions() -> None:
    """Six concurrent writers with no sight of each other repeat themselves."""
    ask = AsyncMock(return_value=_body())

    await calls.develop_research_directions(_context(), _drafted(3), ask)

    prompt = ask.await_args_list[0].kwargs["prompt"]
    assert "Direction 0" in prompt
    assert "Direction 1" in prompt
    assert "Direction 2" in prompt


async def test_the_wave_is_attributed_to_its_own_telemetry_sub_phase() -> None:
    """Folded into the node's bucket, the draft stops being measurable."""

    async def _record(**_: Any) -> dict[str, Any]:
        record_call("test/model", ModelCallStats(calls=1))
        return _body()

    with scoped_telemetry("research_overview") as accumulator:
        record_call("test/model", ModelCallStats(calls=1))
        await calls.develop_research_directions(
            _context(), _drafted(2), _record
        )

    snapshot = accumulator.snapshot()
    assert snapshot["research_overview::test/model"]["calls"] == 1
    assert snapshot["research_overview.directions::test/model"]["calls"] == 2


@pytest.mark.parametrize("directions", [None, "not a list", {}])
async def test_a_malformed_directions_value_buys_nothing(
    directions: Any,
) -> None:
    """The wave never turns a malformed draft into provider requests."""
    ask = AsyncMock(return_value=_body())

    developed, spent = await calls.develop_research_directions(
        _context(), directions, ask
    )

    assert developed == directions
    assert spent == 0
    ask.assert_not_awaited()


async def _research_overview_directions_run_overview_node(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> dict[str, Any]:
    """Runs the node against a canned LLM response; returns its state delta."""
    fake = AsyncMock(return_value=response)
    monkeypatch.setattr(ro, "call_llm_json", fake)
    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    return await ro.research_overview_node(state)


def _direction_response(direction: dict[str, Any]) -> dict[str, Any]:
    """A minimal overview response carrying exactly one research direction."""
    return {"overview": {"summary": "S", "research_directions": [direction]}}


async def test_sub_topics_pass_through_when_well_formed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MO-1: a well-formed direction's sub-topic survives intact."""
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {
                    "title": "Sub-topic A",
                    "why": "Because Y.",
                    "what": "Investigate Z.",
                    "example_idea": "Knock Z down and read out Y.",
                    "specific_questions": ["Does Z cause Y?"],
                }
            ],
        }
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"] == [
        {
            "title": "Sub-topic A",
            "why": "Because Y.",
            "what": "Investigate Z.",
            "example_idea": "Knock Z down and read out Y.",
            "specific_questions": ["Does Z cause Y?"],
        }
    ]


async def test_sub_topics_degrade_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A json_object-mode response omitting sub_topics never raises.

    The schema declares it required, but nothing enforces that
    server-side under the downgrade, so the model may still omit it --
    this must degrade to [], the same pattern
    ``_validate_research_contacts`` already follows for a missing field.
    """
    response = _direction_response(
        {"title": "T", "importance": "I", "suggested_experiments": ["E"]}
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"] == []


async def test_recent_findings_passes_through_when_well_formed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MO-12: a well-formed recent_findings paragraph survives intact."""
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "recent_findings": "Prior work established X.",
        }
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["recent_findings"] == "Prior work established X."


async def test_recent_findings_degrades_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A json_object-mode response omitting recent_findings never raises.

    The schema declares it required, but nothing enforces that
    server-side under the downgrade, so the model may still omit it --
    this must degrade to "", the same pattern
    ``_validate_research_contacts`` already follows for a missing field.
    """
    response = _direction_response(
        {"title": "T", "importance": "I", "suggested_experiments": ["E"]}
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["recent_findings"] == ""


async def test_sub_topics_are_capped_at_the_schema_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """More sub-topics than the schema allows are capped, not trusted.

    json_object mode does not enforce ``maxItems`` server-side, so a
    non-conforming response is capped here defensively -- the same
    reason ``_validate_knowledge_base`` slices to its own max rather
    than accepting whatever the model returns.
    """
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {
                    "title": f"Topic {i}",
                    "why": "w",
                    "what": "w",
                    "specific_questions": [f"q{n}" for n in range(6)],
                }
                for i in range(6)
            ],
        }
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    sub_topics = out["research_overview"]["overview"]["research_directions"][0][
        "sub_topics"
    ]
    assert len(sub_topics) == 4
    assert [t["title"] for t in sub_topics] == [
        "Topic 0",
        "Topic 1",
        "Topic 2",
        "Topic 3",
    ]
    assert len(sub_topics[0]["specific_questions"]) == 4


async def test_malformed_sub_topics_are_dropped_not_crashed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-dict sub-topic, or non-list questions, degrade, not raise."""
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {"title": "ok", "why": "w", "what": "w"},
                "not a dict",
                {
                    "title": "ok2",
                    "why": "w",
                    "what": "w",
                    "specific_questions": "not a list",
                },
            ],
        }
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    sub_topics = out["research_overview"]["overview"]["research_directions"][0][
        "sub_topics"
    ]
    assert [t["title"] for t in sub_topics] == ["ok", "ok2"]
    assert sub_topics[0]["specific_questions"] == []
    assert sub_topics[1]["specific_questions"] == []


async def test_example_idea_degrades_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7: a sub-topic omitting ``example_idea`` never raises.

    The json_object downgrade omits required fields, so the field is
    read the same defensive way its ``why``/``what`` siblings are.
    """
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [{"title": "Sub-topic A", "why": "w", "what": "w"}],
        }
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"][0]["example_idea"] == ""


async def test_research_directions_are_capped_at_the_schema_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F5: more directions than the published exemplar carries are capped.

    Raising the asked-for count raises the response's size with it, and
    this node's budget is already at the escalation ladder's ceiling, so
    an over-producing response is sliced here rather than trusted -- the
    same reason the sub-topic layer above is.
    """
    directions = [
        {
            "title": f"Direction {i}",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [],
        }
        for i in range(9)
    ]
    response = {"overview": {"summary": "S", "research_directions": directions}}

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    kept = out["research_overview"]["overview"]["research_directions"]
    assert len(kept) == RESEARCH_OVERVIEW_MAX_DIRECTIONS
    assert kept[0]["title"] == "Direction 0"


def test_full_text_on_the_record_never_reaches_the_corpus() -> None:
    """A source contributes its abstract, never its downloaded full text.

    ``pubmed_search_with_fulltext`` attaches PMC full text to
    ``Article.content`` for the open-access share of a run's sources
    (157 of 239 analyzed articles, measured over six real runs, averaging
    ~14,000 characters). Sending that instead of the abstract is the
    obvious way to buy the knowledge base more detail and the wrong one:
    the corpus is already nearly the whole prompt of the knowledge base's
    own calls, which resend it once per theme, so a full-text corpus
    is an order of magnitude past any context this chain offers.
    """
    articles = [
        make_article(
            title="P1",
            source="pubmed",
            abstract="The abstract as retrieved.",
            content="FULL TEXT BODY " * 2000,
            used_in_analysis=True,
        )
    ]

    corpus = ev._build_evidence_corpus(articles)
    formatted = ev._format_evidence_corpus(corpus)

    entry = next(iter(corpus.values()))
    assert entry["abstract"] == "The abstract as retrieved."
    assert "content" not in entry
    assert "FULL TEXT BODY" not in formatted


def test_the_cap_passes_a_real_abstract_through_whole() -> None:
    """The per-source cap trims a tail, and only a tail.

    Real retrieved abstracts average ~1,590 characters and only two of
    239 exceeded this cap, by 80 and 306 characters. An abstract at the
    long end of that distribution must therefore arrive intact -- if a
    later edit lowers the cap into the distribution, the corpus starts
    losing the end of ordinary abstracts silently.
    """
    long_real_abstract = "a" * 2596
    over_cap = "b" * (ev._EVIDENCE_ABSTRACT_CHARS + 306)
    articles = [
        make_article(
            title="P1", abstract=long_real_abstract, used_in_analysis=True
        ),
        make_article(title="P2", abstract=over_cap, used_in_analysis=True),
    ]

    entries = list(ev._build_evidence_corpus(articles).values())

    assert entries[0]["abstract"] == long_real_abstract
    assert len(entries[1]["abstract"]) == ev._EVIDENCE_ABSTRACT_CHARS


def test_the_corpus_is_capped_at_the_measured_source_count() -> None:
    """One source past the cap is dropped, not sent.

    The corpus grows across cycles -- every parsed search result is marked
    ``used_in_analysis`` and deep-verification probes append more articles
    every cycle -- so without a cap the interim overview's prompt grows
    without bound. Production extended run ``bc77950f`` reached 126,975
    prompt tokens and could not be answered.
    """
    articles = [
        make_article(
            title=f"P{index}",
            abstract="An abstract.",
            used_in_analysis=True,
        )
        for index in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES + 1)
    ]

    corpus = ev._build_evidence_corpus(articles)

    assert len(corpus) == ev.RESEARCH_OVERVIEW_MAX_SOURCES


def test_the_capped_corpus_keeps_contiguous_evidence_ids() -> None:
    """Ids stay ``evidence-1..N`` after the cap drops the tail.

    ``_validate_knowledge_base`` resolves the topics the model cited back
    to their source metadata by evidence id, so a gap in the numbering
    silently drops a cited topic's provenance from the report.
    """
    articles = [
        make_article(title=f"P{index}", used_in_analysis=True)
        for index in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES + 25)
    ]

    corpus = ev._build_evidence_corpus(articles)

    expected = [
        f"evidence-{i + 1}" for i in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES)
    ]
    assert list(corpus) == expected
    assert [entry["evidence_id"] for entry in corpus.values()] == expected


def test_every_source_survives_a_corpus_far_over_the_cap() -> None:
    """The cap is applied round-robin, so no source type is dropped whole.

    Selecting the cap's worth of sources by a global ``retrieval_score``
    sort would drop every web result: ``_retrieval_score`` floors web
    articles at a normalized 0.0, so they sort below every indexed paper
    however well they match. Round-robin is what keeps the breadth.
    """
    sources = ("pubmed", "openalex", "web")
    articles = [
        make_article(title=f"{source}-{index}", source=source)
        for index in range(100)
        for source in sources
    ]
    for article in articles:
        article.used_in_analysis = True

    corpus = ev._build_evidence_corpus(articles)

    assert len(corpus) == ev.RESEARCH_OVERVIEW_MAX_SOURCES
    assert {entry["source"] for entry in corpus.values()} == set(sources)


def test_the_capped_selection_is_deterministic() -> None:
    """The same articles select the same corpus every time.

    The selection is positional (round-robin over first-appearance source
    order), never randomized or score-sorted, so a resumed run and its
    checkpoint predecessor build the identical corpus.
    """
    articles = [
        make_article(
            title=f"P{index}",
            source=("pubmed", "openalex", "web")[index % 3],
            used_in_analysis=True,
        )
        for index in range(ev.RESEARCH_OVERVIEW_MAX_SOURCES + 40)
    ]

    first = ev._build_evidence_corpus(articles)
    second = ev._build_evidence_corpus(articles)

    assert first == second
    assert [entry["title"] for entry in first.values()] == [
        entry["title"] for entry in second.values()
    ]


async def _research_overview_unexpected_directions_run_overview_node(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> dict[str, Any]:
    """Runs the node against a canned LLM response; returns its state delta."""
    fake = AsyncMock(return_value=response)
    monkeypatch.setattr(ro, "call_llm_json", fake)
    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    return await ro.research_overview_node(state)


async def test_unexpected_research_directions_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed unexpected direction survives into the state delta."""
    response = {
        "overview": {"summary": "S", "research_directions": []},
        "unexpected_research_directions": [
            {
                "title": "Nuclear LOXL2 as a Histone Modifier",
                "description": (
                    "Beyond crosslinking collagen, nuclear-translocated"
                    " LOXL2 may act as a histone aminooxidase."
                ),
            }
        ],
    }
    out = await _research_overview_unexpected_directions_run_overview_node(
        monkeypatch, response
    )

    directions = out["research_overview"]["unexpected_research_directions"]
    assert directions == [
        {
            "title": "Nuclear LOXL2 as a Histone Modifier",
            "description": (
                "Beyond crosslinking collagen, nuclear-translocated"
                " LOXL2 may act as a histone aminooxidase."
            ),
        }
    ]


async def test_absent_unexpected_research_directions_defaults_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response that omits the field degrades to an empty list, not KeyError.

    The schema declares it required, but nothing enforces that server-side
    under production's json_object downgrade, so a live response may still
    omit it.
    """
    response = {"overview": {"summary": "S", "research_directions": []}}
    out = await _research_overview_unexpected_directions_run_overview_node(
        monkeypatch, response
    )

    assert out["research_overview"]["unexpected_research_directions"] == []
