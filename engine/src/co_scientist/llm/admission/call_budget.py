"""Count physical requests inside tasks to catch node-local overruns.
Threading locks cross worker event loops without asyncio affinity.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from co_scientist._context import _bind_contextvar
from co_scientist.exceptions import LLMCallBudgetExceededError


@dataclass
class CompletionBudget:
    """Operation budgets are shared by concurrent child tasks, independently
    of run counters.
    """

    ceiling: int
    count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def reserve(self) -> None:
        with self._lock:
            if self.count >= self.ceiling:
                raise LLMCallBudgetExceededError(self.count + 1, self.ceiling)
            self.count += 1


_current: ContextVar[CompletionBudget | None] = ContextVar(
    "completion_operation_budget", default=None
)


def current_completion_budget() -> CompletionBudget | None:
    return _current.get()


@contextmanager
def scoped_completion_budget(ceiling: int) -> Iterator[CompletionBudget]:
    if ceiling < 1:
        raise ValueError("completion budget must allow at least one call")
    budget = CompletionBudget(ceiling)
    with _bind_contextvar(_current, budget):
        yield budget


logger = logging.getLogger(__name__)

# Bound process memory; evicting a tracked run forfeits its ceiling enforcement.
_MAX_TRACKED_RUNS = 500

_current_run: ContextVar[str | None] = ContextVar("llm_call_budget_run", default=None)


@dataclass
class _RunCounter:
    count: int
    ceiling: int | None


_lock = threading.Lock()
# Re-entered runs move last so eviction still identifies the oldest entry.
_runs: OrderedDict[str, _RunCounter] = OrderedDict()


@contextmanager
def scoped_llm_call_budget(run_id: str | None, ceiling: int | None) -> Iterator[None]:
    """Tasks re-enter one persisted run counter without resetting it; the
    first ceiling remains binding.
    """
    if run_id is not None:
        _ensure_tracked(run_id, ceiling)
    with _bind_contextvar(_current_run, run_id):
        yield


def _ensure_tracked(run_id: str, ceiling: int | None) -> None:
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
    """Unscoped calls must not inherit the last run on this thread. The
    refused next request shares the scheduler ceiling boundary.
    """
    operation = current_completion_budget()
    if operation is not None:
        operation.reserve()
        return
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
    with _lock:
        entry = _runs.get(run_id)
        return entry.count if entry is not None else 0


def release_run_call_budget(run_id: str) -> None:
    """Terminal cleanup bounds memory; eviction covers runs that never reach
    that cleanup.
    """
    with _lock:
        _runs.pop(run_id, None)
