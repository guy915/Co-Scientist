"""Tests for redaction, spillover, and what reaches the model.

The framing question for this module is not "does redact() replace the
string" -- it plainly does -- but "is there a path from a secret to the
transcript that skips it". So the tests here run the real tool surface
wherever they can, rather than calling ``SecretRegistry`` directly: the
gap this closes in the harness the idea came from was not a broken
redactor, it was a second output path nobody routed through it.
"""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.sandbox import PROTECTED_METADATA_NAMES, sandbox_backend
from co_scientist.workspace import (
    LIST_FILES,
    MIN_SECRET_LENGTH,
    READ_FILE,
    RUN_COMMAND,
    SPILL_DIRECTORY,
    OutputRecorder,
    SecretRegistrationError,
    SecretRegistry,
    WorkspaceSession,
    WorkspaceToolProvider,
)

_requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None, reason="no sandbox backend on this platform"
)

_SECRET = "sk-live-9f3c2b71aa4d8e60"


def _call(name: str, arguments: Any = "{}") -> SimpleNamespace:
    """Builds a litellm-shaped tool call."""
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _registry(**secrets: str) -> SecretRegistry:
    """Builds a registry from name/value pairs."""
    registry = SecretRegistry()
    for name, value in secrets.items():
        registry.register(name, value)
    return registry


def _content(message: dict[str, Any]) -> dict[str, Any]:
    """Parses a tool-role message's JSON content."""
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


def _run(provider: WorkspaceToolProvider, argv: list[str]) -> dict[str, Any]:
    """Runs a command through the tool surface and returns its payload."""
    return _content(
        asyncio.run(
            provider.execute_tool_call(
                _call(RUN_COMMAND, json.dumps({"argv": argv}))
            )
        )
    )


# --- registration ---------------------------------------------------------


def test_a_short_value_is_refused_rather_than_masked() -> None:
    """Masking "abc" everywhere corrupts output that merely contains it."""
    with pytest.raises(SecretRegistrationError, match="cannot be masked"):
        _registry(TOKEN="a" * (MIN_SECRET_LENGTH - 1))


def test_environment_scan_finds_credential_shaped_names() -> None:
    registry = SecretRegistry()
    found = registry.register_environment(
        {
            "ANTHROPIC_API_KEY": _SECRET,
            "GITHUB_TOKEN": "ghp_0123456789abcdef",
            "PATH": "/usr/bin",
        }
    )
    assert set(found) == {"ANTHROPIC_API_KEY", "GITHUB_TOKEN"}


def test_environment_scan_skips_a_short_value_without_raising() -> None:
    """One odd variable must not stop the rest being protected."""
    registry = SecretRegistry()
    found = registry.register_environment(
        {"SHORT_KEY": "abc", "REAL_KEY": _SECRET}
    )
    assert found == ("REAL_KEY",)


def test_a_secret_containing_another_is_masked_as_itself() -> None:
    """Shortest-first would replace the inner value and strand the rest."""
    registry = _registry(INNER=_SECRET, OUTER=f"{_SECRET}-extended-suffix")
    assert registry.redact(f"{_SECRET}-extended-suffix") == "[redacted:OUTER]"


# --- the inline path, which is the one that was missed --------------------


@_requires_sandbox
def test_a_command_printing_a_secret_does_not_print_it(tmp_path: Path) -> None:
    """The gap being closed: stdout reaches the transcript untouched.

    Scrubbing stored artifacts and leaving the command's own output alone
    means one ``env`` publishes every injected credential.
    """
    echo = shutil.which("echo")
    if echo is None:  # pragma: no cover - environment-dependent
        pytest.skip("echo is not installed")
    provider = WorkspaceToolProvider(
        WorkspaceSession(tmp_path), secrets=_registry(API_KEY=_SECRET)
    )

    payload = _run(provider, [echo, _SECRET])

    assert _SECRET not in json.dumps(payload)
    assert "[redacted:API_KEY]" in payload["stdout"]


def test_reading_a_file_does_not_route_around_redaction(
    tmp_path: Path,
) -> None:
    """Otherwise ``cmd > f`` then read_file is the way past the other path."""
    (tmp_path / "captured.txt").write_text(f"key={_SECRET}\n")
    provider = WorkspaceToolProvider(
        WorkspaceSession(tmp_path), secrets=_registry(API_KEY=_SECRET)
    )

    payload = _content(
        asyncio.run(
            provider.execute_tool_call(
                _call(READ_FILE, json.dumps({"path": "captured.txt"}))
            )
        )
    )

    assert _SECRET not in payload["content"]


