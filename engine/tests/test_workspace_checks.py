"""Tests for the parse checks fed back with an edit.

The value of these is timing, not detection: a file that does not parse
is found eventually, two tool calls later, detached from the change that
caused it. So the tests assert the finding arrives *on the apply_patch
result* rather than testing the checkers in isolation.

Everything here is also a test of what stays silent. A check that
reported on a file it could not read, or vetoed a write it had already
performed, would be worse than no check at all.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from co_scientist.workspace import WorkspaceSession, WorkspaceToolProvider
from co_scientist.workspace.checks import MAX_FINDINGS, check_paths


def _apply(tmp_path: Path, body: list[str]) -> dict[str, Any]:
    """Applies a patch through the tool surface, returning its payload."""
    patch = "\n".join(["*** Begin Patch", *body, "*** End Patch", ""])
    provider = WorkspaceToolProvider(WorkspaceSession(tmp_path))
    message = asyncio.run(
        provider.execute_tool_call(
            SimpleNamespace(
                id="call_apply_patch",
                function=SimpleNamespace(
                    name="apply_patch",
                    arguments=json.dumps({"patch": patch}),
                ),
            )
        )
    )
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


def test_a_syntax_error_comes_back_with_the_edit(tmp_path: Path) -> None:
    """The whole point: same turn, not two tool calls later."""
    payload = _apply(
        tmp_path, ["*** Add File: broken.py", "+def f(:", "+    pass"]
    )
    assert payload["changed"] == ["broken.py"]
    assert payload["problems"][0]["path"] == "broken.py"
    assert "SyntaxError" in payload["problems"][0]["message"]


def test_a_finding_does_not_undo_the_write(tmp_path: Path) -> None:
    """The write already happened; a check result is not a veto.

    Refusing edits that do not parse would also make writing a file in
    two steps impossible.
    """
    _apply(tmp_path, ["*** Add File: broken.py", "+def f(:"])
    assert (tmp_path / "broken.py").read_text() == "def f(:\n"


def test_a_clean_edit_says_nothing(tmp_path: Path) -> None:
    """Silence is the common case and must not carry an empty key."""
    payload = _apply(tmp_path, ["*** Add File: fine.py", "+VALUE = 1"])
    assert "problems" not in payload


def test_a_file_type_with_no_checker_says_nothing(tmp_path: Path) -> None:
    payload = _apply(tmp_path, ["*** Add File: notes.md", "+# heading ("])
    assert "problems" not in payload


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    payload = _apply(tmp_path, ["*** Add File: config.json", '+{"a": ,}'])
    assert "invalid JSON" in payload["problems"][0]["message"]


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    payload = _apply(
        tmp_path, ["*** Add File: config.yaml", "+a: [1, 2", "+b: 3"]
    )
    assert "invalid YAML" in payload["problems"][0]["message"]


def test_a_deleted_path_is_not_a_finding(tmp_path: Path) -> None:
    """A patch reports what it changed, including what it removed."""
    assert check_paths(tmp_path, ["gone.py"]) == ()


def test_a_binary_file_is_not_a_finding(tmp_path: Path) -> None:
    """Unreadable is not the same as wrong."""
    (tmp_path / "blob.json").write_bytes(b"\xff\xfe\x00binary")
    assert check_paths(tmp_path, ["blob.json"]) == ()


def test_findings_are_capped(tmp_path: Path) -> None:
    """A patch that rewrote a tree must not return a wall of text."""
    names = []
    for index in range(MAX_FINDINGS + 5):
        name = f"broken_{index}.py"
        (tmp_path / name).write_text("def f(:")
        names.append(name)
    assert len(check_paths(tmp_path, names)) == MAX_FINDINGS
