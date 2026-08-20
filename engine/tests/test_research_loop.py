"""What the research loop guarantees, with no network and no model.

Both ports are fakes here, which is the point of the ports: the loop's
behaviour -- how wide it goes, when it stops, what it refuses to lose --
is testable without a provider key or a search service, and CI has
neither.

The properties pinned below are the ones that would fail silently in
production if they regressed: a budget that stops bounding work, a
descent that keeps going after everything came back empty, a question
dropped instead of declined, and evidence that forgets which question
fetched it.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Sequence

import pytest

from co_scientist.research import (
    CallStatus,
    Document,
    ExtractedFinding,
    Extraction,
    Finding,
    ResearchBudget,
    SourceHit,
    StopReason,
    ThreadStatus,
    conduct_research,
)


class FakeRetrieval:
    """A search service that answers from a script.

    Attributes:
        hits_by_source: What each source returns for any query.
        failing_sources: Sources that raise instead of answering.
        unreadable: Locators whose text cannot be fetched.
        queries: Every query issued, in order.
    """

    def __init__(
        self,
        hits_by_source: dict[str, list[SourceHit]] | None = None,
        failing_sources: set[str] | None = None,
        unreadable: set[str] | None = None,
    ) -> None:
        """Configure the scripted answers."""
        self.hits_by_source = hits_by_source or {}
        self.failing_sources = failing_sources or set()
        self.unreadable = unreadable or set()
        self.queries: list[str] = []

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Return this source's scripted hits, or raise."""
        self.queries.append(query)
        if source in self.failing_sources:
            raise RuntimeError(f"{source} is unreachable")
        return self.hits_by_source.get(source, [])[:limit]

    async def read(self, *, locator: str) -> str | None:
        """Return document text unless the locator is unreadable."""
        if locator in self.unreadable:
            return None
        return f"full text of {locator}"


class FakeModel:
    """A model that answers from a script.

    Attributes:
        stances: What stance planning returns.
        follow_ups_by_question: Follow-ups each question raises.
        barren: Questions that yield no findings.
        exploding: Questions whose extraction raises.
        extracted: Every question extraction ran for, in order.
    """

    def __init__(
        self,
        stances: Sequence[str] = ("mechanism", "prior art"),
        follow_ups_by_question: dict[str, list[str]] | None = None,
        barren: set[str] | None = None,
        exploding: set[str] | None = None,
    ) -> None:
        """Configure the scripted answers."""
        self.stances = tuple(stances)
        self.follow_ups_by_question = follow_ups_by_question or {}
        self.barren = barren or set()
        self.exploding = exploding or set()
        self.extracted: list[str] = []
        self.documents_seen: list[Document] = []

    async def plan_stances(self, *, goal: str, limit: int) -> Sequence[str]:
        """Return the scripted stances, within the limit."""
        return self.stances[:limit]

    async def ask_questions(
        self, *, goal: str, stance: str, limit: int
    ) -> Sequence[str]:
        """Ask one question per stance, named after the stance."""
        return [f"what does {stance} say about {goal}?"][:limit]

    async def to_query(self, *, question: str) -> str:
        """Render the question as a query."""
        return f"query::{question}"

    async def extract(
        self, *, question: str, documents: Sequence[Document]
    ) -> Extraction:
        """Return one finding per document, unless scripted otherwise."""
        self.extracted.append(question)
        self.documents_seen.extend(documents)
        if question in self.exploding:
            raise RuntimeError("extraction failed")
        follow_ups = tuple(self.follow_ups_by_question.get(question, []))
        if question in self.barren:
            return Extraction(findings=(), follow_ups=follow_ups)
        findings = tuple(
            ExtractedFinding(
                text=f"finding from {doc.hit.locator}",
                locator=doc.hit.locator,
                span=f"span from {doc.hit.locator}",
            )
            for doc in documents
        )
        return Extraction(findings=findings, follow_ups=follow_ups)

    async def compress(
        self, *, question: str, findings: Sequence[Finding]
    ) -> str:
        """Summarise a thread by counting what it found."""
        return f"{len(findings)} findings for {question}"


