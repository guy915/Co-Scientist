"""Recording which data sources a node's science-skill commands reached.

The skills query third-party databases whose terms are separate from the
bundle's licence, and most of them require that the user be notified of
those terms. ``licences.py`` pays that obligation where the skills
themselves define it -- a file in the workspace -- and says why that is
not enough: a workspace is deleted, so the notice reaches nobody. The
surface that reaches a person is the run's report, and it can only name
the sources a run actually used if something counted them.

The counter is a context variable rather than an argument threaded
through the draft pipeline, mirroring ``llm_telemetry.scoped_telemetry``:
the invocation happens deep inside a tool handler and the number is
wanted at the node boundary, which is exactly the shape that module
already solved. A context variable is also the only safe choice here --
each durable run's worker cohort runs on its own thread with its own
event loop, so a module-level total would mix two runs together (see
AGENTS.md, "No process-global asyncio primitives").

Recording outside any scope is a no-op, which is what a ``dev/`` script
driving a node function directly does, and what every run without
``COSCIENTIST_SKILLS_DIR`` does because no skill is ever invoked.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar


class SkillUsage:
    """Mutable skill-name-to-invocation-count tally for one node."""

    def __init__(self) -> None:
        """Start with an empty tally."""
        self._counts: dict[str, int] = {}

    def record(self, name: str) -> None:
        """Count one invocation of the named skill."""
        self._counts[name] = self._counts.get(name, 0) + 1

    def snapshot(self) -> dict[str, int]:
        """Return the tally as a plain dict, safe to hand to metrics."""
        return dict(self._counts)


_current_usage: ContextVar[SkillUsage | None] = ContextVar(
    "current_skill_usage", default=None
)


@contextlib.contextmanager
def scoped_skill_usage() -> Iterator[SkillUsage]:
    """Scope a skill tally to one node's execution.

    Yields:
        The tally every skill invocation in this scope is recorded into.
    """
    usage = SkillUsage()
    token = _current_usage.set(usage)
    try:
        yield usage
    finally:
        _current_usage.reset(token)


def record_skill_use(name: str) -> None:
    """Record one skill invocation into the active scope, if any.

    Args:
        name: The skill's declared name, from ``invoked_skill``.
    """
    usage = _current_usage.get()
    if usage is not None:
        usage.record(name)
