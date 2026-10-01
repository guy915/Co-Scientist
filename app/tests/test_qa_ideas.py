"""The idea search tool, and the one tool round the Q&A stream allows.

Covers ``app.qa.ideas`` (matching, rendering, and reassembling streamed
tool-call fragments) and ``app.qa.stream``'s loop: a model that answers
straight away costs one round, a model that asks for idea text gets it, and
a model that does both keeps the answer it already started.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app import qa
from app.qa import ideas as qa_ideas


def _idea(title: str, **fields: Any) -> dict[str, Any]:
    base = {
        "title": title,
        "statement": "a statement",
        "mechanism": "a mechanism",
        "elo_rating": 1200,
        "status": "active",
    }
    return {**base, **fields}


# ---------------------------------------------------------------------------
# search_ideas
# ---------------------------------------------------------------------------


def test_search_returns_the_idea_whose_title_matches() -> None:
    ideas = [
        _idea("Mitochondrial calcium buffering"),
        _idea("Ferroptosis escape via lipid repair"),
    ]
    results = qa_ideas.search_ideas(ideas, "lipid repair", 1)
    assert results[0]["title"] == "Ferroptosis escape via lipid repair"


def test_a_title_match_outranks_a_body_that_repeats_the_words() -> None:
    # A question naming an idea should return that idea, not whichever body
    # happens to mention the words most often.
    ideas = [
        _idea("Unrelated", statement="lipid lipid lipid repair repair repair"),
        _idea("Lipid repair"),
    ]
    assert (
        qa_ideas.search_ideas(ideas, "lipid repair", 1)[0]["title"]
        == "Lipid repair"
    )


def test_search_returns_the_ideas_bodies_not_just_their_titles() -> None:
    # The whole point of the tool: the index already carries titles.
    result = qa_ideas.search_ideas([_idea("H")], "H", 1)[0]
    assert result["Statement"] == "a statement"
    assert result["Mechanism"] == "a mechanism"


def test_a_query_matching_nothing_falls_back_to_the_leaders() -> None:
    # "Nothing found" for a run that has ideas reads to the model as a run
    # with no ideas; the leaders are a truthful answer to a bad query.
    ideas = [_idea("Alpha"), _idea("Beta")]
    results = qa_ideas.search_ideas(ideas, "zzzz qqqq", 1)
    assert [r["title"] for r in results] == ["Alpha"]


def test_the_result_count_is_clamped_however_the_model_asks() -> None:
    ideas = [_idea(f"Idea {n}") for n in range(20)]
    assert len(qa_ideas.search_ideas(ideas, "idea", 99)) == 5
    assert len(qa_ideas.search_ideas(ideas, "idea", 0)) == 1
    assert len(qa_ideas.search_ideas(ideas, "idea", "three")) == 3
    assert len(qa_ideas.search_ideas(ideas, "idea", None)) == 3


def test_one_long_idea_cannot_fill_the_whole_result() -> None:
    result = qa_ideas.search_ideas([_idea("H", statement="x" * 5_000)], "H")[0]
    assert len(result["Statement"]) < 1_300


# ---------------------------------------------------------------------------
# run_tool_call
# ---------------------------------------------------------------------------


def test_a_malformed_argument_blob_still_searches() -> None:
    # Failing a turn over a truncated JSON fragment is worse than treating
    # the fragment as the query it plainly is.
    out = qa_ideas.run_tool_call(
        {"name": "search_ideas", "arguments": "lipid repair"},
        [_idea("Lipid repair")],
    )
    assert json.loads(out)["ideas"][0]["title"] == "Lipid repair"


def test_an_unknown_tool_name_is_reported_not_raised() -> None:
    out = qa_ideas.run_tool_call({"name": "rm_rf", "arguments": "{}"}, [])
    assert "unknown tool" in json.loads(out)["error"]


# ---------------------------------------------------------------------------
# accumulate_tool_calls
# ---------------------------------------------------------------------------


def _fragment(index: int, **fields: Any) -> SimpleNamespace:
    function = SimpleNamespace(
        name=fields.get("name"), arguments=fields.get("arguments")
    )
    return SimpleNamespace(index=index, id=fields.get("id"), function=function)


def test_arguments_split_across_chunks_are_reassembled() -> None:
    # Providers stream a tool call the way they stream text: the name in one
    # chunk, the arguments in pieces across the next several.
    calls: dict[int, dict[str, Any]] = {}
    qa_ideas.accumulate_tool_calls(
        calls,
        SimpleNamespace(
            tool_calls=[_fragment(0, id="c1", name="search_ideas")]
        ),
    )
    for piece in ('{"que', 'ry": "lip', 'id"}'):
        qa_ideas.accumulate_tool_calls(
            calls, SimpleNamespace(tool_calls=[_fragment(0, arguments=piece)])
        )

    assert calls[0] == {
        "id": "c1",
        "name": "search_ideas",
        "arguments": '{"query": "lipid"}',
    }


def test_a_delta_carrying_no_tool_calls_changes_nothing() -> None:
    calls: dict[int, dict[str, Any]] = {}
    qa_ideas.accumulate_tool_calls(calls, SimpleNamespace(content="hello"))
    assert calls == {}


# ---------------------------------------------------------------------------
# the streaming tool round (qa.stream)
# ---------------------------------------------------------------------------


def _chunk(content: str | None = None, tool_calls: Any = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _scripted_litellm(rounds: list[list[Any]]) -> Any:
    """A fake litellm streaming a different chunk list per call.

    Records each round's request so the test can assert on what was sent --
    which tools were offered, and what the second round was told.
    """
    sent: list[dict[str, Any]] = []

    async def _acompletion(**kwargs: Any) -> Any:
        sent.append(kwargs)

        async def _stream() -> Any:
            for chunk in rounds[len(sent) - 1]:
                yield chunk

        return _stream()

    return SimpleNamespace(acompletion=_acompletion, sent=sent)


def _drain(generator: Any) -> list[tuple[str, str]]:
    import asyncio

    async def _collect() -> list[tuple[str, str]]:
        return [delta async for delta in generator]

    return asyncio.run(_collect())


def _search_call_chunk() -> Any:
    return _chunk(
        tool_calls=[
            _fragment(
                0,
                id="c1",
                name="search_ideas",
                arguments='{"query": "lipid"}',
            )
        ]
    )


def test_a_model_that_answers_directly_makes_one_call(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    # The tool is offered on every question, so a question that does not
    # need it must not cost a second round.
    fake = _scripted_litellm([[_chunk("The run "), _chunk("is going well.")]])
    monkeypatch.setitem(sys.modules, "litellm", fake)

    deltas = _drain(
        qa.stream_llm_deltas("model", "sys", "how is it?", [_idea("H")])
    )

    assert deltas == [("chunk", "The run "), ("chunk", "is going well.")]
    assert len(fake.sent) == 1


def test_a_model_that_asks_for_ideas_is_given_them_and_answers(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    fake = _scripted_litellm(
        [[_search_call_chunk()], [_chunk("Idea one says X.")]]
    )
    monkeypatch.setitem(sys.modules, "litellm", fake)

    deltas = _drain(
        qa.stream_llm_deltas(
            "model", "sys", "what does it say?", [_idea("Lipid repair")]
        )
    )

    assert deltas == [("chunk", "Idea one says X.")]
    second = fake.sent[1]
    tool_message = second["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "Lipid repair" in tool_message["content"]
    # The second round is offered no tools, so it has to answer rather than
    # search again -- one round is the whole budget.
    assert "tools" not in second


def test_the_second_round_keeps_the_budget_and_deadline(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    # A tool round that forgot the token floor fails exactly the way the
    # first round would have, only later and with the search already paid for.
    fake = _scripted_litellm([[_search_call_chunk()], [_chunk("answer")]])
    monkeypatch.setitem(sys.modules, "litellm", fake)

    _drain(qa.stream_llm_deltas("model", "sys", "q", [_idea("H")]))

    assert fake.sent[0]["max_tokens"] == fake.sent[1]["max_tokens"]
    assert fake.sent[0]["timeout"] == fake.sent[1]["timeout"]


def test_a_tool_call_after_the_answer_started_is_ignored(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    # The scientist is already reading that answer; a second one would be
    # appended to the middle of it.
    fake = _scripted_litellm(
        [[_chunk("Half an answer."), _search_call_chunk()], [_chunk("never")]]
    )
    monkeypatch.setitem(sys.modules, "litellm", fake)

    deltas = _drain(qa.stream_llm_deltas("model", "sys", "q", [_idea("H")]))

    assert deltas == [("chunk", "Half an answer.")]
    assert len(fake.sent) == 1


def test_a_run_with_no_ideas_is_offered_no_tool(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    fake = _scripted_litellm([[_chunk("Nothing yet.")]])
    monkeypatch.setitem(sys.modules, "litellm", fake)

    _drain(qa.stream_llm_deltas("model", "sys", "q", []))

    assert "tools" not in fake.sent[0]


def test_a_nameless_tool_fragment_does_not_trigger_a_round(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    # A provider that opened a tool call and then changed its mind leaves a
    # fragment with no name behind; it is not a call.
    fake = _scripted_litellm(
        [[_chunk(tool_calls=[_fragment(0, arguments="{}")])], [_chunk("no")]]
    )
    monkeypatch.setitem(sys.modules, "litellm", fake)

    assert _drain(qa.stream_llm_deltas("model", "sys", "q", [_idea("H")])) == []
    assert len(fake.sent) == 1