def test_output_is_dropped_whole_when_a_value_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard behind the redactor, triggered by breaking the redactor.

    Its condition is a bug in ``redact``, so it cannot be reached with
    real inputs -- and a defence that is never exercised is a defence
    nobody knows is wired up.
    """
    monkeypatch.setattr(SecretRegistry, "redact", lambda self, text: text)
    recorder = OutputRecorder(tmp_path, _registry(API_KEY=_SECRET))

    bounded = recorder.record("stdout", f"leaked {_SECRET}")

    assert _SECRET not in bounded.text
    assert "API_KEY" in bounded.text
    assert bounded.truncated


# --- spillover ------------------------------------------------------------


def test_a_long_stream_keeps_both_ends(tmp_path: Path) -> None:
    """A head-only truncation discards the half that holds the verdict."""
    recorder = OutputRecorder(tmp_path, preview_chars=200)
    text = f"START{'x' * 5000}END"

    bounded = recorder.record("stdout", text)

    assert bounded.text.startswith("START")
    assert bounded.text.endswith("END")
    assert bounded.truncated


def test_spilled_output_is_readable_back_through_the_tools(
    tmp_path: Path,
) -> None:
    """The pointer is only useful if read_file can actually follow it."""
    session = WorkspaceSession(tmp_path)
    provider = WorkspaceToolProvider(session)
    recorder = OutputRecorder(session.root, preview_chars=100)
    text = f"START{'x' * 5000}END"

    pointer = recorder.record("stdout", text).pointer
    assert pointer is not None

    payload = _content(
        asyncio.run(
            provider.execute_tool_call(
                _call(READ_FILE, json.dumps({"path": pointer.path}))
            )
        )
    )
    assert payload["content"] == text


def test_spilled_output_is_redacted_before_it_is_written(
    tmp_path: Path,
) -> None:
    """Redacting before persisting: the spill file is a persistence."""
    recorder = OutputRecorder(
        tmp_path, _registry(API_KEY=_SECRET), preview_chars=100
    )

    pointer = recorder.record("stdout", f"{_SECRET}{'x' * 5000}").pointer

    assert pointer is not None
    assert _SECRET not in (tmp_path / pointer.path).read_text()


def test_a_failed_spill_costs_the_middle_not_the_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A full disk must not turn a finished command into an error."""

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "mkdir", _explode)
    recorder = OutputRecorder(tmp_path, preview_chars=100)

    bounded = recorder.record("stdout", "x" * 5000)

    assert bounded.pointer is None
    assert bounded.truncated
    assert bounded.text


# --- the metadata directory ----------------------------------------------


def test_the_spill_directory_is_protected_from_confined_commands() -> None:
    """A later command must not be able to edit an earlier one's record."""
    root = SPILL_DIRECTORY.split("/")[0]
    assert root in PROTECTED_METADATA_NAMES


def test_listing_files_omits_harness_metadata(tmp_path: Path) -> None:
    """Its own transcript is not one of the workspace's inputs."""
    session = WorkspaceSession(tmp_path)
    (tmp_path / "analysis.py").write_text("pass")
    OutputRecorder(session.root, preview_chars=50).record("stdout", "y" * 500)

    payload = _content(
        asyncio.run(
            WorkspaceToolProvider(session).execute_tool_call(_call(LIST_FILES))
        )
    )
    assert payload["files"] == ["analysis.py"]


def test_a_symlinked_metadata_directory_does_not_redirect_the_spill(
    tmp_path: Path,
) -> None:
    """The escape a fresh Linux workspace allowed until sessions made it.

    bwrap's --ro-bind-try skips a path that does not exist, so on a fresh
    workspace .cosci was ordinary writable space and the first confined
    command could replace it with a symlink. The spill then ran in *this*
    process, outside the sandbox, and wrote command-influenced bytes into
    a command-chosen directory. macOS never showed it: seatbelt's deny
    rule matches the path whether or not it exists.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / SPILL_DIRECTORY.split("/")[0]).symlink_to(outside)

    bounded = OutputRecorder(root, preview_chars=50).record(
        "stdout", "x" * 5000
    )

    assert bounded.pointer is None
    # Not even a directory: creating one and then declining to write
    # still lets a command make the host mkdir wherever it likes.
    assert list(outside.rglob("*")) == []


def test_a_session_creates_the_metadata_directory_up_front(
    tmp_path: Path,
) -> None:
    """What makes the read-only bind bind at all, from command one."""
    session = WorkspaceSession(tmp_path)
    assert (session.root / SPILL_DIRECTORY).is_dir()


def test_a_truncated_read_hands_back_a_way_to_the_rest(
    tmp_path: Path,
) -> None:
    """Otherwise the preview's own advice is a dead end.

    "Read the full output with read_file" is what the preview says, and
    re-reading the same path returns the same preview forever.
    """
    session = WorkspaceSession(tmp_path)
    (tmp_path / "big.txt").write_text("y" * 40_000)

    payload = _content(
        asyncio.run(
            WorkspaceToolProvider(session).execute_tool_call(
                _call(READ_FILE, json.dumps({"path": "big.txt"}))
            )
        )
    )

    assert payload["truncated"] is True
    assert payload["full_output"].startswith(SPILL_DIRECTORY)
