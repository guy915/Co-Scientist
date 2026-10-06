from __future__ import annotations

from co_scientist.research import (
    ThreadStatus,
    conduct_research,
)
from tests._research_fakes import FakeModel, FakeRetrieval, _budget, _hits


async def test_results_the_budget_refused_are_recorded_as_refused() -> None:
    """Replay needs the record of seen-but-unread results, not only accepted
    evidence."""
    model = FakeModel()
    retrieval = FakeRetrieval(
        {
            "pubmed": _hits("doc-a", "doc-b"),
            "corpus": _hits("doc-c", "doc-d"),
        }
    )

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(
            depth=1,
            breadth=1,
            hits_per_question=2,
            sources=("pubmed", "corpus"),
        ),
        seed_questions=["q1"],
    )

    by_source = {call.source: call for call in result.calls}
    assert by_source["pubmed"].admitted == ("doc-a", "doc-b")
    assert by_source["pubmed"].dropped == ()
    assert by_source["corpus"].admitted == ()
    assert by_source["corpus"].dropped == ("doc-c", "doc-d")


async def test_the_loop_never_opens_more_threads_than_it_may() -> None:
    model = FakeModel(
        stances=("mechanism", "prior art", "contradictions", "methods"),
        follow_ups_by_question={},
    )
    model.follow_ups_by_question = _Everything(
        ["f1", "f2", "f3", "f4", "f5", "f6"]
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})
    budget = _budget(depth=3, breadth=4)

    result = await conduct_research(
        goal="fibrosis", model=model, retrieval=retrieval, budget=budget
    )

    started = [
        t for t in result.threads if t.status is not ThreadStatus.DECLINED
    ]
    assert len(started) <= budget.max_threads()
    assert result.levels_run == 3
    assert len(started) == 8


class _Everything(dict):  # type: ignore[type-arg]
    """Fresh questions avoid exercising repeated-question termination instead
    of depth bounds."""

    def __init__(self, value: list[str]) -> None:
        super().__init__()
        self._value = value
        self._asked = 0

    def get(self, key: object, default: object = None) -> list[str]:
        self._asked += 1
        return [f"{text}-{self._asked}" for text in self._value]
