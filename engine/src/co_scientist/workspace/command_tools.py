"""Starting and polling confined commands, as two tool handlers.

Split out of ``tools.py`` for size; the shape of the pair is the point.
``run_command`` starts a session and yields rather than waiting for the
process to end, because the interesting commands here -- a build, a
test suite, a database query behind a rate limiter -- routinely outlast
any deadline short enough to be worth blocking on, and killing one at
that deadline discards both the work and the output it had already
produced. ``poll_command`` is how the model comes back to it.

Both handlers are imported into ``tools.py``'s namespace, which is where
tests patch them.
"""

import logging
from typing import Any

from co_scientist.llm import campaign_free_mode
from co_scientist.sandbox import is_known_safe
from co_scientist.skills import (
    invoked_skill,
    record_skill_use,
    skill_environment,
)
from co_scientist.workspace.command_session import CommandSession, SessionRead
from co_scientist.workspace.file_tools import (
    WorkspaceToolInputError,
    _ToolContext,
)
from co_scientist.workspace.output import BoundedOutput
from co_scientist.workspace.session import DEFAULT_COMMAND_TIMEOUT_SECONDS
from co_scientist.workspace.tool_schemas import DEFAULT_YIELD_SECONDS

logger = logging.getLogger(__name__)


def _require_argv(args: dict[str, Any]) -> list[str]:
    """Validates the argv argument of a run_command call."""
    argv = args.get("argv")
    if isinstance(argv, str):
        raise WorkspaceToolInputError(
            "argv must be an array of strings, not a single string; pass "
            '["bash", "-lc", "<command>"] to run something through a shell'
        )
    if not isinstance(argv, list) or not argv:
        raise WorkspaceToolInputError("argv must be a non-empty array")
    if not all(isinstance(item, str) for item in argv):
        raise WorkspaceToolInputError("every argv entry must be a string")
    return argv


def _resolve_seconds(raw: Any, default: float, floor: float = 0.0) -> float:
    """Clamps a requested wait to the ceiling one command may hold."""
    if not isinstance(raw, int | float) or raw < floor:
        return default
    return min(float(raw), DEFAULT_COMMAND_TIMEOUT_SECONDS)


def _resolve_yield(args: dict[str, Any]) -> float:
    """How long to wait before handing back a session id instead."""
    return _resolve_seconds(
        args.get("yield_seconds"), DEFAULT_YIELD_SECONDS, floor=0.001
    )


def _resolve_wait(args: dict[str, Any]) -> float:
    """How long a poll waits for the command to finish. Zero is valid."""
    return _resolve_seconds(args.get("wait_seconds"), DEFAULT_YIELD_SECONDS)


def _full_output_paths(
    streams: dict[str, BoundedOutput],
) -> dict[str, str]:
    """Maps each spilled stream to the path holding its full text."""
    return {
        name: bounded.pointer.path
        for name, bounded in streams.items()
        if bounded.pointer is not None
    }


def _session_payload(
    context: "_ToolContext", read: SessionRead
) -> dict[str, Any]:
    """Renders one look at a session for the model.

    ``running`` is the field that matters: a command still going is a
    successful answer carrying a session id, not a timeout and not an
    error. The caller's next move is to poll it, not to start over.
    """
    streams = {
        "stdout": context.recorder.record("stdout", read.stdout),
        "stderr": context.recorder.record("stderr", read.stderr),
    }
    payload: dict[str, Any] = {
        "session_id": read.session_id,
        "running": read.running,
        "exit_code": read.exit_code,
        "stdout": streams["stdout"].text,
        "stderr": streams["stderr"].text,
        "cursor": read.cursor,
        "truncated": {
            name: bounded.truncated or read.truncated[name]
            for name, bounded in streams.items()
        },
    }
    spilled = _full_output_paths(streams)
    if spilled:
        payload["full_output"] = spilled
    return payload


async def _handle_run_command(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Starts a confined command and reports how far it got.

    It is started as a session rather than awaited to completion,
    because the interesting commands here -- a build, a test suite, a
    training run -- routinely outlast any deadline short enough to be
    worth waiting on, and killing one at that deadline discards both the
    work and the output it had already produced.
    """
    argv = _require_argv(args)
    # Credentials reach a vendored skill script and nothing else. The
    # same workspace runs model-written programs against a network that
    # is open precisely so skills can use it, so a key in the shared
    # environment is a key any generated program could read and send on.
    skill = (
        invoked_skill(argv)
        if context.session.skills_enabled and not campaign_free_mode()
        else None
    )
    if skill is not None:
        # Recorded by name rather than counted from the tool name: the
        # notice a run owes is per data source and run_command is one
        # name over all of them. See skills/usage.py.
        record_skill_use(skill)
    env_extra = skill_environment() if skill is not None else None
    session = await context.session.sessions.start(
        argv,
        policy=context.session.policy,
        cwd=context.session.root,
        env_extra=env_extra,
    )
    await session.wait_for(_resolve_yield(args))
    payload = _session_payload(context, session.read())
    payload["required_approval"] = not is_known_safe(argv)
    return payload


def _named_session(
    context: "_ToolContext", args: dict[str, Any]
) -> CommandSession:
    """Resolves the session a poll names, or says why it cannot."""
    session_id = args.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise WorkspaceToolInputError("session_id must be a string")
    try:
        return context.session.sessions.get(session_id)
    except KeyError:
        raise WorkspaceToolInputError(
            f"no command session {session_id!r} is open here. A worker "
            f"restart ends every session it was running."
        ) from None


async def _send_input(session: CommandSession, args: dict[str, Any]) -> None:
    """Passes a poll's `input` to the command, if it asked for one."""
    if not isinstance(args.get("input"), str):
        return
    try:
        await session.write(str(args["input"]))
    except ValueError as exc:
        # Actionable, not a harness fault: the command answered or
        # exited before the input arrived, and polling without it still
        # returns what it printed.
        raise WorkspaceToolInputError(str(exc)) from None


async def _handle_poll_command(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Continues a command a previous call left running."""
    session = _named_session(context, args)
    await _send_input(session, args)
    if args.get("kill"):
        await session.close()
    else:
        await session.wait_for(_resolve_wait(args))
    cursor = args.get("cursor") if isinstance(args.get("cursor"), dict) else {}
    return _session_payload(context, session.read(cursor))
