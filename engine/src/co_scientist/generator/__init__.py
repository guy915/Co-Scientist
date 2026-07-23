"""Main HypothesisGenerator class.

Provides an interface inspired by the original AI-CoScientist integration,
but uses LangGraph under the hood.

The public entry point is ``HypothesisGenerator`` (defined in ``core``).
The package splits the implementation by responsibility: graph topology
(``graph``), per-run setup (``run_setup``), initial-state assembly
(``initial_state``), and stream/result shaping (``streaming``). Every
module-level name historically defined by the old single-module
``co_scientist.generator`` is re-exported here so existing imports keep
working.
"""

from co_scientist.generator.core import HypothesisGenerator
from co_scientist.generator.graph import CompiledWorkflow as CompiledWorkflow
from co_scientist.generator.graph import (
    _add_workflow_edges as _add_workflow_edges,
)
from co_scientist.generator.graph import (
    _add_workflow_nodes as _add_workflow_nodes,
)
from co_scientist.generator.graph import (
    _route_next_task as _route_next_task,
)
from co_scientist.generator.graph import _WorkflowBuilder as _WorkflowBuilder
from co_scientist.generator.initial_state import (
    RunCallbacks as RunCallbacks,
)
from co_scientist.generator.initial_state import (
    _build_initial_state as _build_initial_state,
)
from co_scientist.generator.initial_state import (
    _initial_run_identity_fields as _initial_run_identity_fields,
)
from co_scientist.generator.initial_state import (
    _initial_runtime_fields as _initial_runtime_fields,
)
from co_scientist.generator.initial_state import (
    _initial_user_and_literature_fields as _initial_user_and_literature_fields,
)
from co_scientist.generator.options import GeneratorOptions as GeneratorOptions
from co_scientist.generator.run_setup import (
    _build_tool_registry as _build_tool_registry,
)
from co_scientist.generator.run_setup import (
    _configure_cache_dir_env as _configure_cache_dir_env,
)
from co_scientist.generator.run_setup import (
    _resolve_dev_isolation_flag as _resolve_dev_isolation_flag,
)
from co_scientist.generator.run_setup import (
    _resolve_run_identity as _resolve_run_identity,
)
from co_scientist.generator.run_setup import (
    _resolve_tool_calling_generation as _resolve_tool_calling_generation,
)
from co_scientist.generator.streaming import (
    _STREAMED_STATE_KEYS as _STREAMED_STATE_KEYS,
)
from co_scientist.generator.streaming import (
    _build_generation_result as _build_generation_result,
)
from co_scientist.generator.streaming import (
    _build_stream_state_dict as _build_stream_state_dict,
)
from co_scientist.generator.streaming import (
    _initial_cumulative_stream_state as _initial_cumulative_stream_state,
)
from co_scientist.generator.streaming import (
    _merge_node_state_into_cumulative as _merge_node_state_into_cumulative,
)

# Export for backwards compatibility
__all__ = ["HypothesisGenerator"]
