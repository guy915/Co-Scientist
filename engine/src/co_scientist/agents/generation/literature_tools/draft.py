"""Tool-assisted drafting with scientific skill and literature context."""

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from co_scientist.agents.generation.assumptions import (
    build_falsified_assumptions_section,
)
from co_scientist.agents.generation.expansion_research import (
    EXPANSION_EXTRA_DRAFT_ITERATIONS,
    build_expansion_section,
    is_research_expansion,
)
from co_scientist.constants import (
    DEEP_HYPOTHESIS_MAX_TOKENS,
    DRAFT_MAX_TOKENS_CAP,
    DRAFT_TOKENS_PER_HYPOTHESIS,
    HIGH_TEMPERATURE,
    corpus_slug,
    get_draft_max_iterations,
    scaled_max_tokens,
)
from co_scientist.llm import (
    DEFAULT_TOOL_LOOP_TOKEN_BUDGET,
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_with_tools,
    campaign_free_mode,
    parse_tool_loop_json,
)
from co_scientist.prompts import (
    DraftPromptRequest,
    PromptRunContext,
    get_draft_prompt_with_tools,
)
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


def _log_lit_review_context(
    articles_with_reasoning: str | None, articles: list[Any]
) -> None:
    """Log whether warm-started literature-review context is available.

    Args:
        articles_with_reasoning: lit review summary text, if any.
        articles: articles already fetched by the literature review (used to
            report the warm-start paper count).
    """
    if articles_with_reasoning:
        logger.info("Including lit review summary as context for drafting")
        logger.info(
            "Warm start: corpus already populated with %s papers"
            " from literature review",
            len(articles),
        )
    else:
        logger.warning(
            "No lit review summary available"
            " - agent will examine papers directly"
        )


class _DraftStateContext(NamedTuple):
    """Per-pass values needed to assemble the Phase 1 draft prompt.

    All but ``skills_section`` come from workflow state; that one comes
    from the caller, because whether a pass was actually given the
    science skills depends on the deployment and on whether this host
    can confine a command, neither of which state records.
    """

    research_goal: str
    supervisor_guidance: dict[str, Any]
    meta_review: Any
    articles_with_reasoning: str | None
    preferences: Any
    attributes: Any
    user_hypotheses: Any
    articles: list[Any]
    run_setup_guidance: Any
    run_focus_guidance: Any
    research_expansion_section: str
    falsified_assumptions_section: str
    lab_constraints: list[str] | None
    skills_section: str


def _gather_draft_state_context(
    state: WorkflowState, skills_section: str = ""
) -> _DraftStateContext:
    """Extract and log the workflow-state values the draft prompt needs.

    Also logs the shared corpus slug (reused by the validation phase for
    warm-start) and the lit-review-context diagnostics.

    Args:
        state: Current workflow state.
        skills_section: Prompt text describing the science skills this
            pass was given; empty when it was given none.

    Returns:
        The bundled values the draft prompt is built from.
    """
    articles_with_reasoning = state.get("articles_with_reasoning")
    articles = state.get("articles") or []

    # Shared slug for corpus (reuse lit review slug for warm start); the
    # validation phase derives the same slug from the research goal.
    shared_slug = corpus_slug(state["research_goal"])
    logger.info("Using shared corpus slug: %s", shared_slug)

    _log_lit_review_context(articles_with_reasoning, articles)

    return _DraftStateContext(
        research_goal=state["research_goal"],
        skills_section=skills_section,
        supervisor_guidance=state.get("supervisor_guidance", {}),
        meta_review=state.get("meta_review"),
        articles_with_reasoning=articles_with_reasoning,
        preferences=state.get("preferences"),
        attributes=state.get("attributes"),
        user_hypotheses=state.get("starting_hypotheses"),
        articles=articles,
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
        # Research expansion (E11b) and verified-wrong assumptions (K9)
        # render as self-contained prompt sections; both are empty
        # strings outside their conditions, so the initial cycle's prompt
        # is unchanged.
        research_expansion_section=build_expansion_section(state),
        falsified_assumptions_section=build_falsified_assumptions_section(
            state.get("hypotheses")
        ),
        # Lab constraints elicited by the goal interview (K5); None or
        # empty renders no section.
        lab_constraints=state.get("lab_constraints"),
    )


