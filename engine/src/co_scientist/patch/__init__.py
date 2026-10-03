"""Context-anchored multi-file editing (the V4A ``apply_patch`` format).

Chosen over line-addressed editing on the strongest evidence available
from the survey: Codex uses this format exclusively, and opencode ships
*both* this and a line/string editor while giving this one to its
strongest models and denying them the other entirely.

The property that earns it: an edit is located by the lines around it,
so a stale patch fails to match instead of applying at a line number
that now means something else. No read-before-write bookkeeping is
needed because the match *is* the staleness check.
"""

from co_scientist.patch.apply import (
    ApplyResult,
    SeekResult,
    apply_patch,
    seek_anchor,
)
from co_scientist.patch.parse import (
    AddFile,
    DeleteFile,
    Hunk,
    LineKind,
    Patch,
    PatchError,
    PatchLine,
    UpdateFile,
    parse_patch,
)

__all__ = [
    "AddFile",
    "ApplyResult",
    "DeleteFile",
    "Hunk",
    "LineKind",
    "Patch",
    "PatchError",
    "PatchLine",
    "SeekResult",
    "UpdateFile",
    "apply_patch",
    "parse_patch",
    "seek_anchor",
]
