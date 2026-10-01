"""A paper the transcript already carries is not carried twice."""

from __future__ import annotations

import json
from typing import Any

from co_scientist.llm.tools.transcript import elide_repeated_papers


def _result(payload: Any) -> dict[str, Any]:
    """Builds one tool-result message carrying a JSON payload."""
    return {
        "role": "tool",
        "tool_call_id": "c1",
        "content": json.dumps(payload),
    }


def _paper(pmid: str, abstract: str = "A long abstract.") -> dict[str, Any]:
    """Builds one paper record as a search tool returns it."""
    return {"source_id": pmid, "title": f"Paper {pmid}", "abstract": abstract}


def test_a_repeat_keeps_its_identity_and_loses_its_body() -> None:
    """The second copy stays citable and stops costing tokens.

    Measured on a live drafting pass: 8 searches returned 94 records
    carrying 61 distinct papers, so 35% were abstracts the transcript
    already held -- in a loop where literature results are 96% of the
    transcript, and where the token ceiling rather than the turn count
    is what stops it.
    """
    messages = [
        _result({"results": [_paper("111"), _paper("222")]}),
        _result({"results": [_paper("222"), _paper("333")]}),
    ]

    elided = elide_repeated_papers(messages)

    assert elided == 1
    second = json.loads(messages[1]["content"])["results"]
    repeat = next(p for p in second if p["source_id"] == "222")
    fresh = next(p for p in second if p["source_id"] == "333")
    # Identity survives, so a citation still resolves.
    assert repeat["title"] == "Paper 222"
    assert "abstract" not in repeat
    assert "re-fetch" in repeat["elided"]
    assert fresh["abstract"] == "A long abstract."


def test_the_first_copy_is_left_whole() -> None:
    """Eliding the original would delete the evidence, not a duplicate."""
    messages = [_result({"results": [_paper("111")]})]

    assert elide_repeated_papers(messages) == 0
    assert json.loads(messages[0]["content"])["results"][0]["abstract"] == (
        "A long abstract."
    )


def test_a_dict_keyed_payload_is_handled_too() -> None:
    """PubMed returns records keyed by id, not as a list.

    Recognising a paper by its own fields rather than by the envelope
    around it is what makes this cover a source added later without
    anyone remembering to update it.
    """
    messages = [
        _result({"111": _paper("111")}),
        _result({"records": [_paper("111")]}),
    ]

    assert elide_repeated_papers(messages) == 1


def test_non_paper_tool_results_are_untouched() -> None:
    """A command's output is not a paper and must not be rewritten."""
    messages = [
        _result({"exit_code": 0, "stdout": "done"}),
        _result({"exit_code": 0, "stdout": "done"}),
    ]

    assert elide_repeated_papers(messages) == 0
    assert json.loads(messages[1]["content"])["stdout"] == "done"


def test_an_unparseable_result_is_skipped_not_dropped() -> None:
    """Plain-text tool output stays exactly as the tool produced it."""
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "not json"}]

    assert elide_repeated_papers(messages) == 0
    assert messages[0]["content"] == "not json"
