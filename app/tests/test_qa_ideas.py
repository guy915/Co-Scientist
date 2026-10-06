from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import app.qa.manifest as qa_ideas
from app import qa
from tests._llm_fake_backend import install_completion_backend


def _idea(title: str, **fields: Any) -> dict[str, Any]:
    base = {
        "title": title,
        "statement": "a statement",
        "mechanism": "a mechanism",
        "elo_rating": 1200,
        "status": "active",
    }
    return {**base, **fields}


def test_search_ranks_title_matches_and_returns_the_idea_bodies() -> None:
    ideas = [
        _idea("Unrelated", statement="lipid lipid lipid repair repair repair"),
        _idea("Mitochondrial calcium buffering"),
        _idea("Lipid repair"),
    ]
    results = qa_ideas.search_ideas(ideas, "lipid repair", 1)
    assert results[0]["title"] == "Lipid repair"
    assert results[0]["Statement"] == "a statement"
    assert results[0]["Mechanism"] == "a mechanism"


def test_a_query_matching_nothing_falls_back_to_the_leaders() -> None:
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


def test_a_malformed_argument_blob_still_searches() -> None:
    out = qa_ideas.run_tool_call(
        {"name": "search_ideas", "arguments": "lipid repair"},
        [_idea("Lipid repair")],
    )
    assert json.loads(out)["ideas"][0]["title"] == "Lipid repair"


def test_an_unknown_tool_name_is_reported_not_raised() -> None:
    out = qa_ideas.run_tool_call({"name": "rm_rf", "arguments": "{}"}, [])
    assert "unknown tool" in json.loads(out)["error"]


def _fragment(index: int, **fields: Any) -> SimpleNamespace:
    function = SimpleNamespace(
        name=fields.get("name"), arguments=fields.get("arguments")
    )
    return SimpleNamespace(index=index, id=fields.get("id"), function=function)


def _chunk(content: str | None = None, tool_calls: Any = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _scripted_litellm(rounds: list[list[Any]]) -> Any:
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
    fake = _scripted_litellm([[_chunk("The run "), _chunk("is going well.")]])
    install_completion_backend(monkeypatch, (fake).acompletion)

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
    install_completion_backend(monkeypatch, (fake).acompletion)

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
    assert "tools" not in second
    assert fake.sent[0]["max_tokens"] == second["max_tokens"]
    assert fake.sent[0]["timeout"] == second["timeout"]


def test_a_tool_call_after_the_answer_started_is_ignored(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    fake = _scripted_litellm(
        [[_chunk("Half an answer."), _search_call_chunk()], [_chunk("never")]]
    )
    install_completion_backend(monkeypatch, (fake).acompletion)

    deltas = _drain(qa.stream_llm_deltas("model", "sys", "q", [_idea("H")]))

    assert deltas == [("chunk", "Half an answer.")]
    assert len(fake.sent) == 1


def test_a_run_with_no_ideas_is_offered_no_tool(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    fake = _scripted_litellm([[_chunk("Nothing yet.")]])
    install_completion_backend(monkeypatch, (fake).acompletion)

    _drain(qa.stream_llm_deltas("model", "sys", "q", []))

    assert "tools" not in fake.sent[0]


def test_run_artifact_lookup_uses_same_bounded_two_round_stream(
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    scripted = _scripted_litellm(
        [
            [
                _chunk(
                    tool_calls=[
                        _fragment(
                            0,
                            id="run_lookup",
                            name="search_run_artifacts",
                            arguments='{"section":"meta_review"}',
                        )
                    ]
                )
            ],
            [_chunk(content="Replication remains necessary.")],
        ]
    )
    install_completion_backend(monkeypatch, scripted.acompletion)
    output = _drain(
        qa.stream_llm_deltas(
            "model",
            "sys",
            "What did the synthesis conclude?",
            [],
            {"meta_review": [{"conclusion": "Replication remains necessary"}]},
        )
    )
    assert output == [("chunk", "Replication remains necessary.")]
    assert len(scripted.sent) == 2
    assert (
        scripted.sent[0]["tools"][0]["function"]["name"]
        == "search_run_artifacts"
    )
    assert "tools" not in scripted.sent[1]
    messages = scripted.sent[1]["messages"]
    assert messages[-1]["tool_call_id"] == "run_lookup"
    assert "Replication remains necessary" in messages[-1]["content"]
