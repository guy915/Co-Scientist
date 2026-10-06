"""Context anchors reject stale edits instead of applying them at obsolete
line numbers.
"""

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class LineKind(Enum):
    CONTEXT = " "
    REMOVE = "-"
    ADD = "+"


@dataclass(frozen=True)
class PatchLine:
    kind: LineKind
    text: str


@dataclass(frozen=True)
class Hunk:
    """Hunk headers are advisory: a guessed function name cannot veto
    matching context.
    """

    lines: tuple[PatchLine, ...]
    header: str | None = None

    @property
    def anchor(self) -> tuple[str, ...]:
        return tuple(
            line.text for line in self.lines if line.kind in (LineKind.CONTEXT, LineKind.REMOVE)
        )

    @property
    def replacement(self) -> tuple[str, ...]:
        return tuple(
            line.text for line in self.lines if line.kind in (LineKind.CONTEXT, LineKind.ADD)
        )


@dataclass(frozen=True)
class AddFile:
    path: str
    content: str


@dataclass(frozen=True)
class DeleteFile:
    path: str


@dataclass(frozen=True)
class UpdateFile:
    path: str
    hunks: tuple[Hunk, ...] = field(default_factory=tuple)
    move_to: str | None = None


FileOp = AddFile | DeleteFile | UpdateFile


