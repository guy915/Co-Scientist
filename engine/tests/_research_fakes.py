"""Fakes standing in for the research loop's two ports.

The loop states what it needs as protocols precisely so a test can
supply them, which is what lets every research test run with no
provider key and no search service -- CI has neither. Shared here
because both the loop's own tests and the descent tests script the same
two fakes.
"""

from __future__ import annotations

from collections.abc import Sequence

from co_scientist.research import (
    Document,
    ExtractedFinding,
    Extraction,
    Finding,
    ResearchBudget,
    SourceHit,
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
