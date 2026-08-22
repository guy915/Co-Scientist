"""Offering the vendored science skills to the hypothesis-draft agent.

This is the one consumer the skills are turned on for, and the choice is
a reading of how the published system uses the same resources. The
Co-Scientist papers put tool use in three places -- the Generation
agent's literature exploration, the Reflection agent's *full* review
(the initial review is stated to use no tools), and evolution's
grounding -- and describe the databases as something the agents "utilize
... to constrain searches and generate hypotheses". Phase 1 of
``literature_tools`` is that first place in this codebase: it is where
the generation agent reads literature and drafts from the gaps it finds.

Two properties make it the right host, and both were learned by picking
the wrong one first (``agents/reflection/simulation_execution.py``
records the eighteen runs). Retrieval *is* the task here, so a database
query serves the deliverable instead of competing with it. And the
phase drafts every hypothesis of a cycle in a single tool loop, so the
cost is per cycle rather than per hypothesis -- the multiplicity that
turned a reasonable per-candidate LLM pass into 299 calls a run.

Deferred deliberately: the deep-verification and evolution-grounding
callers, which reach retrieval through
``deep_verification_evidence._retrieve_probe_evidence`` and run per
hypothesis per cycle. They are the shape that incident had.

Inert unless the bundle is installed: ``available_skills()`` is empty
without ``COSCIENTIST_SKILLS_DIR``, so a checkout, a test and a CI job
take the early return and this module changes nothing.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from co_scientist.skills import (
    catalogue_section,
    seed_licence_notices,
)
from co_scientist.state import WorkflowState
from co_scientist.workspace import (
    WorkspaceToolProvider,
    open_draft_workspace,
)
from co_scientist.workspace.tool_schemas import READ_SKILL

logger = logging.getLogger(__name__)

# Reading a skill, running its script and reading the output back is
# about three turns. Two skills is the advertised ceiling, so the loop
# gets the turns for two without taking them from the drafting.
DRAFT_SKILLS_EXTRA_ITERATIONS = 6

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

    The loop's transcript ceiling is deliberately not among these. It is
    already ``DEFAULT_TOOL_LOOP_TOKEN_BUDGET``, a loose backstop rather
    than a measured figure, and skills only ever add to what a pass
    re-sends -- so a number invented here could only shorten the loop it
    is meant to fund. Measure the skills path first, then set one.

    Attributes:
        provider: The provider to execute tool calls against -- the
            workspace one when skills attached, otherwise the MCP
            provider unchanged.
        tools: The schemas to offer, merged.
        section: Prompt text describing the skills, empty when none
            were attached.
        extra_iterations: Turns added to fund reading and running them.
    """

    provider: Any
    tools: list[Any] = field(default_factory=list)
    section: str = ""
    extra_iterations: int = 0


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
    if not skills_section():
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
        DRAFT_SKILLS_EXTRA_ITERATIONS,
    )
