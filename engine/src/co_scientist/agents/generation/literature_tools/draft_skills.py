"""Resolve drafting tool providers and offer the science-skills workspace."""

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from co_scientist.llm import DEFAULT_TOOL_LOOP_TOKEN_BUDGET, campaign_free_mode
from co_scientist.skills import (
    catalogue_section,
    seed_licence_notices,
)
from co_scientist.state import WorkflowState
from co_scientist.tools.provider import MCPToolProvider
from co_scientist.workspace import (
    WorkspaceToolProvider,
    open_draft_workspace,
)
from co_scientist.workspace.tool_schemas import READ_SKILL

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


def _resolve_tool_registry_fallback(
    tool_registry: Optional["ToolRegistry"], label: str, log: logging.Logger
) -> Optional["ToolRegistry"]:
    """Fall back to the process-global tool registry when none was passed.

    Args:
        tool_registry: optional ToolRegistry threaded from WorkflowState.
        label: short phase label used in log messages.
        log: the calling module's logger.

    Returns:
        The resolved ToolRegistry, or None if none is available.
    """
    if tool_registry is not None:
        return tool_registry
    try:
        # Imported at call time so tests can monkeypatch
        # config.get_tool_registry on the config module namespace.
        from co_scientist.config import get_tool_registry

        tool_registry = get_tool_registry()
        log.info("Using global tool registry for %s", label)
    except Exception as e:
        log.warning("Failed to get tool registry: %s", e)
    return tool_registry


def _resolve_mcp_whitelist(
    tool_registry: Optional["ToolRegistry"],
    workflow_name: str,
    label: str,
    log: logging.Logger,
) -> list[str] | None:
    """Resolve the MCP tool-name whitelist for a workflow from its registry.

    Args:
        tool_registry: resolved ToolRegistry, or None.
        workflow_name: registry workflow key selecting the tool whitelist.
        label: short phase label used in log messages.
        log: the calling module's logger.

    Returns:
        The MCP tool-name whitelist, or None to allow every available tool.
    """
    if not tool_registry:
        # No registry available - let provider use all available tools
        log.warning("No tool registry - using all available MCP tools")
        return None

    tool_ids = tool_registry.get_tools_for_workflow(workflow_name)
    mcp_whitelist = tool_registry.get_mcp_tool_names(tool_ids)
    log.info("Tool whitelist for %s: %s", label, mcp_whitelist)
    return mcp_whitelist


def _setup_tool_provider(
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    workflow_name: str,
    label: str,
    log: logging.Logger,
) -> tuple[MCPToolProvider, list[Any], Optional["ToolRegistry"]]:
    """Resolve the tool registry/whitelist and init an MCP tool provider.

    Shared by the draft phase here and the validation synthesis stage
    (validate_synthesis.py). Fallback chain: passed-in registry (threaded
    from WorkflowState) -> process-global registry (covers standalone/dev
    scripts that never thread one through state) -> no whitelist at all
    (provider uses every available tool).

    Args:
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection; resolved from the global registry when None.
        workflow_name: registry workflow key selecting the tool whitelist.
        label: short phase label used in log messages.
        log: the calling module's logger, so log records keep their
            per-phase attribution.

    Returns:
        Tuple of (provider, openai_tools, resolved tool_registry).
    """
    tool_registry = _resolve_tool_registry_fallback(tool_registry, label, log)

    provider = MCPToolProvider(mcp_client=mcp_client)

    mcp_whitelist = _resolve_mcp_whitelist(
        tool_registry, workflow_name, label, log
    )

    tools_dict, openai_tools = provider.get_tools(mcp_whitelist=mcp_whitelist)
    log.info("Initialized %s provider with %s tools", label, len(tools_dict))

    return provider, openai_tools, tool_registry


# What a drafting pass may re-send once skills are in the transcript.
#
# Turns are not what binds this loop, and funding the skills with extra
# turns -- the obvious move -- buys nothing: for four hypotheses the
# iteration budget is 13 (`get_draft_max_iterations`), and before
# transcript ageing existed a live pass never reached it, stopping on
# the token backstop at seven to eleven turns.
#
# What skills actually cost is transcript. The catalogue is ~1.6k tokens
# on every turn, and a skill document another ~3k on every turn after it
# is read -- a quarter of a finished pass's last transcript, measured.
# Two documents plus the catalogue over a full pass is roughly the 60k
# added here, which keeps the pass the same number of *working* turns it
# had before rather than trading drafting for lookups.
#
# Since `llm.tools.transcript.elide_aged_evidence` this ceiling is a
# backstop rather than the thing that ends the pass: spend per turn no
# longer grows with the searches run, so thirteen turns cost ~300k and
# healthy passes finish inside it.
DRAFT_SKILLS_TOKEN_BUDGET = 360_000


