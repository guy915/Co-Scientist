"""Confined execution of commands the model authored.

`policy` carries the decision as data; `seatbelt` and `bwrap` render it
into the arguments of an OS primitive; `argv.wrap_argv` picks the backend
and, crucially, **fails closed** when no backend is available rather than
handing back the bare command.

Nothing here executes anything. Wrapping and running are separate so that
the wrapped argv can be inspected, logged, and asserted on without a
process being spawned -- and so that a test can prove the confinement
holds by running a command that tries to escape it.
"""

from co_scientist.sandbox.argv import (
    UnsupportedSandboxError,
    sandbox_backend,
    wrap_argv,
)
from co_scientist.sandbox.policy import (
    PROTECTED_METADATA_NAMES,
    SandboxKind,
    SandboxPolicy,
    read_only,
    workspace_write,
)

__all__ = [
    "PROTECTED_METADATA_NAMES",
    "SandboxKind",
    "SandboxPolicy",
    "UnsupportedSandboxError",
    "read_only",
    "sandbox_backend",
    "workspace_write",
    "wrap_argv",
]
