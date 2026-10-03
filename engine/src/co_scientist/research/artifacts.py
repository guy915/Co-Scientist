"""Research budgets, input and output records, and collaborator protocols."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol

# Below this, halving stops. A one-question level is not research, it is
# a single lookup, and the descent may as well end instead.
DEFAULT_BREADTH_FLOOR = 2


@dataclass(frozen=True)
class ResearchBudget:
    """Ceilings for one research request.

    Attributes:
        depth: Levels of follow-up remaining, counting this one.
        breadth: Questions this level may open.
        concurrency: Threads that may run at once.
        hits_per_question: Documents read per question, across all
            sources.
        sources: Source names to search, in preference order. Opaque
            strings; the retrieval port decides what they mean.
        breadth_floor: Breadth never decays below this.
        reserved_slots: ``(source, places)`` pairs guaranteeing a source
            that many of each question's documents before the rest are
            filled in source order. Empty by default, which is the
            preference-order behaviour on its own.

    Raises:
        ValueError: If any ceiling is below one, no source is named, or a
            reservation is unfillable (see :meth:`_check_reservations`).
    """

    depth: int = 2
    breadth: int = 4
    concurrency: int = 2
    hits_per_question: int = 4
    sources: tuple[str, ...] = ()
    breadth_floor: int = DEFAULT_BREADTH_FLOOR
    reserved_slots: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        """Reject a budget that cannot describe any work."""
        for name in ("depth", "breadth", "concurrency", "hits_per_question"):
            value = getattr(self, name)
            if value < 1:
                raise ValueError(f"{name} must be at least 1, got {value}")
        if self.breadth_floor < 1:
            raise ValueError("breadth_floor must be at least 1")
        if not self.sources:
            raise ValueError("at least one source is required")
        self._check_reservations()

    def _check_reservations(self) -> None:
        """Reject reservations that cannot be honoured.

        A reservation naming a source this budget will not search is a
        typo that would otherwise do nothing at all, and reserving every
        place leaves preference order deciding nothing -- both are
        configuration mistakes worth failing on rather than absorbing.

        Raises:
            ValueError: A reservation names an unsearched source, asks
                for fewer than one place, or the reservations together
                claim every document the question may read.
        """
        total = 0
        for source, places in self.reserved_slots:
            if source not in self.sources:
                raise ValueError(f"reserved slots for unsearched {source!r}")
            if places < 1:
                raise ValueError(f"reserved slots for {source!r} must be >= 1")
            total += places
        if total >= self.hits_per_question and total:
            raise ValueError(
                f"reservations claim all {self.hits_per_question} hits"
            )

    def descend(self) -> ResearchBudget | None:
        """Return the budget for the next level down.

        Returns:
            A budget with one less level and half the breadth, or None
            when this was the last level.
        """
        if self.depth <= 1:
            return None
        return replace(
            self,
            depth=self.depth - 1,
            breadth=max(self.breadth_floor, self.breadth // 2),
        )

    def max_threads(self) -> int:
        """Return the most threads this budget can open, all levels.

        The number a caller can quote before spending anything. Useful
        for a cost estimate and for asserting in a test that the loop
        cannot exceed what it was given.
        """
        total = 0
        level: ResearchBudget | None = self
        while level is not None:
            total += level.breadth
            level = level.descend()
        return total


# Ids are truncated SHA-256. Long enough that a collision is not a
# practical concern at run scale, short enough to read in a log line.
_ID_CHARS = 32

# Separator between hashed parts. A byte that cannot appear in the text
# being hashed, so ("ab", "c") and ("a", "bc") cannot collide.
_SEP = b"\x1f"


def content_id(kind: str, *parts: str) -> str:
    """Derive a stable id from the parts that define an artifact.

    Args:
        kind: Artifact family, so ids from different families never
            collide even given identical parts.
        *parts: The defining values, in a fixed order.

    Returns:
        A 32-character hex digest.
    """
    digest = hashlib.sha256(kind.encode("utf-8"))
    for part in parts:
        digest.update(_SEP)
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()[:_ID_CHARS]


class CallStatus(Enum):
    """How one search against one source ended."""

    OK = "ok"
    EMPTY = "empty"
    FAILED = "failed"


class ThreadStatus(Enum):
    """How one question's research thread ended.

    ``DECLINED`` is not a failure: it is a thread the budget refused to
    start, reported so the caller can see what was not explored rather
    than silently receiving less than it asked for.
    """

    OK = "ok"
    EMPTY = "empty"
    FAILED = "failed"
    DECLINED = "declined"


class StopReason(Enum):
    """Why the descent ended.

    ``NO_RESULTS`` is the guard that matters operationally: when every
    thread at a level comes back empty -- an unreachable search service
    looks exactly like this -- descending would generate follow-up
    questions from nothing and spend the whole budget on it.
    """

    DEPTH_EXHAUSTED = "depth_exhausted"
    NO_RESULTS = "no_results"
    NO_FOLLOW_UPS = "no_follow_ups"


@dataclass(frozen=True)
class Question:
    """One thing the research is trying to answer.

    Attributes:
        text: The question itself.
        stance: The perspective that raised it ("mechanism", "prior
            art", ...), or ``seed`` when the caller supplied it.
        parent_id: Id of the finding whose follow-up this is, or None at
            the first level. This is what makes a run's questions a tree
            rather than a list.
    """

    text: str
    stance: str
    parent_id: str | None = None

    @property
    def id(self) -> str:
        """Content id over stance, text and parent."""
        return content_id(
            "question", self.stance, self.text, self.parent_id or ""
        )


@dataclass(frozen=True)
class SourceHit:
    """One result as a retrieval port returned it.

    Kept as returned, including ``rank``, because the ranking is part of
    what a replay has to reproduce.

    Attributes:
        locator: Whatever the source identifies a document by -- URL,
            DOI, PMID, corpus id. Opaque to this package.
        title: Display title.
        snippet: Whatever text came back with the result.
        rank: Position in the source's own ordering, from 0.
        score: The source's score, when it gives one.
        metadata: Anything else the port wants to carry through.
    """

    locator: str
    title: str
    snippet: str
    rank: int
    score: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchCall:
    """One query, against one source, and everything it returned.

    ``admitted`` and ``dropped`` partition the locators in ``hits``: a
    result the evidence budget refused is recorded as refused rather
    than deleted, because "we saw it and did not read it" and "we never
    saw it" are different facts about a run.

    Attributes:
        question: The question this query was serving.
        query: The query as issued.
        source: Which source was searched.
        status: How the call ended.
        hits: Results in the order returned.
        admitted: Locators that passed the budget and were read.
        dropped: Locators the budget refused.
        error: Failure text, when ``status`` is FAILED.
        duration_seconds: Wall time for the call.
    """

    question: str
    query: str
    source: str
    status: CallStatus
    hits: tuple[SourceHit, ...] = ()
    admitted: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    error: str | None = None
    duration_seconds: float | None = None

    @property
    def id(self) -> str:
        """Content id over source, question and query."""
        return content_id("call", self.source, self.question, self.query)


@dataclass(frozen=True)
class Finding:
    """One thing a document said, bound to where it was said.

    The binding happens at extraction time rather than after a report is
    written, which is what makes an unsupported claim structurally
    impossible here rather than merely detectable later.

    Attributes:
        text: The finding, in the extractor's words.
        question: The question it answers.
        locator: The document it came from.
        span: The quoted text supporting it.
        call_id: The search call that surfaced the document.
    """

    text: str
    question: str
    locator: str
    span: str
    call_id: str

    @property
    def id(self) -> str:
        """Content id over locator, span and question."""
        return content_id("finding", self.locator, self.span, self.question)


@dataclass(frozen=True)
class ThreadRecord:
    """What happened to one question.

    Attributes:
        question: The question researched.
        depth: Level in the descent, from 1.
        status: How the thread ended.
        call_ids: Search calls it made.
        finding_ids: Findings it produced.
        follow_ups: Questions its reading raised.
        summary: Compressed account of the thread, when it found
            anything.
        note: Why it was declined or how it failed.
        retry_breadth: For a declined thread, the breadth that would
            have accepted it -- so a caller is told what to ask for
            instead of only that it asked for too much.
    """

    question: Question
    depth: int
    status: ThreadStatus
    call_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()
    summary: str | None = None
    note: str | None = None
    retry_breadth: int | None = None


@dataclass(frozen=True)
class ResearchResult:
    """Everything one research request produced.

    Attributes:
        goal: The goal researched.
        stances: Perspectives the first level was planned from, empty
            when the caller supplied its own questions.
        threads: One record per question, including declined ones.
        calls: Every search call, in the order they completed.
        findings: Every finding, deduplicated by content id.
        stop_reason: Why the descent ended.
        levels_run: How many levels actually ran.
    """

    goal: str
    stances: tuple[str, ...]
    threads: tuple[ThreadRecord, ...]
    calls: tuple[SearchCall, ...]
    findings: tuple[Finding, ...]
    stop_reason: StopReason
    levels_run: int

    def findings_for(self, question: str) -> tuple[Finding, ...]:
        """Return the findings answering one question."""
        return tuple(f for f in self.findings if f.question == question)

    def declined(self) -> tuple[ThreadRecord, ...]:
        """Return the threads the budget refused to start."""
        return tuple(
            t for t in self.threads if t.status is ThreadStatus.DECLINED
        )

    def summaries(self) -> tuple[str, ...]:
        """Return every thread summary, outermost level first."""
        return tuple(t.summary for t in self.threads if t.summary)


def dedupe_findings(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    """Drop findings whose content id was already seen, keeping order."""
    seen: set[str] = set()
    kept: list[Finding] = []
    for finding in findings:
        if finding.id in seen:
            continue
        seen.add(finding.id)
        kept.append(finding)
    return tuple(kept)


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
