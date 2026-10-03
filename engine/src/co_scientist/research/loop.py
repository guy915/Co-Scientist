"""Budgeted research descent and admission over scientific questions."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import replace
from typing import Union

from co_scientist.research.artifacts import (
    CallStatus,
    Document,
    ExtractedFinding,
    Finding,
    Question,
    ResearchBudget,
    ResearchModelPort,
    ResearchResult,
    RetrievalPort,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
    dedupe_findings,
)

logger = logging.getLogger(__name__)


def bind_findings(
    extracted: Sequence[ExtractedFinding],
    question: str,
    calls: Sequence[SearchCall],
) -> tuple[Finding, ...]:
    """Bind each extracted claim to the question and call behind it.

    A finding that cannot be traced to the call that surfaced its
    document keeps an empty ``call_id`` rather than being dropped: the
    claim and its span are the evidence, and the call is provenance.

    Args:
        extracted: What the model drew from the documents.
        question: The question the thread was answering.
        calls: The thread's calls, for locating each document's origin.

    Returns:
        Findings carrying their question, span and originating call.
    """
    call_by_locator = {
        hit.locator: call.id for call in calls for hit in call.hits
    }
    return tuple(
        Finding(
            text=item.text,
            question=question,
            locator=item.locator,
            span=item.span,
            call_id=call_by_locator.get(item.locator, ""),
        )
        for item in extracted
    )


def _claim_locators(
    calls: Sequence[SearchCall],
) -> list[tuple[SearchCall, list[SourceHit]]]:
    """Pair each call with the hits no earlier call already returned.

    Deduplication happens once, before either fill, so a paper both a
    reserved source and an unreserved one returned is seated once and
    counted against whichever came first -- the same collapse-onto-the-
    first-source rule as before reservations existed.

    Args:
        calls: This question's calls, in the order they were issued.

    Returns:
        One entry per call, hits in the source's own ranking.
    """
    seen: set[str] = set()
    paired = []
    for call in calls:
        hits = [hit for hit in call.hits if hit.locator not in seen]
        seen.update(hit.locator for hit in hits)
        paired.append((call, hits))
    return paired


def _fill_reserved(
    paired: Sequence[tuple[SearchCall, list[SourceHit]]],
    budget: ResearchBudget,
) -> list[SourceHit]:
    """Seat the hits a source's reservation guarantees a place.

    Reservations are filled best-first from within their own source,
    never padded when the source returned fewer hits than it reserved,
    and cannot push the question past ``hits_per_question``.

    Args:
        paired: Calls with their deduplicated hits.
        budget: The level's ceilings, carrying ``reserved_slots``.

    Returns:
        The reserved hits, in call order.
    """
    quotas = dict(budget.reserved_slots)
    if not quotas:
        return []
    taken: list[SourceHit] = []
    for call, hits in paired:
        room = budget.hits_per_question - len(taken)
        places = min(quotas.get(call.source, 0), room)
        if places > 0:
            taken.extend(hits[:places])
    return taken


def admit_within_budget(
    calls: Sequence[SearchCall], budget: ResearchBudget
) -> tuple[list[SourceHit], list[SearchCall]]:
    """Choose which results get read, and record which did not.

    Sources are drawn in configured order and results in their own
    ranking, so the ordering a replay has to reproduce is the ordering
    the sources gave. A locator returned by two sources collapses onto
    the first one that returned it.

    The one departure from that order is a source holding
    ``reserved_slots``: it is seated first, up to its reservation. That
    exists because preference order is a proxy for quality that one
    source cannot compete on -- the group's own papers are searched last
    and the indexed literature fills every place before they are reached,
    so without a reservation a corpus that answers the question well is
    never read at all.

    Args:
        calls: This question's calls, one per source.
        budget: The level's ceilings.

    Returns:
        The admitted hits, and the calls updated with what each of them
        contributed and what was refused.
    """
    paired = _claim_locators(calls)
    admitted = _fill_reserved(paired, budget)
    admitted_locators = {hit.locator for hit in admitted}

    for _call, hits in paired:
        for hit in hits:
            if hit.locator in admitted_locators:
                continue
            if len(admitted) < budget.hits_per_question:
                admitted.append(hit)
                admitted_locators.add(hit.locator)

    recorded = [
        replace(
            call,
            admitted=tuple(
                hit.locator
                for hit in call.hits
                if hit.locator in admitted_locators
            ),
            dropped=tuple(
                hit.locator
                for hit in call.hits
                if hit.locator not in admitted_locators
            ),
        )
        for call in calls
    ]
    return admitted, recorded


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
