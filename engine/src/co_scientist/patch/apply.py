"""Applying a patch: plan everything, then write everything.

Two phases, and the split is the point. Every operation is resolved
against the current files and turned into a complete intended content in
memory; only once all of them succeed does anything reach disk. A patch
that fails its third hunk therefore leaves the working tree exactly as
it found it, rather than half-edited in a state neither the model nor
the user asked for -- which matters more here than in a normal coding
agent, because a half-applied edit can still run, and a hypothesis
verdict computed from it would be wrong rather than merely broken.

Path containment is enforced per operation and after resolution, so a
patch cannot reach outside its root by symlink or by ``..`` -- the same
reason writable roots are resolved before reaching the sandbox.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from co_scientist.patch.model import (
    AddFile,
    DeleteFile,
    FileOp,
    Patch,
    PatchError,
    UpdateFile,
)
from co_scientist.patch.seek import seek_anchor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannedWrite:
    """One file's intended end state."""

    path: Path
    content: str | None  # None means delete
    original_path: Path | None = None  # set when the op renames


@dataclass(frozen=True)
class ApplyResult:
    """What a patch did.

    Attributes:
        changed: Paths written, created, or removed, relative to root.
        rungs: Per-path list of which ladder rung each hunk matched at,
            so an edit that only applied after whitespace folding can be
            reported rather than passing silently.
    """

    changed: tuple[str, ...]
    rungs: dict[str, tuple[str, ...]]


def _resolve_within(root: Path, relative: str) -> Path:
    """Resolves a patch path, refusing anything outside the root.

    Raises:
        PatchError: If the path escapes the root. Checked after
            resolution so a symlink cannot be used to step outside.
    """
    if os.path.isabs(relative):
        raise PatchError(f"patch paths must be relative; got {relative!r}")
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PatchError(
            f"patch path {relative!r} resolves outside the patch root"
        )
    return candidate


def _read_lines(path: Path) -> list[str]:
    """Reads a file as lines without terminators."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # A trailing newline yields a final empty element; drop it so line
    # counts match what a hunk's context describes, and restore it on
    # write.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _plan_update(
    root: Path, op: UpdateFile
) -> tuple[PlannedWrite, tuple[str, ...]]:
    """Resolves an update into its intended content.

    Raises:
        PatchError: If the file is missing or a hunk's context does not
            match. The message names the first unmatched line, which is
            the actionable part for whoever rewrites the patch.
    """
    source = _resolve_within(root, op.path)
    if not source.is_file():
        raise PatchError(f"cannot update {op.path!r}: file does not exist")

    lines = _read_lines(source)
    cursor = 0
    rungs: list[str] = []

    for number, hunk in enumerate(op.hunks, start=1):
        found = seek_anchor(lines, hunk.anchor, cursor)
        if found is None:
            first = hunk.anchor[0] if hunk.anchor else "<empty>"
            raise PatchError(
                f"hunk {number} of {op.path!r} did not match: no occurrence "
                f"of its context at or after line {cursor + 1}. First "
                f"expected line was {first!r}. The file may have changed "
                f"since it was read."
            )
        replacement = list(hunk.replacement)
        lines[found.start : found.end] = replacement
        cursor = found.start + len(replacement)
        rungs.append(found.rung)

    target = _resolve_within(root, op.move_to) if op.move_to else source
    content = "\n".join(lines) + "\n" if lines else ""
    return (
        PlannedWrite(
            path=target,
            content=content,
            original_path=source if op.move_to else None,
        ),
        tuple(rungs),
    )


def _plan_operation(
    root: Path, op: FileOp
) -> tuple[PlannedWrite, tuple[str, ...]]:
    """Resolves one operation into an intended end state."""
    if isinstance(op, AddFile):
        target = _resolve_within(root, op.path)
        if target.exists():
            raise PatchError(
                f"cannot add {op.path!r}: it already exists. Use "
                f"'*** Update File:' to change an existing file."
            )
        return PlannedWrite(path=target, content=op.content), ()

    if isinstance(op, DeleteFile):
        target = _resolve_within(root, op.path)
        if not target.is_file():
            raise PatchError(f"cannot delete {op.path!r}: file does not exist")
        return PlannedWrite(path=target, content=None), ()

    return _plan_update(root, op)


def _commit(write: PlannedWrite) -> None:
    """Writes one planned change to disk."""
    if write.content is None:
        write.path.unlink()
        return
    write.path.parent.mkdir(parents=True, exist_ok=True)
    write.path.write_text(write.content, encoding="utf-8")
    if write.original_path and write.original_path != write.path:
        write.original_path.unlink()


def apply_patch(patch: Patch, root: Path) -> ApplyResult:
    """Applies a patch to the tree at ``root``, all or nothing.

    Args:
        patch: The parsed envelope.
        root: Directory every path in the patch is relative to.

    Returns:
        What changed, and which ladder rung each hunk matched at.

    Raises:
        PatchError: If any operation cannot be resolved. Nothing is
            written in that case -- the whole patch is planned before
            any of it is committed.
    """
    plans: list[PlannedWrite] = []
    rungs: dict[str, tuple[str, ...]] = {}

    for op in patch.operations:
        write, matched = _plan_operation(root, op)
        plans.append(write)
        if matched:
            rungs[op.path] = matched

    for write in plans:
        _commit(write)

    changed = tuple(
        str(write.path.relative_to(root.resolve())) for write in plans
    )
    logger.debug("applied patch touching %s", changed)
    return ApplyResult(changed=changed, rungs=rungs)
