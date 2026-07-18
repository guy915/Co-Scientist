"""Engine adapter — drives the real engine workflow at runtime.

The engine is the only provider (``select_provider`` always returns
`"engine"`, raising if the `co_scientist` package can't be imported); a
keyless or forced deployment instead pins the run to the deterministic
offline LLM backend (see ``offline_mode``), rather than falling back to a
mock provider (retired).

The package is split by concern: ``provider`` (provider selection,
diagnostics, and the lazy engine import), ``events`` (engine-node to
canonical event/milestone translation), ``opts`` (run-config and steering
translation into engine opts), ``drain`` (final-state persistence into the
store), ``engine_stream`` (the real-engine streaming loop), and ``workflow``
(the shared ``run_workflow`` boundary with the intake safety gate). This
module re-exports the names consumed through the package namespace — the
public entry points plus the private helpers tests exercise directly — so
callers keep using ``from app import engine_adapter`` unchanged.
"""

from __future__ import annotations

from app.engine_adapter.drain import (
    _persist_final_state as _persist_final_state,
)
from app.engine_adapter.engine_stream import (
    is_engine_checkpoint as is_engine_checkpoint,
)
from app.engine_adapter.opts import _build_engine_opts as _build_engine_opts
from app.engine_adapter.provider import offline_mode as offline_mode
from app.engine_adapter.provider import select_provider as select_provider
from app.engine_adapter.provider import system_status as system_status
from app.engine_adapter.tools import (
    connectors_report as connectors_report,
)
from app.engine_adapter.tools import (
    tools_config_report as tools_config_report,
)
from app.engine_adapter.tools import (
    validate_tools_config as validate_tools_config,
)
from app.engine_adapter.workflow import run_workflow as run_workflow
