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

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from co_scientist.patch import PatchError
from co_scientist.sandbox import SandboxKind, SandboxPolicy, sandbox_backend
from co_scientist.tool_effects import declare_local_tool
from co_scientist.tools.messages import tool_error_message, tool_result_message
from co_scientist.workspace.checks import check_paths
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
    LIST_FILES,
    READ_FILE,
    RUN_COMMAND,
    apply_patch_schema,
    list_files_schema,
    read_file_schema,
    run_command_schema,
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
declare_local_tool(LIST_FILES, WorkspaceSession.READ_FILE_EFFECTS)

# Policies whose confinement is somebody else's job: EXTERNAL means the
# caller placed the boundary outside this process, DANGER_FULL_ACCESS
# means it was explicitly declined. Both are legitimate reasons to have
# no local backend, and neither should hide the tool.
_BACKEND_EXEMPT_KINDS = (SandboxKind.EXTERNAL, SandboxKind.DANGER_FULL_ACCESS)


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
        apply_patch_schema(),
        read_file_schema(),
        list_files_schema(),
    ]
    if can_run_commands(policy):
        schemas.insert(0, run_command_schema())
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


def _resolve_timeout(args: dict[str, Any]) -> float:
    """Clamps a requested command timeout to the session's ceiling."""
    requested = args.get("timeout_seconds")
    if not isinstance(requested, int | float) or requested <= 0:
        return DEFAULT_COMMAND_TIMEOUT_SECONDS
    return min(float(requested), DEFAULT_COMMAND_TIMEOUT_SECONDS)


def _full_output_paths(
    streams: dict[str, BoundedOutput],
) -> dict[str, str]:
    """Maps each spilled stream to the path holding its full text."""
    return {
        name: bounded.pointer.path
        for name, bounded in streams.items()
        if bounded.pointer is not None
    }


async def _handle_run_command(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Runs a confined command and reports its outcome to the model."""
    outcome = await context.session.run_command(
        _require_argv(args), timeout_seconds=_resolve_timeout(args)
    )
    result = outcome.result
    streams = {
        "stdout": context.recorder.record("stdout", result.stdout),
        "stderr": context.recorder.record("stderr", result.stderr),
    }
    payload: dict[str, Any] = {
        "exit_code": result.exit_code,
        "stdout": streams["stdout"].text,
        "stderr": streams["stderr"].text,
        "timed_out": result.timed_out,
        "truncated": {
            name: bounded.truncated for name, bounded in streams.items()
        },
        "required_approval": outcome.required_approval,
    }
    spilled = _full_output_paths(streams)
    if spilled:
        payload["full_output"] = spilled
    return payload


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


async def _handle_list_files(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Lists the workspace's files."""
    del args
    files = await asyncio.to_thread(context.session.list_files)
    return {"files": list(files)}


_HANDLERS = {
    RUN_COMMAND: _handle_run_command,
    APPLY_PATCH: _handle_apply_patch,
    READ_FILE: _handle_read_file,
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