def _hits(*locators: str) -> list[SourceHit]:
    """Build ranked hits for the given locators."""
    return [
        SourceHit(
            locator=locator,
            title=f"title {locator}",
            snippet=f"snippet {locator}",
            rank=index,
        )
        for index, locator in enumerate(locators)
    ]


def _budget(**overrides: object) -> ResearchBudget:
    """A small default budget, overridable per test."""
    defaults: dict[str, object] = {
        "depth": 2,
        "breadth": 2,
        "concurrency": 2,
        "hits_per_question": 2,
        "sources": ("pubmed",),
    }
    defaults.update(overrides)
    return ResearchBudget(**defaults)  # type: ignore[arg-type]


def test_breadth_halves_on_descent_and_stops_at_the_floor() -> None:
    budget = ResearchBudget(depth=4, breadth=8, sources=("pubmed",))

    second = budget.descend()
    assert second is not None
    assert (second.depth, second.breadth) == (3, 4)

    third = second.descend()
    assert third is not None
    assert (third.depth, third.breadth) == (2, 2)

    fourth = third.descend()
    assert fourth is not None
    # Floored rather than halved to 1: a one-question level is a lookup.
    assert (fourth.depth, fourth.breadth) == (1, 2)
    assert fourth.descend() is None


def test_max_threads_is_quotable_before_anything_is_spent() -> None:
    budget = ResearchBudget(depth=3, breadth=8, sources=("pubmed",))

    # 8 + 4 + 2, summed rather than multiplied: follow-ups are pooled per
    # level, so the bound is linear in depth.
    assert budget.max_threads() == 14


@pytest.mark.parametrize(
    "kwargs",
    [
        {"depth": 0},
        {"breadth": 0},
        {"concurrency": 0},
        {"hits_per_question": 0},
        {"sources": ()},
    ],
)
def test_a_budget_that_funds_nothing_is_refused(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _budget(**kwargs)


async def test_first_level_is_planned_one_question_per_stance() -> None:
    model = FakeModel(stances=("mechanism", "prior art", "contradictions"))
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="reverse liver fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=3),
    )

    assert result.stances == ("mechanism", "prior art", "contradictions")
    stances_researched = {t.question.stance for t in result.threads}
    assert stances_researched == set(result.stances)


async def test_a_finding_is_identified_by_the_question_that_found_it() -> None:
    """The same span under two questions is two findings, not one.

    This is the identity decision that cannot be revised once rows
    exist: a locator alone does not identify evidence, because the
    reason it was fetched is part of what it is.
    """
    model = FakeModel(stances=("mechanism", "prior art"))
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="reverse liver fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=2, hits_per_question=1),
    )

    findings = result.findings
    assert len(findings) == 2
    assert {f.locator for f in findings} == {"doc-a"}
    assert {f.span for f in findings} == {"span from doc-a"}
    # Same document, same span, different question -- and so different
    # evidence, with different ids.
    assert findings[0].id != findings[1].id


async def test_follow_ups_become_the_next_level() -> None:
    model = FakeModel(
        stances=("mechanism",),
        follow_ups_by_question={
            "what does mechanism say about fibrosis?": [
                "which cell type drives it?"
            ]
        },
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=2, breadth=1, breadth_floor=1),
    )

    assert result.levels_run == 2
    second_level = [t for t in result.threads if t.depth == 2]
    assert [t.question.text for t in second_level] == [
        "which cell type drives it?"
    ]
    # The descent is a tree: the follow-up remembers what raised it.
    assert second_level[0].question.parent_id is not None


async def test_descent_stops_when_a_whole_level_finds_nothing() -> None:
    """An unreachable search service looks exactly like this."""
    question = "what does mechanism say about fibrosis?"
    model = FakeModel(
        stances=("mechanism",),
        barren={question},
        follow_ups_by_question={question: ["a question from nothing"]},
    )
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=3, breadth=1, breadth_floor=1),
    )

    assert result.stop_reason is StopReason.NO_RESULTS
    assert result.levels_run == 1
    # The follow-up existed and was deliberately not researched.
    assert model.extracted == [question]


