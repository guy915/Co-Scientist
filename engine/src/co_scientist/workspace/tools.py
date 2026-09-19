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
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.llm_free_policy import campaign_free_mode
from co_scientist.patch import PatchError
from co_scientist.sandbox import (
    SandboxKind,
    SandboxPolicy,
    sandbox_backend,
)
from co_scientist.sandbox.policy import campaign_workspace_policy
from co_scientist.skills import (
    available_skills,
    read_skill_document,
)
from co_scientist.tool_effects import declare_local_tool
from co_scientist.tools.messages import tool_error_message, tool_result_message
from co_scientist.tools.tracking import tracked_executor as track_calls
from co_scientist.workspace.command_tools import (
    _handle_poll_command as _handle_poll_command,
)
from co_scientist.workspace.command_tools import (
    _handle_run_command as _handle_run_command,
)
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
    OutputRecorder,
    SecretRegistry,
)
from co_scientist.workspace.session import (
    WorkspaceSession,
)
from co_scientist.workspace.tool_schemas import (
    APPLY_PATCH,
    LIST_FILES,
    POLL_COMMAND,
    READ_FILE,
    READ_SKILL,
    RUN_COMMAND,
    WRITE_FILE,
    apply_patch_schema,
    list_files_schema,
    poll_command_schema,
    read_file_schema,
    read_skill_schema,
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
# Reading a skill's instructions is reading a file off the image: no
# barrier, so it batches concurrently with the other reads in a turn.
declare_local_tool(READ_SKILL, WorkspaceSession.READ_FILE_EFFECTS)

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


def workspace_tool_schemas(
    policy: SandboxPolicy, *, skills_enabled: bool = False
) -> list[dict[str, Any]]:
    """Builds the tool schemas offerable under a policy.

    Args:
        policy: The confinement the session applies. Governs whether the
            command tool is offered at all.
        skills_enabled: Whether this consumer asked for the vendored
            science skills. Defaults off, which is what keeps installing
            the bundle from silently re-arming a consumer measured to be
            worse with it.

    Returns:
        OpenAI-format tool definitions. The file tools are always
        present; ``run_command`` only when it could actually be confined.
    """
    policy = campaign_workspace_policy(policy)
    schemas = [
        write_file_schema(),
        apply_patch_schema(),
        read_file_schema(),
        list_files_schema(),
    ]
    # Offered only where a skill could actually be used: the consumer
    # has to ask, the bundle has to be installed (the catalogue is empty
    # unless COSCIENTIST_SKILLS_DIR is set, which a checkout, a test and
    # a CI job do not set), and commands have to be runnable -- because
    # instructions whose every step is a command are worse than useless
    # to a model that cannot run one.
    skills = (
        available_skills()
        if skills_enabled
        and not campaign_free_mode()
        and can_run_commands(policy)
        else ()
    )
    if skills:
        schemas.append(read_skill_schema(tuple(s.name for s in skills)))
    if can_run_commands(policy):
        schemas.insert(
            0, run_command_schema(network_allowed=policy.allows_network)
        )
        schemas.insert(1, poll_command_schema())
    else:
        logger.warning(
            "no sandbox backend on this platform; withholding %r from the "
            "model rather than offering a tool every call would refuse",
            RUN_COMMAND,
        )
    return schemas


async def _handle_read_skill(
    context: "_ToolContext", args: dict[str, Any]
) -> dict[str, Any]:
    """Returns one skill's instructions.

    Not passed through the output recorder: this is a file baked into the
    image, not something a command produced, so there is no secret of
    ours in it to redact and no budget of the model's to spend
    truncating it.
    """
    del context
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceToolInputError("name must be a non-empty string")
    path = args.get("path")
    if path is not None and not isinstance(path, str):
        raise WorkspaceToolInputError("path must be a string")
    document = await asyncio.to_thread(read_skill_document, name, path)
    if document is None:
        if path:
            raise WorkspaceToolInputError(
                f"skill {name!r} has no file {path!r}; the path is relative "
                "to the skill directory, as its own document writes it"
            )
        available = ", ".join(skill.name for skill in available_skills())
        raise WorkspaceToolInputError(
            f"no skill named {name!r}; available skills: {available}"
        )
    return {"name": name, "path": path or "SKILL.md", "instructions": document}


_HANDLERS = {
    RUN_COMMAND: _handle_run_command,
    POLL_COMMAND: _handle_poll_command,
    APPLY_PATCH: _handle_apply_patch,
    READ_FILE: _handle_read_file,
    WRITE_FILE: _handle_write_file,
    LIST_FILES: _handle_list_files,
    READ_SKILL: _handle_read_skill,
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
            for schema in workspace_tool_schemas(
                session.policy, skills_enabled=session.skills_enabled
            )
        }

    def _schemas(self) -> list[dict[str, Any]]:
        """Returns this session's tool schemas under its own gating."""
        return workspace_tool_schemas(
            self.session.policy, skills_enabled=self.session.skills_enabled
        )

    def tracked_executor(
        self, label: str
    ) -> tuple[Callable[[Any], Awaitable[dict[str, Any]]], dict[str, int]]:
        """Wraps this provider's executor with per-tool-name counting.

        Args:
            label: Log prefix identifying the calling phase.

        Returns:
            An (executor, counts) pair; see ``tools.tracking``.
        """
        return track_calls(self, label)

    def get_tools(self) -> tuple[set[str], list[dict[str, Any]]]:
        """Returns the local tool names and their OpenAI schemas."""
        return set(self._names), self._schemas()

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
        return [*self._schemas(), *kept]

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
        if name == READ_SKILL and campaign_free_mode():
            return tool_error_message(
                name, tool_call.id, "skills are unavailable in campaign mode"
            )
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
