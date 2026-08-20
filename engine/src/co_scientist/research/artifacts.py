"""What a piece of research is made of, and how each piece is named.

Every artifact here is immutable and **content-addressed**: its id is a
hash of the things that make it what it is, not a counter handed out at
creation. Two properties follow, and both are the point.

**The same source read for two questions is two findings.** A locator
alone does not identify evidence, because the reason it was fetched is
part of what it is. A paper that answers "what is the mechanism" and a
paper that answers "what contradicts this" are different evidence even
when they are the same PDF, and collapsing them loses the only record of
why the run went looking. So a finding's id spans locator, span and
question, and a search call's id spans source, question and query.

**Identity survives a restart without a registry.** Re-running the same
question against the same source produces the same ids, so a resumed run
recognises work it already paid for instead of duplicating it.

This is the one decision in this package that cannot be revised later: an
id scheme can be changed only while no rows exist. The fields are
therefore chosen against what persistence will need — the ranked result
set as returned, what the budget dropped, the status, and the timing —
rather than against what the loop happens to use today.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

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
