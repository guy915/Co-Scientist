"""The workspace, exposed as tools a model can call.

Everything under `sandbox/`, `patch/` and `session.py` is a library until
something registers it. This module is that registration, and it is the
first tool on this host that is not an MCP call.

Three decisions are load-bearing.

**Local, not MCP.** The alternative was a local MCP server, which keeps
one registration path at the cost of an HTTP hop and the 300 s
`COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS` ceiling -- a ceiling that bounds
the tool call and the command with one number, so a long analysis and a
hung provider become the same event. Effects are declared here at import
time instead, and `tool_effects` consults local declarations before the
MCP registry.

**Exposure is gated, not just execution.** When no sandbox backend
exists and the policy does not name an outside boundary, `run_command`
is not offered at all. Offering it and failing at call time would spend
a loop iteration per attempt on an error the model cannot act on, and
production is exactly that case today: the api image carries no
bubblewrap, so `sandbox_backend()` is None there.

**`argv`, never a command string.** The model passes
`["bash", "-lc", "a | b"]` when it wants a shell, which is visible in the
argv the classifier reads. Accepting a string and splitting it here
would put an implicit shell behind every call and make
`command_safety`'s composite parsing a description of something that no
longer happens.
"""

import json
import logging
from typing import Any

from co_scientist.patch import PatchError
from co_scientist.sandbox import (
    SandboxKind,
    SandboxPolicy,
    is_known_safe,
    sandbox_backend,
)
from co_scientist.tool_effects import declare_local_tool
from co_scientist.tools.messages import tool_error_message, tool_result_message
from co_scientist.workspace.command_session import CommandSession, SessionRead
from co_scientist.workspace.file_tools import (
    WorkspaceToolInputError as WorkspaceToolInputError,
)
from co_scientist.workspace.file_tools import (
    _handle_apply_patch,
    _handle_list_files,
    _handle_read_file,
    _handle_write_file,
)
from co_scientist.workspace.file_tools import (
    _ToolContext as _ToolContext,
)
from co_scientist.workspace.output import (
    BoundedOutput,
    OutputRecorder,
    SecretRegistry,
)
from co_scientist.workspace.session import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    WorkspaceSession,
)
from co_scientist.workspace.tool_schemas import (
    APPLY_PATCH,
    DEFAULT_YIELD_SECONDS,
    LIST_FILES,
    POLL_COMMAND,
    READ_FILE,
    RUN_COMMAND,
    WRITE_FILE,
    apply_patch_schema,
    list_files_schema,
    poll_command_schema,
    read_file_schema,
    run_command_schema,
    write_file_schema,
)

logger = logging.getLogger(__name__)

# Declared at import so the batching rule sees them however the tools are
# later exposed. run_command and apply_patch are barriers and run alone;
# read_file and list_files batch with sibling reads, which is the only
# case where consulting this table changes behaviour at all -- a barrier
# is what an unknown tool defaults to anyway.
declare_local_tool(RUN_COMMAND, WorkspaceSession.RUN_COMMAND_EFFECTS)
declare_local_tool(APPLY_PATCH, WorkspaceSession.APPLY_PATCH_EFFECTS)
declare_local_tool(READ_FILE, WorkspaceSession.READ_FILE_EFFECTS)
declare_local_tool(WRITE_FILE, WorkspaceSession.WRITE_FILE_EFFECTS)
declare_local_tool(LIST_FILES, WorkspaceSession.READ_FILE_EFFECTS)
# Polling touches a live process -- it can write to its stdin and end
# it -- so it is a barrier for the same reason starting one is.
declare_local_tool(POLL_COMMAND, WorkspaceSession.RUN_COMMAND_EFFECTS)

# Policies whose confinement is somebody else's job: EXTERNAL means the
# caller placed the boundary outside this process, DANGER_FULL_ACCESS
# means it was explicitly declined. Both are legitimate reasons to have
# no local backend, and neither should hide the tool.
_BACKEND_EXEMPT_KINDS = (SandboxKind.EXTERNAL, SandboxKind.DANGER_FULL_ACCESS)


def can_run_commands(policy: SandboxPolicy) -> bool:
    """Reports whether commands can be confined under this policy here.

    Args:
        policy: The confinement the session would apply.

    Returns:
        True when a backend exists, or when the policy places the
        boundary outside this process.
    """
    if policy.kind in _BACKEND_EXEMPT_KINDS:
        return True
    return sandbox_backend() is not None


