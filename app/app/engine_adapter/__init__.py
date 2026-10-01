"""Engine adapter — drives the real engine workflow at runtime.

The engine is the only provider (``select_provider`` always returns
`"engine"`, raising if the `co_scientist` package can't be imported); a
keyless or forced deployment instead pins the run to the deterministic
offline LLM backend (see ``offline_mode``), rather than falling back to a
mock provider (retired).

The package is split by concern: ``provider`` (provider selection,
diagnostics, and the lazy engine import), ``events`` (engine-node to
canonical event/milestone translation), ``opts`` (run-config and steering
translation into engine opts), ``drain`` (a subpackage: final-state
persistence into the store, entered through ``drain.persist_final_state``),
and ``checkpoints`` (the engine-checkpoint tag the durable resume path
recognizes). This module re-exports the entry points consumed through the
package namespace, so callers keep using ``from app import engine_adapter``
unchanged.
"""

from __future__ import annotations

from app.engine_adapter.checkpoints import (
    is_engine_checkpoint as is_engine_checkpoint,
)
from app.engine_adapter.provider import offline_mode as offline_mode
from app.engine_adapter.provider import select_provider as select_provider
from app.engine_adapter.provider import system_status as system_status
from app.engine_adapter.tools import (
    connectors_report as connectors_report,
)
from app.engine_adapter.tools import (
    validate_tools_config as validate_tools_config,
)
