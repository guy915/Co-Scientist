"""Final-state drain: persist an engine run's results into the store.

The one entry is :func:`persist_final_state`, which the durable finalize
task awaits. It runs two write transactions with the provider work between
them and holds no connection across that work (the root ``AGENTS.md``
invariant: never hold a SQLite write lock over network I/O):

1. Resolve cited articles off the event loop, then in one transaction write
   evidence, hypotheses, reviews, citations, held-for-review verdicts and the
   supervisor plan, and run the deterministic safety screen.
2. Between the transactions, assess claim grounding and escalate held safety
   verdicts, each off the event loop so the task lease's heartbeat keeps
   renewing.
3. In a second transaction, persist the grounding result, the tournament
   matches, the proximity graph, and the escalated verdicts.

It returns a :class:`DrainResult`; ``FinalStateInputs`` is the precomputed
view of the final state that its phases share. Every other module in this
package is an implementation detail of the drain: production code outside it
never imports them, and only tests of their pure helpers do.
"""

from __future__ import annotations

from app.engine_adapter.drain.final_state import (
    DrainResult as DrainResult,
)
from app.engine_adapter.drain.final_state import (
    FinalStateInputs as FinalStateInputs,
)
from app.engine_adapter.drain.final_state import (
    persist_final_state as persist_final_state,
)

__all__ = ["DrainResult", "FinalStateInputs", "persist_final_state"]
