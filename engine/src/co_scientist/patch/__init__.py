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

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class LineKind(Enum):
    """The role of one line inside a hunk."""

    CONTEXT = " "
    REMOVE = "-"
    ADD = "+"


@dataclass(frozen=True)
class PatchLine:
    """One line of a hunk, with the role it plays."""

    kind: LineKind
    text: str


@dataclass(frozen=True)
class Hunk:
    """A contiguous edit within one file.

    Attributes:
        lines: The context, removals, and additions in file order.
        header: The optional ``@@`` marker's text. Advisory only -- it
            helps a reader, and this implementation does not anchor on
            it, because a model that guesses a wrong function name would
            otherwise fail an edit that is perfectly well specified by
            its context.
    """

    lines: tuple[PatchLine, ...]
    header: str | None = None

    @property
    def anchor(self) -> tuple[str, ...]:
        """The lines that must already exist, in order."""
        return tuple(
            line.text
            for line in self.lines
            if line.kind in (LineKind.CONTEXT, LineKind.REMOVE)
        )

    @property
    def replacement(self) -> tuple[str, ...]:
        """The lines that replace the anchor."""
        return tuple(
            line.text
            for line in self.lines
            if line.kind in (LineKind.CONTEXT, LineKind.ADD)
        )


@dataclass(frozen=True)
class AddFile:
    """Create a file that does not yet exist."""

    path: str
    content: str


@dataclass(frozen=True)
class DeleteFile:
    """Remove an existing file."""

    path: str


@dataclass(frozen=True)
class UpdateFile:
    """Edit an existing file, optionally moving it.

    Attributes:
        path: The file to edit, relative to the patch root.
        hunks: The edits, in the order they appear in the file.
        move_to: New path, when the operation also renames.
    """

    path: str
    hunks: tuple[Hunk, ...] = field(default_factory=tuple)
    move_to: str | None = None


FileOp = AddFile | DeleteFile | UpdateFile


@dataclass(frozen=True)
class Patch:
    """A complete edit envelope."""

    operations: tuple[FileOp, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        """Every path the patch reads or writes."""
        return tuple(op.path for op in self.operations)


class PatchError(ValueError):
    """A patch could not be parsed or could not be applied.

    One exception type for both phases on purpose: to the model that
    wrote the patch, "your envelope is malformed" and "your context did
    not match" are the same kind of feedback -- something to correct and
    resubmit -- and both must name what failed precisely enough to fix.
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
    """Reports whether a line begins a new file operation."""
    return line.startswith(_OPERATION_PREFIXES) or line == _END


def _parse_body_line(line: str) -> PatchLine:
    """Reads one line of an update hunk.

    Raises:
        PatchError: If the line carries no recognizable role marker.
    """
    if line == "":
        # A blank context line is " ", which trailing-whitespace
        # stripping removes somewhere between the model and here.
        return PatchLine(LineKind.CONTEXT, "")
    marker, text = line[0], line[1:]
    for kind in LineKind:
        if marker == kind.value:
            return PatchLine(kind, text)
    raise PatchError(
        f"unrecognized line in hunk: {line!r} (expected it to start with "
        f"' ', '-', or '+')"
    )


class _Cursor:
    """A position in the patch's lines, consumed front to back."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.index = 0

    @property
    def done(self) -> bool:
        """Whether every line has been consumed."""
        return self.index >= len(self._lines)

    def peek(self) -> str:
        """Returns the current line without consuming it."""
        return self._lines[self.index]

    def take(self) -> str:
        """Consumes and returns the current line."""
        line = self._lines[self.index]
        self.index += 1
        return line


def _parse_add(cursor: _Cursor, path: str) -> AddFile:
    """Reads an Add File operation's body."""
    body: list[str] = []
    while not cursor.done and not _is_operation_start(cursor.peek()):
        line = cursor.take()
        if not line.startswith("+"):
            raise PatchError(
                f"every line of an added file must start with '+'; "
                f"got {line!r} in {path!r}"
            )
        body.append(line[1:])
    content = "\n".join(body)
    if body:
        content += "\n"
    return AddFile(path=path, content=content)


def _flush(
    hunks: list[Hunk], current: list[PatchLine], header: str | None
) -> list[PatchLine]:
    """Closes the hunk under construction, if it has any lines."""
    if current:
        hunks.append(Hunk(tuple(current), header))
    return []


def _parse_move(cursor: _Cursor) -> str | None:
    """Reads an optional Move to: line."""
    if not cursor.done and cursor.peek().startswith(_MOVE):
        return cursor.take()[len(_MOVE) :].strip()
    return None


def _parse_update(cursor: _Cursor, path: str) -> UpdateFile:
    """Reads an Update File operation's move, headers, and hunks."""
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
    """Reads one file operation, including its body."""
    line = cursor.take()
    if line.startswith(_ADD):
        return _parse_add(cursor, line[len(_ADD) :].strip())
    if line.startswith(_DELETE):
        return DeleteFile(path=line[len(_DELETE) :].strip())
    return _parse_update(cursor, line[len(_UPDATE) :].strip())


def _envelope_lines(text: str) -> list[str]:
    """Strips the envelope markers and returns the operation lines.

    Raises:
        PatchError: If the Begin/End markers are missing or reversed.
    """
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
    """Parses a V4A patch envelope.

    Args:
        text: The full envelope, Begin marker through End marker.

    Returns:
        The parsed patch.

    Raises:
        PatchError: If the envelope is malformed. The message names what
            was wrong, because its audience is the model that will
            rewrite the patch.
    """
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
