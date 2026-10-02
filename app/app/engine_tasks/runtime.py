"""The collaborators a durable engine task calls outside the store.

A task builds a generator (for a new run's engine options, or only for the
tool registry a checkpoint restore needs), screens text through the safety
gate, and drains a finished run's final state. Each used to be looked up by
name in whichever module happened to call it, so a test reached one by patching
three to five namespaces, and a patch on a namespace nothing resolved the name
in installed nothing while the suite quietly ran the real collaborator. They
now sit behind one interface with two adapters:

- :class:`ProductionEngineTaskRuntime`, the default, which reaches the real
  generator builders, ``screen_with_escalation`` and the final-state drain.
- A test adapter (``tests/_engine_tasks_helpers.py``), which replaces only the
  slots a test states and leaves the rest on production. It takes the place of
  the module's ``_installed`` adapter, the one name every task resolves
  through.

``execute_engine_task`` resolves :func:`active` once per task and :func:`bound`
scopes it around the handler, the way the run's credential and call budget are
scoped beside it, so every helper the task reaches sees the same adapter.

The adapter is plain callables: it holds no generator and no asyncio primitive,
so nothing built on one worker cohort's event loop can reach another. Each
generator is still built inside the handler call that uses it. The module is a
leaf (standard library only at import) so the
``app.engine_tasks`` modules can all import it eagerly. ``app.report`` imports
it inside the function that needs it: any submodule import loads the package
first, and the package reaches ``engine_adapter``, which imports ``app.report``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app import store
    from app.safety import ScreenSubject
    from app.safety.types import SafetyDecision
    from app.store import ScientificTask

__all__ = [
    "EngineTaskRuntime",
    "ProductionEngineTaskRuntime",
    "active",
    "bound",
]


class EngineTaskRuntime(Protocol):
    """What a durable engine task needs from outside the store."""

    def generator_and_opts(
        self, task: ScientificTask, db_path: str | None
    ) -> tuple[Any, dict[str, Any]]:
        """Build the generator and engine options for a run's next task."""
        ...

    def generator_for_restore(
        self, task: ScientificTask, db_path: str | None
    ) -> Any:
        """Build a registry-compatible generator without consuming steering."""
        ...

    async def screen(
        self,
        run_id: str,
        subject: ScreenSubject,
        *,
        provider: str,
        db_path: str | None = None,
    ) -> SafetyDecision:
        """Gate a stage's content: the intake goal or the final report."""
        ...

    async def drain_final_state(
        self,
        run: store.RunRow,
        state: dict[str, Any],
        db_path: str | None,
    ) -> tuple[Any, float, dict[str, Any]]:
        """Persist replayable final artifacts outside a database lock."""
        ...


class ProductionEngineTaskRuntime:
    """Production adapter: each slot reaches the real collaborator.

    Imports are function-local because the collaborators sit above this
    module in the import graph (``engine_tasks.support`` imports the engine
    adapter, whose drain imports ``app.report``).
    """

    def generator_and_opts(
        self, task: ScientificTask, db_path: str | None
    ) -> tuple[Any, dict[str, Any]]:
        """Build the generator and engine options for a run's next task."""
        from app.engine_tasks.support import _generator_and_opts

        return _generator_and_opts(task, db_path)

    def generator_for_restore(
        self, task: ScientificTask, db_path: str | None
    ) -> Any:
        """Build a registry-compatible generator without consuming steering."""
        from app.engine_tasks.support import _generator_for_restore

        return _generator_for_restore(task, db_path)

    async def screen(
        self,
        run_id: str,
        subject: ScreenSubject,
        *,
        provider: str,
        db_path: str | None = None,
    ) -> SafetyDecision:
        """Gate a stage's content: the intake goal or the final report."""
        from app.safety import screen_with_escalation

        return await screen_with_escalation(
            run_id, subject, provider=provider, db_path=db_path
        )

    async def drain_final_state(
        self,
        run: store.RunRow,
        state: dict[str, Any],
        db_path: str | None,
    ) -> tuple[Any, float, dict[str, Any]]:
        """Persist replayable final artifacts outside a database lock."""
        from app.engine_tasks.finalize import _drain_and_persist_final_state

        return await _drain_and_persist_final_state(run, state, db_path)


_installed: EngineTaskRuntime = ProductionEngineTaskRuntime()
_bound: ContextVar[EngineTaskRuntime | None] = ContextVar(
    "engine_task_runtime", default=None
)


def active() -> EngineTaskRuntime:
    """Return the adapter bound to the running task, else the installed one.

    Looked up at call time, so a handler invoked directly (as the tests do)
    sees the installed adapter without going through the dispatcher.
    """
    return _bound.get() or _installed


@contextlib.contextmanager
def bound(runtime: EngineTaskRuntime) -> Iterator[None]:
    """Scope ``runtime`` to the current (async) execution context."""
    token = _bound.set(runtime)
    try:
        yield
    finally:
        _bound.reset(token)