def _invoke_draft_prompt_builder(
    count: int,
    max_iterations: int,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
    ctx: _DraftStateContext,
) -> str:
    """Call the draft prompt template with the gathered state context.

    Args:
        count: Number of hypotheses to draft.
        max_iterations: Iteration budget for this draft call.
        tool_registry: Resolved ToolRegistry for tool selection.
        reference_index: Optional `[C*]` citation reference index.
        ctx: Per-pass values from _gather_draft_state_context.

    Returns:
        The assembled draft prompt text.
    """
    ref_text = reference_index.text if reference_index else ""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal=ctx.research_goal,
            hypotheses_count=count,
            articles=ctx.articles,
            articles_with_reasoning=ctx.articles_with_reasoning,
            skills_section=ctx.skills_section,
            preferences=ctx.preferences,
            attributes=ctx.attributes,
            user_hypotheses=ctx.user_hypotheses,
            max_iterations=max_iterations,
            reference_list=ref_text,
            research_expansion_section=ctx.research_expansion_section,
            falsified_assumptions_section=ctx.falsified_assumptions_section,
            lab_constraints=ctx.lab_constraints,
            context=PromptRunContext(
                supervisor_guidance=ctx.supervisor_guidance,
                meta_review=ctx.meta_review,
                tool_registry=tool_registry,
                run_setup_guidance=ctx.run_setup_guidance,
                run_focus_guidance=ctx.run_focus_guidance,
            ),
        )
    )

    return prompt


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


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


@dataclass(frozen=True)
class _DraftCall:
    """Inputs for one draft-phase tool-calling LLM invocation.

    Attributes:
        prompt: The assembled draft prompt.
        openai_tools: OpenAI-format tool schemas available to the agent.
        executor: Tracked tool executor for the draft phase.
        count: Number of hypotheses being drafted.
        max_iterations: Iteration budget for the tool-calling loop.
        max_prompt_tokens: Ceiling on the transcript the loop re-sends.
            Raised only where the science skills attached, whose
            catalogue and documents are what a live pass actually runs
            out of room for.
    """

    prompt: str
    openai_tools: list[Any]
    executor: Any
    count: int
    max_iterations: int
    max_prompt_tokens: int = DEFAULT_TOOL_LOOP_TOKEN_BUDGET


def _parse_draft_response(final_response: str) -> list[dict[str, str]]:
    """Parse the draft agent's final response into draft hypothesis dicts.

    Args:
        final_response: the draft agent's final tool-call-loop response.

    Returns:
        List of draft dicts with text, gap_reasoning, literature_sources.

    Raises:
        ResponseParseError: if the response cannot be parsed as JSON even
            after repair attempts. Failing hard here is deliberate: an empty
            Phase 1 would make Phase 2 a silent no-op too.
    """
    drafts: list[dict[str, str]] = parse_tool_loop_json(
        final_response, "drafts", "Draft phase"
    )
    logger.info("Parsed %s draft hypotheses", len(drafts))
    return drafts


def _compute_draft_max_tokens(count: int, max_iterations: int) -> int:
    """Scale and log the draft agent's max-token budget for this call.

    Args:
        count: Number of hypotheses being drafted.
        max_iterations: Iteration budget for the tool-calling loop.

    Returns:
        The scaled max-tokens budget for the draft agent call.
    """
    # Scale the token budget with the hypotheses count (~200 tokens per
    # hypothesis). K6: the base is the deep-generation budget because the
    # draft prompt now requires full-depth ideas (a shallow draft becomes
    # a shallow final hypothesis).
    draft_max_tokens = scaled_max_tokens(
        DEEP_HYPOTHESIS_MAX_TOKENS,
        count,
        per_item=DRAFT_TOKENS_PER_HYPOTHESIS,
        cap=DRAFT_MAX_TOKENS_CAP,
    )
    logger.info(
        "Calling draft agent: %s iterations, %s max tokens",
        max_iterations,
        draft_max_tokens,
    )
    return draft_max_tokens


