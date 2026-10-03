"""Parsing the V4A envelope into a Patch.

Strict about structure and forgiving about nothing. A patch that parses
loosely is worse than one that fails: the model resubmits a corrected
envelope in the failure case, whereas a mis-parsed hunk silently edits
the wrong thing and the mistake surfaces much later as a wrong result.

The one place ambiguity is real is a line inside a hunk that is empty. A
context line is ``" "`` plus its text, so a blank context line is a
single space -- which trailing-whitespace-trimming editors and several
providers strip. An empty line inside a hunk is therefore read as blank
context rather than rejected.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


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
