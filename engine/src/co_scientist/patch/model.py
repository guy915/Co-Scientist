"""The V4A patch model: what an edit envelope can ask for.

One envelope carries operations across several files, which is the
property that makes this format worth porting: a refactor that touches
four files is one atomic proposal rather than four independent edits
whose intermediate states are all broken.

Edits are anchored by *context* -- the surrounding lines -- rather than
by line numbers. That is what removes the read-before-write bookkeeping
every line-addressed editor needs: if the file moved under the model,
its context no longer matches and the edit fails loudly, so the match is
itself the staleness check.
"""

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