def _count_assistant_turns(messages: list[dict[str, Any]]) -> int:
    """Count real completions spent in a tool-call loop's message history.

    Each tool-loop iteration issues exactly one ``litellm.acompletion`` and
    appends its assistant message to the running conversation
    (``llm/tools/loop.py``), so the assistant-role entries are a precise
    count of real LLM calls the loop made -- finding L3's fix for
    tool-based generation, without needing to instrument the ``llm`` package
    itself.

    Args:
        messages: The full running conversation returned by
            ``call_llm_with_tools``.

    Returns:
        The number of assistant-role turns, i.e. real completions made.
    """
    return sum(1 for m in messages if m.get("role") == "assistant")


async def _call_draft_llm_with_tools(
    state: WorkflowState,
    call: _DraftCall,
    draft_max_tokens: int,
) -> tuple[str, int]:
    # Diversity-critical generation: keep drafts fresh, never cache-frozen.
    final_response, messages = await call_llm_with_tools(
        prompt=call.prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=draft_max_tokens,
            temperature=HIGH_TEMPERATURE,
        ),
        loop=ToolLoop(
            tools=call.openai_tools,
            executor=call.executor,
            max_iterations=call.max_iterations,
            max_prompt_tokens=call.max_prompt_tokens,
        ),
        options=LLMCallOptions(
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="generate_draft_with_tools",
        ),
    )
    return final_response, _count_assistant_turns(messages)


async def _invoke_draft_llm(
    state: WorkflowState,
    call: _DraftCall,
    draft_max_tokens: int,
) -> tuple[str, int]:
    """Run the draft agent's tool-calling LLM call, re-raising on failure.

    Args:
        state: Current workflow state.
        call: Inputs for this draft-phase LLM invocation.
        draft_max_tokens: Token budget for this call.

    Returns:
        Tuple of (final response text, real LLM calls made).
    """
    try:
        return await _call_draft_llm_with_tools(state, call, draft_max_tokens)
    except Exception as e:
        # No fallback: Phase 1 failing means there are no drafts to pass to
        # Phase 2, so this re-raises rather than degrading gracefully (unlike
        # the enhancement-node fallbacks in llm.structured.validate's
        # _ENHANCEMENT_NODE_FALLBACKS).
        logger.error("Draft phase failed: %s", e)
        raise


async def _call_draft_agent(
    state: WorkflowState,
    call: _DraftCall,
) -> tuple[str, int]:
    """Invoke the draft agent's tool-calling loop and return its response.

    Args:
        state: Current workflow state.
        call: Inputs for this draft-phase LLM invocation.

    Returns:
        Tuple of (final response text, real LLM calls made).
    """
    draft_max_tokens = _compute_draft_max_tokens(
        call.count, call.max_iterations
    )
    return await _invoke_draft_llm(state, call, draft_max_tokens)


def _log_draft_completion(tool_call_counts: dict[str, int]) -> None:
    """Log the total/per-tool call counts for the completed draft phase.

    Args:
        tool_call_counts: per-tool-name call counts from the tracked
            executor.
    """
    total_calls = sum(tool_call_counts.values())
    calls_summary = ", ".join(
        f"{name}={count}" for name, count in tool_call_counts.items()
    )
    logger.info(
        "Draft phase complete: %s tool calls (%s)", total_calls, calls_summary
    )