def workspace_tool_schemas(policy: SandboxPolicy) -> list[dict[str, Any]]:
    """Builds the tool schemas offerable under a policy.

    Args:
        policy: The confinement the session applies. Governs whether the
            command tool is offered at all.

    Returns:
        OpenAI-format tool definitions. The file tools are always
        present; ``run_command`` only when it could actually be confined.
    """
    schemas = [
        write_file_schema(),
        apply_patch_schema(),
        read_file_schema(),
        list_files_schema(),
    ]
    if can_run_commands(policy):
        schemas.insert(0, run_command_schema())
        schemas.insert(1, poll_command_schema())
    else:
        logger.warning(
            "no sandbox backend on this platform; withholding %r from the "
            "model rather than offering a tool every call would refuse",
            RUN_COMMAND,
        )
    return schemas


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
    session = await context.session.sessions.start(
        argv, policy=context.session.policy, cwd=context.session.root
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


_HANDLERS = {
    RUN_COMMAND: _handle_run_command,
    POLL_COMMAND: _handle_poll_command,
    APPLY_PATCH: _handle_apply_patch,
    READ_FILE: _handle_read_file,
    WRITE_FILE: _handle_write_file,
    LIST_FILES: _handle_list_files,
}


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Parses a tool call's JSON arguments into a dict."""
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise WorkspaceToolInputError(
            f"arguments were not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise WorkspaceToolInputError("arguments must be a JSON object")
    return parsed


class WorkspaceToolProvider:
    """Serves the workspace tools, delegating anything else onward.

    Attributes:
        session: The workspace every call acts on.
    """

    def __init__(
        self,
        session: WorkspaceSession,
        delegate: Any | None = None,
        secrets: SecretRegistry | None = None,
    ) -> None:
        """Binds a provider to one run's workspace.

        Args:
            session: The workspace to act on.
            delegate: Optional provider handling every other tool name --
                in practice the ``MCPToolProvider`` for this run, so the
                model sees one tool surface. A local name always wins,
                loudly: shadowing an MCP tool is a configuration mistake
                worth a log line rather than a silent reordering.
            secrets: Values to mask in anything returned to the model.
                Defaults to the host environment's credential-shaped
                variables -- the default has to be the protective one,
                since a caller who forgets this argument is exactly the
                caller who most needs it.
        """
        self.session = session
        self._delegate = delegate
        if secrets is None:
            secrets = SecretRegistry()
            secrets.register_environment()
        self._context = _ToolContext(
            session=session,
            recorder=OutputRecorder(session.root, secrets),
        )
        self._names = {
            schema["function"]["name"]
            for schema in workspace_tool_schemas(session.policy)
        }

    def get_tools(self) -> tuple[set[str], list[dict[str, Any]]]:
        """Returns the local tool names and their OpenAI schemas."""
        return set(self._names), workspace_tool_schemas(self.session.policy)

    def merge_tools(
        self, mcp_tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Combines MCP schemas with the workspace's, local names winning.

        Args:
            mcp_tools: The MCP tool schemas for this run.

        Returns:
            One schema list with no duplicate names.
        """
        kept = []
        for schema in mcp_tools:
            name = schema.get("function", {}).get("name")
            if name in self._names:
                logger.warning(
                    "MCP tool %r is shadowed by the workspace tool of the "
                    "same name and will not be offered",
                    name,
                )
                continue
            kept.append(schema)
        return [*workspace_tool_schemas(self.session.policy), *kept]

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Executes one tool call against the workspace, or delegates it.

        Every failure becomes a tool-role error message: a raise here
        would leave the assistant turn's tool call unanswered, which the
        provider rejects on the next iteration -- so one bad argument
        would end the conversation rather than the call.

        Args:
            tool_call: The model's call, with ``.id`` and ``.function``.

        Returns:
            A tool-role message answering the call.
        """
        name = tool_call.function.name
        handler = _HANDLERS.get(name) if name in self._names else None
        if handler is None:
            return await self._delegate_call(tool_call, name)

        try:
            payload = await handler(
                self._context, _parse_arguments(tool_call.function.arguments)
            )
        except (WorkspaceToolInputError, PatchError) as exc:
            # Expected and actionable: the model can fix its own call.
            logger.info("workspace tool %s rejected a call: %s", name, exc)
            return tool_error_message(name, tool_call.id, str(exc))
        except Exception as exc:
            logger.exception("workspace tool %s failed", name)
            return tool_error_message(
                name, tool_call.id, f"tool execution failed: {exc}"
            )
        return tool_result_message(name, tool_call.id, payload)

    async def _delegate_call(self, tool_call: Any, name: str) -> dict[str, Any]:
        """Passes a non-workspace tool call to the delegate provider."""
        if self._delegate is None:
            return tool_error_message(
                name, tool_call.id, f"unknown tool: {name}"
            )
        result: dict[str, Any] = await self._delegate.execute_tool_call(
            tool_call
        )
        return result
