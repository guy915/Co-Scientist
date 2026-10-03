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
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from co_scientist.patch.parse import (
    AddFile,
    DeleteFile,
    FileOp,
    Patch,
    PatchError,
    UpdateFile,
)

# Characters a model substitutes for their ASCII equivalents, usually via
# a smart-quotes pass somewhere upstream. Normalizing these is what stops
# a correct edit failing because a quote changed shape in transit.
_PUNCTUATION_EQUIVALENTS = {
    # Written as escapes, not literals: these are precisely the
    # characters that are hard to tell apart on sight, which is why they
    # need folding in the first place.
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201a": "'",  # single low-9 quotation mark
    "\u201b": "'",  # single high-reversed-9 quotation mark
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
    "\u201e": '"',  # double low-9 quotation mark
    "\u2032": "'",  # prime
    "\u2033": '"',  # double prime
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
    "\u00a0": " ",  # no-break space
    "\u2026": "...",  # horizontal ellipsis
}


def _normalize_punctuation(text: str) -> str:
    """Folds look-alike Unicode punctuation to its ASCII equivalent."""
    folded = unicodedata.normalize("NFC", text)
    for source, target in _PUNCTUATION_EQUIVALENTS.items():
        folded = folded.replace(source, target)
    return folded


# The ladder, most exact first. Each entry is a canonicalization applied
# to both sides before comparison; equality under it defines that rung.
_LADDER = (
    ("exact", lambda line: line),
    ("trailing-whitespace", lambda line: line.rstrip()),
    ("surrounding-whitespace", lambda line: line.strip()),
    (
        "unicode-punctuation",
        lambda line: _normalize_punctuation(line).strip(),
    ),
)


@dataclass(frozen=True)
class SeekResult:
    """Where an anchor was found, and how exactly it matched.

    Attributes:
        start: Index of the first matching line.
        end: Index one past the last matching line.
        rung: Which ladder rung matched, for reporting. An edit that
            only applied after whitespace folding is worth being able to
            say so.
    """

    start: int
    end: int
    rung: str


def _matches_at(
    lines: list[str],
    anchor: tuple[str, ...],
    index: int,
    canonicalize: object,
) -> bool:
    """Reports whether the anchor matches at index under one rung."""
    fold = canonicalize  # narrowed by the caller; kept callable-typed
    assert callable(fold)
    return all(
        fold(lines[index + offset]) == fold(text)
        for offset, text in enumerate(anchor)
    )


def _first_match_on_rung(
    lines: list[str],
    anchor: tuple[str, ...],
    start: int,
    rung: str,
    fold: object,
) -> SeekResult | None:
    """Scans for the anchor under a single ladder rung."""
    last = len(lines) - len(anchor)
    for index in range(start, last + 1):
        if _matches_at(lines, anchor, index, fold):
            return SeekResult(index, index + len(anchor), rung)
    return None


def seek_anchor(
    lines: list[str], anchor: tuple[str, ...], start: int = 0
) -> SeekResult | None:
    """Finds a hunk's anchor at or after ``start``.

    Args:
        lines: The file's lines, without terminators.
        anchor: The context and removal lines the hunk expects.
        start: Index to search from -- the monotonic cursor, which is
            what makes repeated identical blocks resolve in order.

    Returns:
        Where the anchor matched, or None if no rung matched anywhere at
        or after ``start``.
    """
    if not anchor:
        return SeekResult(start, start, "empty")
    if len(lines) - len(anchor) < start:
        return None

    # Rung-major: a whole-file scan at an exact match is preferred over
    # a nearer approximate one, so a file containing both is edited at
    # the place that genuinely matches.
    for rung, fold in _LADDER:
        found = _first_match_on_rung(lines, anchor, start, rung, fold)
        if found is not None:
            return found
    return None


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