@dataclass(frozen=True)
class Patch:
    operations: tuple[FileOp, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(op.path for op in self.operations)


class PatchError(ValueError):
    """Both parse and application failures give the model actionable feedback
    to correct its patch.
    """


_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_ADD = "*** Add File: "
_DELETE = "*** Delete File: "
_UPDATE = "*** Update File: "
_MOVE = "*** Move to: "
_EOF_MARKER = "*** End of File"

_HEADER_RE = re.compile(r"^@@(?: (?P<text>.*))?$")

_OPERATION_PREFIXES = (_ADD, _DELETE, _UPDATE)


def _is_operation_start(line: str) -> bool:
    return line.startswith(_OPERATION_PREFIXES) or line == _END


def _parse_body_line(line: str) -> PatchLine:
    if line == "":
        # A blank context line is " ", which trailing-whitespace
        # stripping removes somewhere between the model and here.
        return PatchLine(LineKind.CONTEXT, "")
    marker, text = line[0], line[1:]
    for kind in LineKind:
        if marker == kind.value:
            return PatchLine(kind, text)
    raise PatchError(
        f"unrecognized line in hunk: {line!r} (expected it to start with ' ', '-', or '+')"
    )


class _Cursor:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.index = 0

    @property
    def done(self) -> bool:
        return self.index >= len(self._lines)

    def peek(self) -> str:
        return self._lines[self.index]

    def take(self) -> str:
        line = self._lines[self.index]
        self.index += 1
        return line


def _parse_add(cursor: _Cursor, path: str) -> AddFile:
    body: list[str] = []
    while not cursor.done and not _is_operation_start(cursor.peek()):
        line = cursor.take()
        if not line.startswith("+"):
            raise PatchError(
                f"every line of an added file must start with '+'; got {line!r} in {path!r}"
            )
        body.append(line[1:])
    content = "\n".join(body)
    if body:
        content += "\n"
    return AddFile(path=path, content=content)


def _flush(hunks: list[Hunk], current: list[PatchLine], header: str | None) -> list[PatchLine]:
    if current:
        hunks.append(Hunk(tuple(current), header))
    return []


def _parse_move(cursor: _Cursor) -> str | None:
    if not cursor.done and cursor.peek().startswith(_MOVE):
        return cursor.take()[len(_MOVE) :].strip()
    return None


def _parse_update(cursor: _Cursor, path: str) -> UpdateFile:
    move_to = _parse_move(cursor)
    hunks: list[Hunk] = []
    current: list[PatchLine] = []
    header: str | None = None

    while not cursor.done and not _is_operation_start(cursor.peek()):
        line = cursor.take()
        if line == _EOF_MARKER:
            continue
        match = _HEADER_RE.match(line)
        if match:
            current = _flush(hunks, current, header)
            header = match.group("text")
            continue
        current.append(_parse_body_line(line))

    _flush(hunks, current, header)
    if not hunks:
        raise PatchError(f"update of {path!r} contains no changes")
    return UpdateFile(path=path, hunks=tuple(hunks), move_to=move_to)


def _parse_operation(cursor: _Cursor) -> FileOp:
    line = cursor.take()
    if line.startswith(_ADD):
        return _parse_add(cursor, line[len(_ADD) :].strip())
    if line.startswith(_DELETE):
        return DeleteFile(path=line[len(_DELETE) :].strip())
    return _parse_update(cursor, line[len(_UPDATE) :].strip())


def _envelope_lines(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines or lines[0].rstrip() != _BEGIN:
        raise PatchError(f"patch must start with {_BEGIN!r}")
    if lines[-1].rstrip() != _END:
        raise PatchError(f"patch must end with {_END!r}")
    return lines[1:-1]


def parse_patch(text: str) -> Patch:
    cursor = _Cursor(_envelope_lines(text))
    operations: list[FileOp] = []

    while not cursor.done:
        line = cursor.peek()
        if not line.strip():
            cursor.take()
            continue
        if not line.startswith(_OPERATION_PREFIXES):
            raise PatchError(
                f"expected a file operation, got {line!r}. Each operation "
                f"starts with one of {_OPERATION_PREFIXES}"
            )
        operations.append(_parse_operation(cursor))

    if not operations:
        raise PatchError("patch contains no file operations")
    return Patch(operations=tuple(operations))


# Fold smart punctuation so transit substitutions cannot invalidate otherwise
# matching context.
_PUNCTUATION_EQUIVALENTS = {
    # Escapes distinguish visually confusable punctuation.
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2032": "'",
    "\u2033": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\u00a0": " ",
    "\u2026": "...",
}


def _normalize_punctuation(text: str) -> str:
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
    start: int
    end: int
    rung: str


def _matches_at(
    lines: list[str],
    anchor: tuple[str, ...],
    index: int,
    canonicalize: object,
) -> bool:
    fold = canonicalize
    assert callable(fold)
    return all(fold(lines[index + offset]) == fold(text) for offset, text in enumerate(anchor))


def _first_match_on_rung(
    lines: list[str],
    anchor: tuple[str, ...],
    start: int,
    rung: str,
    fold: object,
) -> SeekResult | None:
    last = len(lines) - len(anchor)
    for index in range(start, last + 1):
        if _matches_at(lines, anchor, index, fold):
            return SeekResult(index, index + len(anchor), rung)
    return None


def seek_anchor(lines: list[str], anchor: tuple[str, ...], start: int = 0) -> SeekResult | None:
    """Search from a monotonic cursor so repeated context blocks resolve in
    order.
    """
    if not anchor:
        return SeekResult(start, start, "empty")
    if len(lines) - len(anchor) < start:
        return None

    # Prefer exact matches anywhere over nearer approximate matches.
    for rung, fold in _LADDER:
        found = _first_match_on_rung(lines, anchor, start, rung, fold)
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class PlannedWrite:
    path: Path
    content: str | None  # None means delete
    original_path: Path | None = None  # set when the op renames


@dataclass(frozen=True)
class ApplyResult:
    changed: tuple[str, ...]
    rungs: dict[str, tuple[str, ...]]


def _resolve_within(root: Path, relative: str) -> Path:
    """Check canonical paths after symlink resolution to confine every
    operation.
    """
    if os.path.isabs(relative):
        raise PatchError(f"patch paths must be relative; got {relative!r}")
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PatchError(f"patch path {relative!r} resolves outside the patch root")
    return candidate


def _read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # Drop the trailing split element, then restore the newline on write to
    # match hunk line counts.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _plan_update(root: Path, op: UpdateFile) -> tuple[PlannedWrite, tuple[str, ...]]:
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


def _plan_operation(root: Path, op: FileOp) -> tuple[PlannedWrite, tuple[str, ...]]:
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
    if write.content is None:
        write.path.unlink()
        return
    write.path.parent.mkdir(parents=True, exist_ok=True)
    write.path.write_text(write.content, encoding="utf-8")
    if write.original_path and write.original_path != write.path:
        write.original_path.unlink()


def apply_patch(patch: Patch, root: Path) -> ApplyResult:
    """Plan every operation before writing, so an unresolved operation leaves
    the tree unchanged.
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

    changed = tuple(str(write.path.relative_to(root.resolve())) for write in plans)
    logger.debug("applied patch touching %s", changed)
    return ApplyResult(changed=changed, rungs=rungs)


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
