"""Back-compat shim: reflection helpers moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.reflection_helpers`` import path
(the literature-review enrichment step reuses ``extract_entity_names``). New
code should import from ``co_scientist.agents.reflection``.
"""

from co_scientist.agents.reflection.reflection_helpers import (
    extract_entity_names,
)

__all__ = ["extract_entity_names"]
