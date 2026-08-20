"""The two things a caller has to supply, and nothing else.

This package does not know how to search and does not know how to call a
model. It knows how to *sequence* those two, which is the part worth
sharing between agents. Everything provider-shaped arrives through the
protocols here.

Four things deliberately do not appear anywhere in this package, because
each one would tie it to a single caller and end its portability:

* MCP client imports -- retrieval arrives as a port.
* LLM dispatch imports -- the model port returns typed values, so JSON
  repair, retries and budget escalation stay the adapter's problem.
* Any run-tier to budget mapping -- the caller resolves ceilings.
* Any store write -- the result is returned, not persisted.

An adapter implementing these two protocols is what "assigning deep
research to an agent" means.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from co_scientist.research.artifacts import Finding, SourceHit


@dataclass(frozen=True)
class Document:
    """One admitted result, with whatever text could be read for it.

    Attributes:
        hit: The result as the source returned it.
        text: Full text where the port could fetch it, otherwise the
            snippet. Never empty.
        full_text: Whether ``text`` is the document or only its snippet,
            so an extractor can weigh a title-and-abstract read against
            a whole paper.
    """

    hit: SourceHit
    text: str
    full_text: bool


@dataclass(frozen=True)
class ExtractedFinding:
    """One claim an extractor drew from one document.

    Attributes:
        text: The finding in the extractor's words.
        locator: Which document it came from.
        span: The quoted text supporting it. An extractor that cannot
            quote has not found anything.
    """

    text: str
    locator: str
    span: str


@dataclass(frozen=True)
class Extraction:
    """What one thread's reading produced.

    Attributes:
        findings: Claims drawn from the documents.
        follow_ups: Questions the reading raised and did not answer.
            These become the next level's questions -- research
            direction derived from what was read, rather than the
            original goal planned again.
    """

    findings: tuple[ExtractedFinding, ...] = ()
    follow_ups: tuple[str, ...] = ()


class RetrievalError(Exception):
    """Raised by a retrieval port when a source could not be searched.

    The loop records it as a failed call and carries on with the other
    sources; it never propagates. Ports are free to raise anything --
    this exists so a port can be explicit about an expected failure.

    Attributes:
        source: Which source failed.
        reason: What went wrong.
    """

    def __init__(self, source: str, reason: str = "") -> None:
        """Record which source failed and why."""
        self.source = source
        self.reason = reason
        super().__init__(f"{source}: {reason}" if reason else source)


class RetrievalPort(Protocol):
    """Search and fetch, however the caller does those."""

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Search one source.

        Args:
            query: The query to issue.
            source: Which source to search.
            limit: Most results wanted.

        Returns:
            Results in the source's own ranking.
        """
        ...

    async def read(self, *, locator: str) -> str | None:
        """Fetch a document's text.

        Args:
            locator: Identifier from a hit.

        Returns:
            The text, or None when it could not be fetched -- in which
            case the loop falls back to the hit's snippet rather than
            skipping the document.
        """
        ...


class ResearchModelPort(Protocol):
    """The five model-shaped judgements the loop needs."""

    async def plan_stances(self, *, goal: str, limit: int) -> Sequence[str]:
        """Choose the perspectives the first level should cover.

        Coverage planned before it is searched: deciding whose questions
        matter, before deciding what to search for, is what makes a
        first level wide on purpose rather than wide by accident.

        Args:
            goal: What the research is for.
            limit: Most stances wanted.

        Returns:
            Stance names, e.g. mechanism, contradicting evidence,
            methodology, prior art.
        """
        ...

    async def ask_questions(
        self, *, goal: str, stance: str, limit: int
    ) -> Sequence[str]:
        """Ask what this stance needs to know.

        Args:
            goal: What the research is for.
            stance: The perspective asking.
            limit: Most questions wanted.

        Returns:
            Questions, in the stance's voice.
        """
        ...

    async def to_query(self, *, question: str) -> str:
        """Turn a question into a search query.

        Kept separate from the question deliberately: a query is a
        lossy, source-shaped rendering, and when it is broadened or
        retried the question it was serving has to survive.

        Args:
            question: What is being asked.

        Returns:
            The query to issue.
        """
        ...

    async def extract(
        self, *, question: str, documents: Sequence[Document]
    ) -> Extraction:
        """Read the documents for one question.

        Args:
            question: What the thread is answering.
            documents: What it admitted and read.

        Returns:
            Findings bound to their sources, plus the questions the
            reading left open.
        """
        ...

    async def compress(
        self, *, question: str, findings: Sequence[Finding]
    ) -> str:
        """Reduce a thread to an account its caller can hold.

        A thread reads far more than its caller can carry, so it hands
        back a summary rather than a transcript. The findings survive
        whole in the result either way.

        Args:
            question: What the thread answered.
            findings: What it found.

        Returns:
            The thread's account of itself.
        """
        ...
