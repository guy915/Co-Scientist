"""The workspace tools that act on files, and the context they share.

Split out of ``tools.py`` for length; every name is re-exported there, so
the module namespace tests and callers use is unchanged.

These four are the file surface the model actually reaches for. Their
ordering matters more than it looks: ``write_file`` exists because
expressing "here is the program I want to run" as a context-anchored
patch is the wrong shape -- a new file has no context to anchor to, so
the envelope is all ceremony and each near-miss costs a turn. Traced
against the real model, one simulation loop spent 33 of its tool results
on ``apply_patch`` rejections and never ran a program.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from co_scientist.workspace.checks import check_paths
from co_scientist.workspace.output import OutputRecorder
from co_scientist.workspace.session import WorkspaceSession


class WorkspaceToolInputError(ValueError):
    """Arguments the model sent that this module will not act on."""


@dataclass(frozen=True)
class _ToolContext:
    """What every handler acts on: one workspace and its output policy.

    Attributes:
        session: The workspace the call operates in.
        recorder: Redacts and bounds anything on its way to the model.
    """

    session: WorkspaceSession
    recorder: OutputRecorder


async def _handle_apply_patch(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Applies a patch envelope and reports what changed."""
    session = context.session
    patch_text = args.get("patch")
    if not isinstance(patch_text, str) or not patch_text.strip():
        raise WorkspaceToolInputError("patch must be a non-empty string")
    # Parsing and writing are synchronous and can touch many files; a
    # cohort's event loop runs several tasks, so this does not hold it.
    outcome = await asyncio.to_thread(session.apply_patch_text, patch_text)
    payload: dict[str, Any] = {
        "changed": list(outcome.changed),
        "match_rungs": {
            path: list(rungs) for path, rungs in outcome.rungs.items()
        },
    }
    findings = await asyncio.to_thread(
        check_paths, session.root, outcome.changed
    )
    if findings:
        payload["problems"] = [finding.as_dict() for finding in findings]
    return payload


async def _handle_read_file(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Reads one workspace file.

    Redacted like command output: a file the model just wrote may hold
    whatever a command printed into it, and this path would otherwise be
    the way around the redaction on the other.
    """
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise WorkspaceToolInputError("path must be a non-empty string")
    content = await asyncio.to_thread(context.session.read_file, path)
    bounded = context.recorder.record("read_file", content)
    payload: dict[str, Any] = {
        "path": path,
        "content": bounded.text,
        "truncated": bounded.truncated,
    }
    if bounded.pointer is not None:
        # Without this the preview's own "read the full output with
        # read_file" is a dead end: re-reading the same path returns the
        # same preview forever, and the model has no other handle. With
        # it, the remaining text is reachable -- through this path, or by
        # slicing the spill file with run_command.
        payload["full_output"] = bounded.pointer.path
    return payload


async def _handle_write_file(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Writes one whole file, then runs the same checks a patch does.

    The safety scan is not optional here: without it this tool would be
    the way around the one ``apply_patch`` runs on everything it writes.
    """
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise WorkspaceToolInputError("path must be a non-empty string")
    content = args.get("content")
    if not isinstance(content, str):
        raise WorkspaceToolInputError("content must be a string")
    await asyncio.to_thread(context.session.write_file, path, content)
    payload: dict[str, Any] = {"path": path, "bytes": len(content.encode())}
    findings = await asyncio.to_thread(
        check_paths, context.session.root, [path]
    )
    if findings:
        payload["problems"] = [finding.as_dict() for finding in findings]
    return payload


async def _handle_list_files(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Lists the workspace's files."""
    del args
    files = await asyncio.to_thread(context.session.list_files)
    return {"files": list(files)}
