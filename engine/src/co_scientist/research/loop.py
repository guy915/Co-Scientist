"""The loop: ask, search, read, ask better, stop.

One entry point, :func:`conduct_research`. It sequences the two ports
into levels that narrow as they descend, and returns everything that
happened rather than only what it concluded.

**Follow-ups are pooled per level, not recursed per finding.** The
published implementations this borrows from recurse inside the result
loop, so their thread count multiplies with every level and the real
ceiling is whatever the model asked for. Here, every thread at a level
contributes its follow-up questions to one pool, the pool is clamped to
the next level's breadth, and that becomes the next level. Total threads
are then the sum of the per-level breadths -- a number
``ResearchBudget.max_threads`` can quote before anything is spent.

**Clamping answers, it does not truncate.** A question the budget will
not fund comes back as a declined thread carrying the reason and the
breadth that would have accepted it. Nothing is dropped silently, which
is the same discipline as returning a score for a crashing variant
rather than raising: the caller has to be able to see what did not
happen.

**An empty level ends the descent.** If no thread at a level found
anything, the next level's questions would be generated from nothing --
which is exactly the state an unreachable search service produces, and
exactly when spending the rest of the budget is worst. That stop is a
recorded outcome on the result, not a log line.

Failures are contained at the thread and at the call. A source that
raises is a failed call beside its succeeding siblings; a model that
raises fails one thread and leaves the rest of the level running.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Union

from co_scientist.research.admission import (
    admit_within_budget,
    bind_findings,
)
from co_scientist.research.artifacts import (
    CallStatus,
    Finding,
    Question,
    ResearchResult,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
    dedupe_findings,
)
from co_scientist.research.budget import ResearchBudget
from co_scientist.research.ports import (
    Document,
    ResearchModelPort,
    RetrievalPort,
)

logger = logging.getLogger(__name__)

# Stance recorded for questions the caller supplied itself. A caller that
# already knows what to ask -- a review probing one assumption, say --
# skips stance planning entirely.
SEED_STANCE = "seed"

# What the next level is, or why there is not one.
_Continuation = Union[
    "tuple[list[Question], ResearchBudget]",
    StopReason,
]


async def conduct_research(
    *,
    goal: str,
    model: ResearchModelPort,
    retrieval: RetrievalPort,
    budget: ResearchBudget,
    seed_questions: Sequence[str] = (),
) -> ResearchResult:
    """Research a goal within a budget, and report everything it did.

    Args:
        goal: What the research is for.
        model: The caller's model adapter.
        retrieval: The caller's search and fetch adapter.
        budget: Ceilings for this request. Never exceeded.
        seed_questions: Questions to start from. When given, stance
            planning is skipped and these are the first level.

    Returns:
        Every thread, call and finding the request produced, and why the
        descent ended.
    """
    session = _Session(model=model, retrieval=retrieval, budget=budget)
    stances, questions = await session.open(goal, seed_questions)
    stop_reason, levels_run = await session.descend(questions)
    return ResearchResult(
        goal=goal,
        stances=stances,
        threads=tuple(session.threads),
        calls=tuple(session.calls),
        findings=dedupe_findings(session.findings),
        stop_reason=stop_reason,
        levels_run=levels_run,
    )


class _Session:
    """One research request, and everything it accumulates.

    Holding the ports and the ledger together is what keeps the
    per-thread call sites short; nothing here outlives the request.
    """

    def __init__(
        self,
        *,
        model: ResearchModelPort,
        retrieval: RetrievalPort,
        budget: ResearchBudget,
    ) -> None:
        """Start empty, with a limiter bound to the running loop."""
        self.model = model
        self.retrieval = retrieval
        self.budget = budget
        # Created per request, so it binds to the event loop actually
        # running it. A module-level semaphore binds to whichever loop
        # touched it first and raises from every other -- and several
        # are live at once, one per worker cohort.
        self.limiter = asyncio.Semaphore(budget.concurrency)
        self.threads: list[ThreadRecord] = []
        self.calls: list[SearchCall] = []
        self.findings: list[Finding] = []

    async def open(
        self, goal: str, seed_questions: Sequence[str]
    ) -> tuple[tuple[str, ...], list[Question]]:
        """Decide what the first level asks.

        A caller with its own questions skips stance planning entirely;
        otherwise stances are planned first and each contributes one
        question, so the first level's coverage is spread across
        perspectives rather than concentrated in whichever one the model
        found most interesting.

        Args:
            goal: What the research is for.
            seed_questions: Caller-supplied questions, if any.

        Returns:
            The stances used, and the first level's questions.
        """
        if seed_questions:
            return (), [
                Question(text=text, stance=SEED_STANCE)
                for text in seed_questions
            ]

        stances = tuple(
            await self.model.plan_stances(goal=goal, limit=self.budget.breadth)
        )
        if not stances:
            return (), []

        asked = await asyncio.gather(
            *(
                self.model.ask_questions(goal=goal, stance=stance, limit=1)
                for stance in stances
            )
        )
        questions = [
            Question(text=text, stance=stance)
            for stance, texts in zip(stances, asked, strict=True)
            for text in texts
        ]
        return stances, questions

    async def descend(
        self, questions: list[Question]
    ) -> tuple[StopReason, int]:
        """Run levels until the budget or the material runs out.

        Args:
            questions: The first level's questions.

        Returns:
            Why the descent ended, and how many levels ran.
        """
        levels_run = 0
        while questions:
            accepted = self._clamp(questions, levels_run + 1)
            if not accepted:
                return StopReason.NO_FOLLOW_UPS, levels_run
            levels_run += 1
            await asyncio.gather(
                *(
                    self._run_thread(question, levels_run)
                    for question in accepted
                )
            )
            outcome = self._continue_from(levels_run)
            if isinstance(outcome, StopReason):
                return outcome, levels_run
            questions, self.budget = outcome
        return StopReason.NO_FOLLOW_UPS, levels_run

    def _continue_from(self, depth: int) -> _Continuation:
        """Decide whether there is a next level, and what it is."""
        if not self._level_found_anything(depth):
            logger.warning(
                "Research level %s produced no findings; stopping descent",
                depth,
            )
            return StopReason.NO_RESULTS
        next_budget = self.budget.descend()
        if next_budget is None:
            return StopReason.DEPTH_EXHAUSTED
        questions = self._follow_up_questions(depth)
        if not questions:
            return StopReason.NO_FOLLOW_UPS
        return questions, next_budget

    def _level_found_anything(self, depth: int) -> bool:
        """Whether any thread at this depth produced a finding."""
        return any(
            thread.finding_ids
            for thread in self.threads
            if thread.depth == depth
        )

    def _follow_up_questions(self, depth: int) -> list[Question]:
        """Collect this depth's follow-ups as the next level's questions.

        Deduplicated by text, and not only within the level: two threads
        reading adjacent literature routinely surface the same open
        question, and a level's reading routinely raises a question an
        earlier level already researched. Both cost a thread out of a
        small budget to re-answer something on record, and the second
        one also makes the descent look deeper than it was.
        """
        seen: set[str] = {thread.question.text for thread in self.threads}
        questions: list[Question] = []
        for thread in self.threads:
            if thread.depth != depth:
                continue
            for text in thread.follow_ups:
                if text in seen:
                    continue
                seen.add(text)
                questions.append(
                    Question(
                        text=text,
                        stance=thread.question.stance,
                        parent_id=thread.question.id,
                    )
                )
        return questions

    def _clamp(
        self, questions: Sequence[Question], depth: int
    ) -> list[Question]:
        """Take what this level can fund, and record what it refused.

        A declined thread carries the depth it was declined at, so a
        question refused at the first level and one refused three levels
        down stay distinguishable in the record.
        """
        breadth = self.budget.breadth
        for question in questions[breadth:]:
            self.threads.append(
                ThreadRecord(
                    question=question,
                    depth=depth,
                    status=ThreadStatus.DECLINED,
                    note=(
                        "Breadth budget spent: this level funds "
                        f"{breadth} questions"
                    ),
                    retry_breadth=len(questions),
                )
            )
        return list(questions[:breadth])

    async def _run_thread(self, question: Question, depth: int) -> None:
        """Research one question and record what happened to it."""
        async with self.limiter:
            try:
                record = await self._research_question(question, depth)
            except Exception as exc:  # one thread, not the request
                logger.warning(
                    "Research thread failed for %r: %s", question.text, exc
                )
                record = ThreadRecord(
                    question=question,
                    depth=depth,
                    status=ThreadStatus.FAILED,
                    note=str(exc),
                )
            self.threads.append(record)

    async def _research_question(
        self, question: Question, depth: int
    ) -> ThreadRecord:
        """Search, read and extract for one question."""
        query = await self.model.to_query(question=question.text)
        calls = await self._search_sources(question.text, query)
        admitted, calls = admit_within_budget(calls, self.budget)
        self.calls.extend(calls)
        call_ids = tuple(call.id for call in calls)

        if not admitted:
            return ThreadRecord(
                question=question,
                depth=depth,
                status=ThreadStatus.EMPTY,
                call_ids=call_ids,
                note="No source returned a usable result",
            )
        return await self._read_for(question, depth, admitted, calls)

    async def _read_for(
        self,
        question: Question,
        depth: int,
        admitted: Sequence[SourceHit],
        calls: Sequence[SearchCall],
    ) -> ThreadRecord:
        """Read what one question admitted, and account for it.

        Args:
            question: What the thread is answering.
            depth: The level it is running at.
            admitted: The hits the budget funded.
            calls: The thread's calls, already recorded.

        Returns:
            The thread's record, empty-but-successful included.
        """
        call_ids = tuple(call.id for call in calls)
        documents = await self._read_documents(admitted)
        extraction = await self.model.extract(
            question=question.text, documents=documents
        )
        findings = bind_findings(extraction.findings, question.text, calls)
        self.findings.extend(findings)

        if not findings:
            return ThreadRecord(
                question=question,
                depth=depth,
                status=ThreadStatus.EMPTY,
                call_ids=call_ids,
                follow_ups=extraction.follow_ups,
                note="Nothing in the admitted documents answered it",
            )

        summary = await self.model.compress(
            question=question.text, findings=findings
        )
        return ThreadRecord(
            question=question,
            depth=depth,
            status=ThreadStatus.OK,
            call_ids=call_ids,
            finding_ids=tuple(finding.id for finding in findings),
            follow_ups=extraction.follow_ups,
            summary=summary,
        )

    async def _search_sources(
        self, question: str, query: str
    ) -> list[SearchCall]:
        """Run one query against every configured source.

        A source that raises becomes a failed call beside its siblings:
        one unreachable remote service must not veto the sources that
        are fine, including a local corpus that was never unavailable.
        """

        async def one(source: str) -> SearchCall:
            started = time.monotonic()
            try:
                hits = await self.retrieval.search(
                    query=query,
                    source=source,
                    limit=self.budget.hits_per_question,
                )
            except Exception as exc:  # one source, not the request
                logger.warning("Search failed on %s: %s", source, exc)
                return SearchCall(
                    question=question,
                    query=query,
                    source=source,
                    status=CallStatus.FAILED,
                    error=str(exc),
                    duration_seconds=time.monotonic() - started,
                )
            ordered = tuple(hits)
            return SearchCall(
                question=question,
                query=query,
                source=source,
                status=CallStatus.OK if ordered else CallStatus.EMPTY,
                hits=ordered,
                duration_seconds=time.monotonic() - started,
            )

        gathered = await asyncio.gather(
            *(one(source) for source in self.budget.sources)
        )
        return list(gathered)

    async def _read_documents(
        self, hits: Sequence[SourceHit]
    ) -> list[Document]:
        """Fetch each admitted hit, falling back to its snippet.

        A document that cannot be fetched is still evidence at snippet
        depth; dropping it would silently narrow a thread's reading to
        whatever happened to be fetchable.
        """

        async def one(hit: SourceHit) -> Document:
            try:
                text = await self.retrieval.read(locator=hit.locator)
            except Exception as exc:  # one document, not the thread
                logger.warning("Read failed for %s: %s", hit.locator, exc)
                text = None
            if text:
                return Document(hit=hit, text=text, full_text=True)
            return Document(hit=hit, text=hit.snippet, full_text=False)

        return list(await asyncio.gather(*(one(hit) for hit in hits)))
