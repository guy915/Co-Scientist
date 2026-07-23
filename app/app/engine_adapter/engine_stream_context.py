"""Value objects describing one engine dispatch.

The three records the streaming path threads through its stages: what to
run before the generator exists (``_EngineRunRequest``), what to run once
it does (``_EngineRunInputs``), and the execution controls that are
orthogonal to both (``_EngineStreamControls``). They live in their own
module so the streaming loop and its post-stream report stage can share
them without an import cycle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, NamedTuple

from app.report_render import EmitFn


class _EngineRunRequest(NamedTuple):
    """What to run, before the engine generator has been built.

    The pre-dispatch half of ``_EngineRunInputs``: the run's identity and
    resolved tier config, from which ``_run_engine_provider`` derives the
    engine opts and the generator.
    """

    research_goal: str
    run_id: str
    run_mode: str
    cfg: dict[str, Any]


class _EngineRunInputs(NamedTuple):
    """One engine dispatch's fixed identity: what to generate and how.

    Bundles the parameters that describe a single engine run (as opposed to
    execution controls like cancellation/db_path/emit), so the streaming and
    persist-and-report stages can each pull only the fields they need
    without every intermediate function re-declaring the full parameter
    list.
    """

    generator: Any
    research_goal: str
    run_id: str
    run_mode: str
    initial_opts: dict[str, Any] | None


@dataclass(frozen=True)
class _EngineStreamControls:
    """One engine dispatch's execution controls.

    The counterpart to ``_EngineRunInputs``: how the run is interrupted,
    where it persists, where its events go, and whether it resumes from a
    checkpoint rather than starting from the goal.

    Attributes:
        cancelled: Cooperative cancellation signal, if the caller has one.
        db_path: Optional override for the SQLite database path.
        emit: Event sink every streamed event is emitted through.
        resume: Whether to restore the latest engine checkpoint.
    """

    cancelled: asyncio.Event | None
    db_path: str | None
    emit: EmitFn
    resume: bool = False
