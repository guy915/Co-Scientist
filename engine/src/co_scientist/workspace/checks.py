"""Checks run on a file the moment it is edited, fed back in the same turn.

An edit that does not parse is discovered eventually -- two tool calls
later, when something tries to run it, by which point the model has moved
on and the traceback arrives detached from the change that caused it.
Answering the edit itself with "this file no longer parses, line 14" costs
one round-trip instead of three, and is the difference between a typo and
a debugging session.

**These are deterministic parse checks, not a linter.** The reference this
came from shells out to the project's own tooling; that is not available
here. `ruff` and `mypy` are dev dependencies absent from the production
image, so an automatic linter pass would be a subprocess per edit that
silently does nothing exactly where the model most needs help -- the
failure mode this codebase keeps meeting, where a missing backend is
indistinguishable from a clean result. Parsing is stdlib, always
available, and never reports an opinion. A linter is one `run_command`
away when the model wants one, and it can then see for itself whether the
tool exists.

**Findings never fail the patch.** The write already happened; a check
result is information, not a veto. Refusing edits that do not parse would
also make the ordinary act of writing a file in two steps impossible.
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Beyond this a "file" is data, and parsing it costs more than the
# feedback is worth.
MAX_CHECKED_BYTES = 2_000_000

# One finding per file is the realistic case (parsers stop at the first
# error); the cap bounds a patch that rewrote a whole tree.
MAX_FINDINGS = 20


@dataclass(frozen=True)
class CheckFinding:
    """One problem found in an edited file.

    Attributes:
        path: Workspace-relative path.
        line: 1-based line, when the parser reported one.
        message: What is wrong, phrased for the model to fix.
    """

    path: str
    line: int | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        """Renders the finding for a tool result."""
        payload: dict[str, Any] = {"path": self.path, "message": self.message}
        if self.line is not None:
            payload["line"] = self.line
        return payload


def _check_python(source: str) -> tuple[int | None, str] | None:
    """Compiles a Python source file, reporting a syntax error."""
    try:
        compile(source, "<workspace>", "exec")
    except SyntaxError as exc:
        return exc.lineno, f"SyntaxError: {exc.msg}"
    except ValueError as exc:
        # e.g. source containing a null byte, which compile() rejects
        # without it being a SyntaxError.
        return None, f"not valid Python source: {exc}"
    return None


def _check_json(source: str) -> tuple[int | None, str] | None:
    """Parses a JSON file, reporting a decode error."""
    try:
        json.loads(source)
    except ValueError as exc:
        line = getattr(exc, "lineno", None)
        return line, f"invalid JSON: {exc}"
    return None


def _check_yaml(source: str) -> tuple[int | None, str] | None:
    """Parses a YAML file, reporting a scan or parse error."""
    import yaml

    try:
        yaml.safe_load(source)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        return line, f"invalid YAML: {getattr(exc, 'problem', exc)}"
    return None


_CHECKERS = {
    ".py": _check_python,
    ".json": _check_json,
    ".yaml": _check_yaml,
    ".yml": _check_yaml,
}


def _read_source(target: Path) -> str | None:
    """Reads a file for checking, or None when it should be skipped."""
    try:
        if target.stat().st_size > MAX_CHECKED_BYTES:
            return None
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Deleted by the same patch, or not text. Neither is a finding:
        # this function only reports what a parser actually rejected.
        return None


def _check_one(root: Path, relative: str) -> CheckFinding | None:
    """Checks one edited file, or returns None when there is nothing to say."""
    checker = _CHECKERS.get(Path(relative).suffix.lower())
    if checker is None:
        return None
    source = _read_source(root / relative)
    if source is None:
        return None
    problem = checker(source)
    if problem is None:
        return None
    line, message = problem
    return CheckFinding(relative, line, message)


def check_paths(root: Path, paths: Iterable[str]) -> tuple[CheckFinding, ...]:
    """Parses each edited file whose type has a checker.

    Args:
        root: The workspace root the paths are relative to.
        paths: Workspace-relative paths the patch wrote.

    Returns:
        Findings, capped at ``MAX_FINDINGS``. Empty when everything
        parsed, when nothing had a checker, and when a file could not be
        read -- all three are silence by design.
    """
    findings: list[CheckFinding] = []
    for relative in paths:
        finding = _check_one(root, relative)
        if finding is not None:
            findings.append(finding)
        if len(findings) >= MAX_FINDINGS:
            break
    return tuple(findings)
