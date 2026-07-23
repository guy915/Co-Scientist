"""Evidence-reference checking for the parity ledger.

Validates the backtick-quoted references in a ``verified`` row's Test/Eval
cell: repo-relative paths, globs, and pytest nodeids such as
``tests/test_foo.py::test_bar`` (a bare ``::test_name`` continues the
previously cited file). Imported by :mod:`evaluations.parity_check`, which
owns the ledger parsing and the CLI.
"""

from __future__ import annotations

import pathlib
import re

# Evidence references are backtick-quoted in the Test/Eval cell.
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _looks_like_path(token: str) -> bool:
    """True when a backticked token should be treated as a file reference.

    File references contain a ``/`` and no whitespace; everything else in the
    cell (identifiers, commands like ``python -m evaluations.smoke``, prose)
    is descriptive and not checked.

    Args:
        token: The path part of a backticked token (nodeid suffix removed).

    Returns:
        Whether the token is a checkable repo-relative file reference.
    """
    return "/" in token and not any(ch.isspace() for ch in token)


def _test_defined_in(file_path: pathlib.Path, test_name: str) -> bool:
    """True when ``test_name`` looks defined inside a cited test file.

    Only Python files are checked (``def <name>(`` covers plain and async
    test functions); nodeids citing other file types pass on existence alone.

    Args:
        file_path: The existing evidence file on disk.
        test_name: The test function name from the ``::`` nodeid suffix.

    Returns:
        Whether the named test appears to be defined in the file.
    """
    if file_path.suffix != ".py":
        return True
    text = file_path.read_text(encoding="utf-8")
    return f"def {test_name}(" in text


def _check_continuation_token(
    prefix: str,
    token: str,
    last_file: pathlib.Path | None,
    repo_root: pathlib.Path,
) -> tuple[int, list[str]]:
    """Check a bare ``::test_name`` token against the last cited file.

    Args:
        prefix: The ``file:line: id`` error prefix for this row.
        token: The backticked token, starting with ``::``.
        last_file: The previously cited evidence file, if any.
        repo_root: Directory that relative evidence paths resolve against.

    Returns:
        A ``(checked_increment, errors)`` pair.
    """
    if last_file is None:
        return 0, []
    name = token[2:]
    if _test_defined_in(last_file, name):
        return 1, []
    return 0, [
        f"{prefix} cites test {name!r} which is not defined "
        f"in {last_file.relative_to(repo_root)}"
    ]


def _check_glob_token(
    prefix: str, path_part: str, repo_root: pathlib.Path
) -> tuple[int, list[str]]:
    """Check a glob evidence token against the repo root."""
    if any(repo_root.glob(path_part)):
        return 1, []
    return 0, [
        f"{prefix} cites evidence glob {path_part!r} which "
        f"matches no files under the repo root"
    ]


def _check_path_token(
    prefix: str,
    token: str,
    repo_root: pathlib.Path,
) -> tuple[int, pathlib.Path | None, list[str]]:
    """Check one path/glob/nodeid token from a Test/Eval cell.

    Returns a ``(checked_increment, cited_file, errors)`` triple;
    ``cited_file`` is the resolved evidence file when the token named
    one directly.
    """
    path_part, _, test_name = token.partition("::")
    if not _looks_like_path(path_part):
        return 0, None, []
    if "*" in path_part:
        found, glob_errors = _check_glob_token(prefix, path_part, repo_root)
        return found, None, glob_errors
    file_path = repo_root / path_part
    if not file_path.is_file():
        return (
            0,
            None,
            [
                f"{prefix} cites evidence file {path_part!r} which does "
                f"not exist under the repo root"
            ],
        )
    errors: list[str] = []
    if test_name and not _test_defined_in(file_path, test_name):
        errors.append(
            f"{prefix} cites test {test_name!r} which is not defined "
            f"in {path_part}"
        )
    return 1, file_path, errors


def _evidence_errors(
    source: str,
    lineno: int,
    req_id: str,
    cell: str,
    repo_root: pathlib.Path,
) -> list[str]:
    """Validate the cited evidence of one ``verified`` row.

    Checks every backtick-quoted reference that looks like a file
    reference (path, glob, or pytest nodeid; a bare ``::test_name``
    continues the previously cited file). A ``verified`` row must yield
    at least one checkable reference. Returns human-readable error
    strings (empty when the evidence checks out).
    """
    prefix = f"{source}:{lineno}: {req_id!r}"
    errors: list[str] = []
    checked = 0
    last_file: pathlib.Path | None = None

    for raw in _BACKTICK_RE.findall(cell):
        token = raw.strip()
        if token.startswith("::"):
            found, errs = _check_continuation_token(
                prefix, token, last_file, repo_root
            )
        else:
            found, cited, errs = _check_path_token(prefix, token, repo_root)
            if cited is not None:
                last_file = cited
        checked += found
        errors.extend(errs)

    if checked == 0 and not errors:
        errors.append(
            f"{prefix} is 'verified' but its Test/Eval cell contains no "
            f"checkable file reference (expected a backticked path, glob, "
            f"or pytest nodeid relative to the repo root)"
        )
    return errors
