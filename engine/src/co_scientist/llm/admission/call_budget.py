"""Run-scoped provider-request counting and the ceiling it enforces.

``co_scientist.scheduling.policy_checks._llm_call_budget_check`` only runs
between the supervisor's scheduling decisions, so a task that fires
hundreds of provider requests inside one node was never interrupted by
it -- the observed production failure was 100-170 calls per minute inside
a single task, over a run that made five scheduling decisions in ninety
minutes. This module is the enforcement point *inside* a task: every
public entry point that actually reaches a provider funnels through
``_acompletion_within_timeout`` (``llm.attempts.single._call_llm_and_cache`` for
``call_llm``/``call_llm_json``, ``llm.tools.iteration`` for the tool-calling
loop). That shared seam counts only after zero-cost admission succeeds.

The counter is scoped to a run via a ``ContextVar`` rather than threaded
as an explicit parameter through every retry/escalation call chain --
the same shape ``llm.admission.credentials.scoped_api_key`` uses to reach a
credential down into ``llm.attempts.single._call_llm_and_cache`` without
carrying it on the (deliberately credential-free) request object.
``scoped_llm_call_budget`` is entered once per durable task
(``app.engine_tasks.execute_engine_task``), and every completion made while
that task runs -- however many retries or tool-loop turns deep -- is attributed
to its run without any intervening function needing to know the run id at all.

Counting lives in a plain ``dict`` behind a ``threading.Lock``, never an
asyncio primitive: each durable run's worker cohort executes on its own
thread with its own event loop (``task_worker.run_run_worker_pool_sync``
calls ``asyncio.run``), so several loops are live in one process and an
asyncio lock binds to whichever loop first awaits it, raising from every
other (see the "No process-global asyncio primitives" root Gotcha). A
``threading.Lock`` has no such affinity.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import logging
import threading
from collections import OrderedDict
from collections.abc import Iterator

from co_scientist.exceptions import LLMCallBudgetExceededError

logger = logging.getLogger(__name__)

# Bounds memory across a long-lived process that has served many runs: the
# oldest-tracked run is evicted once this many are held at once, rather
# than growing the dict for the life of the process. A run this large is
# already well past any tier's max_llm_calls, so eviction only ever
# affects a run whose ceiling can no longer be usefully enforced anyway.
_MAX_TRACKED_RUNS = 500

_current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_call_budget_run", default=None
)


@dataclasses.dataclass
class _RunCounter:
    """One run's counted requests and the ceiling they are checked against."""

    count: int
    ceiling: int | None


_lock = threading.Lock()
# Ordered so the oldest entry is known for eviction; re-entering a run's
# scope (a new task) moves it to the end.
_runs: OrderedDict[str, _RunCounter] = OrderedDict()


@contextlib.contextmanager
def scoped_llm_call_budget(
    run_id: str | None, ceiling: int | None
) -> Iterator[None]:
    """Scopes provider-request counting to one run for the current task.

    Mirrors ``llm.admission.credentials.scoped_api_key``'s shape: a
    ``ContextVar`` reaches the seam without threading the run id through every
    retry/escalation call chain.

    Entry is idempotent per run: a durable run is driven by many
    short-lived tasks, each entering its own scope against the same run
    id, and the run's running count must survive across them rather than
    reset. The first task to see a given run id establishes its ceiling;
    later tasks' ``ceiling`` argument is ignored for an already-tracked
    run, since a run's configured ceiling does not change mid-run and the
    first value seen is as good as any later one.

    Args:
        run_id: The run this block's completions belong to. ``None`` (a
            call made outside a durable task, or a test with nothing to
            attribute spend to) scopes to no run at all: counting is a
            no-op and nothing can be exceeded, matching how
            ``scoped_api_key(None)`` leaves the ambient credential alone.
        ceiling: The run's configured ``max_llm_calls``, or None to count
            without ever enforcing one.

    Yields:
        None.
    """
    if run_id is not None:
        _ensure_tracked(run_id, ceiling)
    token = _current_run.set(run_id)
    try:
        yield
    finally:
        _current_run.reset(token)


def _ensure_tracked(run_id: str, ceiling: int | None) -> None:
    """Registers a run's counter if unseen, and evicts the oldest overflow."""
    with _lock:
        if run_id in _runs:
            _runs.move_to_end(run_id)
            return
        _runs[run_id] = _RunCounter(count=0, ceiling=ceiling)
        while len(_runs) > _MAX_TRACKED_RUNS:
            evicted, _ = _runs.popitem(last=False)
            logger.warning(
                "Evicting llm-call counter for run %s (tracking cap %s"
                " reached); its ceiling can no longer be enforced",
                evicted,
                _MAX_TRACKED_RUNS,
            )


def record_provider_request() -> None:
    """Counts one outbound provider request against the current run scope.

    A no-op when no run is scoped (``scoped_llm_call_budget`` was never
    entered, or entered with ``run_id=None``): an ad hoc call outside a
    durable task must not raise, and must not attribute its spend to
    whatever run happened to run last on this thread.

    Raises once a run's counted requests exceed its ceiling, so the
    request that would be the ``(ceiling + 1)``th is the one refused --
    the same boundary ``policy_checks._llm_call_budget_check`` uses
    between tasks (it terminates once the count reaches the ceiling, this
    refuses the next request past it), so the two can never disagree
    about how many requests a run is allowed.

    Raises:
        LLMCallBudgetExceededError: If this request pushes the run's
            counted total past its configured ceiling.
    """
    run_id = _current_run.get()
    if run_id is None:
        return
    with _lock:
        entry = _runs.setdefault(run_id, _RunCounter(count=0, ceiling=None))
        entry.count += 1
        count, ceiling = entry.count, entry.ceiling
        _runs.move_to_end(run_id)
    if ceiling is not None and count > ceiling:
        raise LLMCallBudgetExceededError(count, ceiling)


def current_run_call_count(run_id: str) -> int:
    """The seam-counted provider requests so far for one run (0 if unseen)."""
    with _lock:
        entry = _runs.get(run_id)
        return entry.count if entry is not None else 0


def release_run_call_budget(run_id: str) -> None:
    """Drops a finished run's counter so memory does not grow unbounded.

    Called once a run reaches a terminal state (finalized, or permanently
    failed on its own ceiling); the ``_MAX_TRACKED_RUNS`` eviction is only
    the backstop for runs that never reach either -- cancelled or exhausted-
    retry-budget failures are not required to call this.
    """
    with _lock:
        _runs.pop(run_id, None)