def _compute_draft_iteration_budget(
    count: int, is_expansion: bool = False
) -> int:
    """Scale and log the draft phase's iteration budget for this call.

    Args:
        count: Number of hypotheses being drafted.
        is_expansion: Whether this draft is a research-expansion cycle
            (E11b); broad exploratory retrieval gets extra round-trips.

    Returns:
        The iteration budget for the draft tool-calling loop.
    """
    # Calculate dynamic iteration budget based on hypotheses count
    max_iterations = get_draft_max_iterations(count)
    if is_expansion:
        max_iterations += EXPANSION_EXTRA_DRAFT_ITERATIONS
    logger.info(
        "Draft budget: %s iterations for %s hypotheses%s",
        max_iterations,
        count,
        " (research expansion)" if is_expansion else "",
    )
    return max_iterations


def _prepare_draft_call(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> tuple[DraftSkills, int, str]:
    """Resolve tools and assemble the prompt for one draft-phase call.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        mcp_client: MCP client for tool access.
        tool_registry: Optional ToolRegistry for config-driven tool
            selection.
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        Tuple of (the surface to run against, max_iterations, prompt).
    """
    # Initialize hybrid tool provider with draft-specific whitelist
    provider, openai_tools, tool_registry = _setup_tool_provider(
        mcp_client, tool_registry, "draft_generation", "draft", logger
    )

    # Adds the science skills where they are installed, and returns the
    # arguments untouched where they are not.
    skills = attach_skills(state, provider, openai_tools)

    max_iterations = _compute_draft_iteration_budget(
        count, is_expansion=is_research_expansion(state)
    )

    prompt = _invoke_draft_prompt_builder(
        count,
        max_iterations,
        tool_registry,
        reference_index,
        _gather_draft_state_context(state, skills.section),
    )

    return skills, max_iterations, prompt


async def _run_draft_pipeline(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> tuple[str, dict[str, int], int]:
    """Set up tools, build the prompt, and run the draft agent's tool loop.

    Args:
        state: Current workflow state.
        count: Number of hypotheses to draft.
        mcp_client: MCP client for tool access.
        tool_registry: Optional ToolRegistry for config-driven tool
            selection.
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list.

    Returns:
        Tuple of (draft agent's final response text, per-tool call counts,
        real LLM calls made).
    """
    skills, max_iterations, prompt = _prepare_draft_call(
        state, count, mcp_client, tool_registry, reference_index
    )

    # Track tool calls in draft phase
    draft_tracked_executor, tool_call_counts = skills.provider.tracked_executor(
        "Draft"
    )

    final_response, llm_calls = await _call_draft_agent(
        state,
        _DraftCall(
            prompt=prompt,
            openai_tools=skills.tools,
            executor=draft_tracked_executor,
            count=count,
            max_iterations=max_iterations,
            max_prompt_tokens=skills.max_prompt_tokens,
        ),
    )

    return final_response, tool_call_counts, llm_calls


async def draft_hypotheses(
    state: WorkflowState,
    count: int,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> tuple[list[dict[str, str]], int]:
    """Phase 1: draft hypotheses by searching literature sources for metadata.

    Uses tools for searching research literature.
    Tool whitelist is determined from tool_registry if provided,
    otherwise falls back to hardcoded default.

    Args:
        state: Current workflow state
        count: Number of hypotheses to draft
        mcp_client: MCP client for tool access
        tool_registry: Optional ToolRegistry for config-driven tool selection
        reference_index: Optional citation reference index supplying the
            `[C*]` reference list

    Returns:
        Tuple of (draft dicts with text/gap_reasoning/literature_sources,
        real LLM calls made -- finding L3).
    """
    logger.info(
        "Phase 1: Drafting %s hypotheses by examining literature", count
    )

    final_response, tool_call_counts, llm_calls = await _run_draft_pipeline(
        state, count, mcp_client, tool_registry, reference_index
    )

    _log_draft_completion(tool_call_counts)

    return _parse_draft_response(final_response), llm_calls
