"""Back-compat shim: the progress helper moved to ``co_scientist.progress``.

Re-exports preserve the ``co_scientist.nodes.progress`` import path. New code
should import from ``co_scientist.progress``.
"""

from co_scientist.progress import emit_progress

__all__ = ["emit_progress"]