async def test_overflow_questions_are_declined_not_dropped() -> None:
    model = FakeModel()
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=2),
        seed_questions=["q1", "q2", "q3", "q4"],
    )

    declined = result.declined()
    assert [t.question.text for t in declined] == ["q3", "q4"]
    # Told what to ask for, not merely that it asked for too much.
    assert all(t.retry_breadth == 4 for t in declined)
    assert all(t.note for t in declined)
    # Recorded at the level that refused them, so a question declined at
    # the first level stays distinguishable from one declined deeper.
    assert all(t.depth == 1 for t in declined)
    assert model.extracted == ["q1", "q2"]


async def test_one_unreachable_source_does_not_veto_the_others() -> None:
    model = FakeModel()
    retrieval = FakeRetrieval(
        hits_by_source={"corpus": _hits("doc-a")},
        failing_sources={"pubmed"},
    )

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=1, sources=("pubmed", "corpus")),
        seed_questions=["q1"],
    )

    by_source = {call.source: call for call in result.calls}
    assert by_source["pubmed"].status is CallStatus.FAILED
    assert by_source["pubmed"].error
    assert by_source["corpus"].status is CallStatus.OK
    assert len(result.findings) == 1


async def test_results_the_budget_refused_are_recorded_as_refused() -> None:
    """Each source may answer in full; the evidence budget is global.

    Two sources returning two results each against a two-document
    budget means half of what came back is never read -- and which half
    has to stay on the record, since a replay has to reproduce the
    choice and not just its outcome.
    """
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
    # Seen and not read is a different fact from never seen.
    assert by_source["corpus"].admitted == ()
    assert by_source["corpus"].dropped == ("doc-c", "doc-d")


async def test_a_failing_thread_does_not_take_the_level_with_it() -> None:
    model = FakeModel(exploding={"q1"})
    retrieval = FakeRetrieval({"pubmed": _hits("doc-a")})

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=2),
        seed_questions=["q1", "q2"],
    )

    by_question = {t.question.text: t for t in result.threads}
    assert by_question["q1"].status is ThreadStatus.FAILED
    assert by_question["q1"].note
    assert by_question["q2"].status is ThreadStatus.OK


async def test_an_unfetchable_document_falls_back_to_its_snippet() -> None:
    model = FakeModel()
    retrieval = FakeRetrieval(
        hits_by_source={"pubmed": _hits("doc-a")},
        unreadable={"doc-a"},
    )

    result = await conduct_research(
        goal="fibrosis",
        model=model,
        retrieval=retrieval,
        budget=_budget(depth=1, breadth=1),
        seed_questions=["q1"],
    )

    assert [d.full_text for d in model.documents_seen] == [False]
    assert model.documents_seen[0].text == "snippet doc-a"
    # Still evidence, at snippet depth, rather than silently narrowed
    # reading.
    assert len(result.findings) == 1


async def test_the_loop_never_opens_more_threads_than_it_may() -> None:
    """However many follow-ups the model raises, the bound holds."""
    model = FakeModel(
        stances=("mechanism", "prior art", "contradictions", "methods"),
        follow_ups_by_question={},
    )
    # Every question raises four follow-ups, whatever it was.
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
    # 4 + 2 + 2 under the floor.
    assert len(started) == 8


def test_the_package_depends_on_nothing_in_this_repo_but_itself() -> None:
    """The capability stays assignable only while it stays standalone.

    An agent takes this by supplying two adapters; the moment the package
    reaches back into a caller's module the assignment stops being an
    adapter and becomes a rewrite. That is a one-line regression to make
    and an invisible one to notice, so it is pinned here.
    """
    package = pathlib.Path(conduct_research.__module__.replace(".", "/"))
    root = pathlib.Path(__file__).parents[1] / "src" / package.parent
    borrowed: set[str] = set()
    for module in sorted(root.glob("*.py")):
        tree = ast.parse(module.read_text(), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                borrowed.add(node.module)
            elif isinstance(node, ast.Import):
                borrowed.update(alias.name for alias in node.names)

    outside = {
        name
        for name in borrowed
        if name.startswith("co_scientist")
        and not name.startswith("co_scientist.research")
    }
    assert not outside


class _Everything(dict):  # type: ignore[type-arg]
    """A dict that answers the same list for every key."""

    def __init__(self, value: list[str]) -> None:
        """Store the one answer."""
        super().__init__()
        self._value = value

    def get(self, key: object, default: object = None) -> list[str]:
        """Return the one answer, whatever was asked."""
        return self._value