_SECTION = """

### Science skills (database access)

Also installed here are scripts that query scientific databases \
directly -- sequences and structures, genomics and regulation, \
pathways, chemistry, clinical trials. They complement the search tools \
above rather than replacing them: those return papers, these return \
records.

{catalogue}

To use one, call `read_skill` with its name for its full instructions \
and the exact command, then run that command with `run_command` in your \
working directory. The one-line summaries above are not enough to use a \
skill correctly. Have each script write to a file and read back the \
fields you need instead of printing everything; the licence notices \
they ask for are already written in `.licenses/`, so skip that step \
entirely.

**Check one entity against a database before you finalise.** Take the \
gene, protein, drug, variant or pathway your drafts lean on hardest and \
look up what is actually recorded about it -- whether the target is \
already drugged, which variants are known, what the pathway contains, \
whether a trial has run. A gap argued from papers alone is a gap in \
what someone wrote up; a record tells you what is known. Say in \
`gap_reasoning` what the lookup showed, including when it closed a gap \
you were about to draft.

Read **at most two** skills: each document is hundreds of lines that \
every later turn re-sends, and what you are judged on is the drafts, \
not the survey."""


def skills_section() -> str:
    """Returns the prompt section describing the skills, or ``""``."""
    catalogue = catalogue_section()
    if not catalogue:
        return ""
    return _SECTION.format(catalogue=catalogue)


@dataclass(frozen=True)
class DraftSkills:
    """The tool surface and prompt text one drafting pass was given.

    Attributes:
        provider: The provider to execute tool calls against -- the
            workspace one when skills attached, otherwise the MCP
            provider unchanged.
        tools: The schemas to offer, merged.
        section: Prompt text describing the skills, empty when none
            were attached.
        max_prompt_tokens: What the loop may re-send in total. Left on
            the default backstop for a pass without skills, which is
            what it has always had.
    """

    provider: Any
    tools: list[Any] = field(default_factory=list)
    section: str = ""
    max_prompt_tokens: int = DEFAULT_TOOL_LOOP_TOKEN_BUDGET


def attach_skills(
    state: WorkflowState, provider: Any, tools: list[Any]
) -> DraftSkills:
    """Gives one drafting pass a workspace and the skills, if there are any.

    Every failure degrades to the surface the phase already had. A
    drafting pass that cannot open a workspace still has the MCP search
    tools, which is the whole job minus one instrument; raising here
    would cost the run its hypotheses for that cycle.

    Args:
        state: The run's state, for the run id the workspace is under.
        provider: The MCP tool provider this phase resolved.
        tools: Its OpenAI-format schemas.

    Returns:
        What to run the loop with -- the arguments unchanged when no
        skills are installed or none could be offered.
    """
    if campaign_free_mode() or not skills_section():
        return DraftSkills(provider, tools)
    run_id = state.get("run_id")
    if not run_id:
        logger.warning("no run id in state; drafting without science skills")
        return DraftSkills(provider, tools)
    try:
        # Per pass, not per run: a cycle that reopened the previous
        # cycle's directory would find its result files and could read
        # a stale one back as its own.
        session = open_draft_workspace(run_id, uuid.uuid4().hex)
        # 35 of the 38 skills refuse to work until their licence notice
        # exists in the workspace. Measured at four turns of fourteen
        # when the model was left to write them itself.
        seed_licence_notices(session.root)
        workspace = WorkspaceToolProvider(session, delegate=provider)
        names, _ = workspace.get_tools()
    except OSError as exc:
        logger.warning("could not open a draft workspace: %s", exc)
        return DraftSkills(provider, tools)
    if READ_SKILL not in names:
        # No sandbox backend on this host, so run_command is withheld
        # and a skill is a document about a command nobody can run.
        logger.info("commands cannot be confined here; drafting without them")
        return DraftSkills(provider, tools)
    logger.info("Draft phase: science skills offered from %s", session.root)
    return DraftSkills(
        workspace,
        workspace.merge_tools(tools),
        skills_section(),
        DRAFT_SKILLS_TOKEN_BUDGET,
    )
