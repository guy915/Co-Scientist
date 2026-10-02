"""Ephemeral provider budgets for operations outside a research run."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from co_scientist.exceptions import LLMCallBudgetExceededError


@dataclass
class CompletionBudget:
    """A shared counter for one operation and its concurrent child tasks."""

    ceiling: int
    count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def reserve(self) -> None:
        """Refuse before dispatch when the operation has no calls left."""
        with self._lock:
            if self.count >= self.ceiling:
                raise LLMCallBudgetExceededError(self.count + 1, self.ceiling)
            self.count += 1


_current: ContextVar[CompletionBudget | None] = ContextVar(
    "completion_operation_budget", default=None
)


def current_completion_budget() -> CompletionBudget | None:
    """Return an operation override, or None to use the research counter."""
    return _current.get()


@contextmanager
def scoped_completion_budget(ceiling: int) -> Iterator[CompletionBudget]:
    """Give one operation a separate budget, independent of any run scope."""
    if ceiling < 1:
        raise ValueError("completion budget must allow at least one call")
    budget = CompletionBudget(ceiling)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)
