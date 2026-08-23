"""Running the simulation review's model instead of imagining it.

The simulation review asks the reviewer to step through a hypothesis's
mechanism and find where it breaks. Its own prompt used to say
*mentally*, *in your mind's eye* -- an instruction to simulate issued to
something with no way to simulate. This module hands it one: a confined
workspace, a bounded tool loop, and the observations it produced.

Three properties are deliberate.

**It never decides the review.** This runs first and returns *text*: what
the reviewer built, ran, and saw. The review itself is the same
schema-constrained call it always was, with those observations added to
its prompt. So the verdict vocabulary, the structured fields and every
consumer downstream are untouched, and a run where execution is
unavailable produces exactly the review it produced before.

**It never fails the review.** Every failure -- no sandbox, no tools
offered, a model that never calls one, an exception anywhere in the
loop, *and opening the workspace itself* -- returns None, which is the
mental-simulation path. A review that errors because its optional
instrument was missing would be worse than the review that had no
instrument. The workspace-open case is the one worth naming: it is
outside the loop and so outside the loop's own guard, it is the failure
a full or read-only workspace root actually produces, and a review that
raises spends its whole retry budget on the durable path, which leaves
the hypothesis with no simulation review at all rather than a mental
one.

**The science skills are deliberately not offered here.** They were
wired into this node first and measured negative. Eighteen runs over
three mechanisms, split by whether the reviewer actually engaged a
skill: baseline produced an observation 9 times out of 9 (mean 4,771
chars), runs offered skills that ignored them 2 of 2 (4,295), and runs
that used one 5 of 7 (2,839). Two of seven skill-engaged runs beat the
baseline mean; two produced nothing. Budget, per-turn overhead and
prompt ordering were each tested and each rejected -- the last
recovered reliability only by making the model stop reaching for
skills, at which point quality returned to baseline. What is left is a
role conflict: this node exists to build a model and run it, and
retrieval competes with that rather than supporting it, which is why
skill-engaged runs are consistently *faster* than baseline while
producing less.

So the workspace opened here asks for neither the network nor the
skills, and that is this node's decision rather than the deployment's:
``WorkspaceSession.skills_enabled`` defaults off precisely so that
installing the bundle for the consumer it does help -- hypothesis
drafting, where retrieval *is* the task, in
``agents/generation/literature_tools/draft_skills.py`` -- cannot
silently re-arm this one. See `engine/AGENTS.md`.

**Whether it ran is recorded by the caller, not the model.** A verdict
reached by running code and one reached by imagining it are different
kinds of claim, and asking the model to self-report which it did makes
that fact as reliable as the rest of its output. The caller knows.
"""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    truncate_for_prompt,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_with_tools,
)
from co_scientist.models import Hypothesis
from co_scientist.prompts import load_prompt
from co_scientist.state import WorkflowState
from co_scientist.workspace.run_workspace import open_review_workspace
from co_scientist.workspace.tool_schemas import RUN_COMMAND
from co_scientist.workspace.tools import (
    WorkspaceToolProvider,
    workspace_tool_schemas,
)

logger = logging.getLogger(__name__)

# Model<->tool round-trips one simulation may spend. The floor is set by
# what writing a program actually costs: write, run, fix what it got
# wrong, run again, sweep the uncertain parameters, report -- and a
# single crash spends two of those. Measured rather than guessed: at 6
# the first real run (an NF-kB delay model, deepseek-v4-flash) wrote a
# working DDE integrator and a Hopf scan, then hit the ceiling with the
# program still unrun, so the review that asked for it got nothing. The
# neighbouring literature loop budgets 11-50 turns for reading papers.
# The cost of a turn is one LLM call re-sending the transcript, which is
# why this is not simply large; the loop's own wrap-up turn fires at 80%
# and lands a partial answer before the cap in the ordinary case.
MAX_SIMULATION_TURNS = 14

# Prompt tokens one simulation may re-send across those turns. The turn
# ceiling above cannot bound this on its own: a turn re-sends the whole
# transcript, so the fourteenth costs several times the first and total
# spend grows with the square of the turn count. Measured on a live
# extended run, the two separated cleanly -- the items that produced an
# observation spent 50-130k prompt tokens, and the nine that reached the
# turn ceiling and therefore produced nothing spent 190-266k, between
# them 1.81M tokens, 44% of comprehensive reflection and 24% of the run's
# entire input.
#
# This is a backstop and should stay one. A number this close to what
# the work costs decides the outcome rather than catching a runaway, and
# briefly did: with the loop discarding its work at the ceiling, every
# observed failure landed between 132k and 150k -- they were simulations
# that would have finished, priced out one or two turns from the end.
# Both halves of that are fixed where they belong rather than by moving
# this number. The loop now drops the file writes a later write
# superseded (`llm_tool_transcript.elide_superseded_writes`), which is
# most of what a converging simulation re-sends -- 59% of one traced
# transcript, and 37% off its total spend. And reaching the ceiling
# anyway now harvests a partial observation instead of raising, so this
# bounds what a simulation costs without deciding whether it produces
# anything.
#
# With both of those in place the number could be measured rather than
# guessed. Seven budgets from 15k to 150k, four mechanisms each, at the
# turn ceiling above (deepseek-v4-flash, 2026-08-22), scored by checking
# every number in the observation against the tool output that was
# supposed to have produced it -- a model cut off under budget pressure
# has every reason to report work it did not finish, and only the
# transcript can tell a reported number from an invented one:
#
#     budget    turns    $/sim   grounded   numbers   chars
#     15,000      3.8   0.0025        97%        57   4,489
#     45,000      8.8   0.0049        98%        56   4,949
#     90,000      9.5   0.0070        99%        53   4,739
#    150,000     13.8   0.0078        93%        54   5,222
#
# Nothing improves above this. Ten more turns and three times the cost
# buy no more grounded numbers and no longer an observation -- 150k
# scored *lowest* on grounding, since a longer investigation has more
# places to lose track of which number came from where. The useful work
# is done in six to eight turns, and 45k is the last budget at which any
# simulation still finishes on its own rather than being harvested,
# which is the margin worth keeping for hypotheses harder than the four
# measured. 30k measured just as well here and would save a further
# fifth, at the cost of every simulation being cut off.
#
# Denominated in `transcript_tokens`, which estimates from character
# count and does not see the tool schemas resent every turn: measured
# against the provider's own accounting this budget bills around 2.5x
# its face value.
SIMULATION_TOKEN_BUDGET = 45_000

# Longest observation kept. Capped here, at the one place observations are
# produced, so the same bound reaches both readers: the review prompt,
# whose every other section is bounded, and the stored result, which rides
# into `enrichments` and from there into every checkpoint envelope. An
# uncapped field in either is the tool loop's whole output budget --
# thousands of tokens of prose -- landing somewhere sized for a paragraph.
MAX_OBSERVATION_CHARS = 12000


_NO_NETWORK_NOTE = (
    " There is no network access and nothing outside this directory is "
    "reachable, so use only the standard library."
)


def _tool_provider(
    run_id: str, hypothesis_id: str
) -> tuple[WorkspaceToolProvider, list[dict[str, Any]]] | None:
    """Opens this review's workspace and the tools it may offer.

    Returns None when the host cannot confine a command, which is the
    fail-closed case: ``workspace_tool_schemas`` withholds
    ``run_command`` there rather than offering a tool every call would
    refuse, and a simulation that cannot run anything has nothing to
    add to the review.

    The workspace is opened without the network and without the skills:
    a simulation writes its own model and runs it, which needs nothing
    outside the directory, and the module docstring records what
    offering it more than that was measured to cost.
    """
    session = open_review_workspace(run_id, hypothesis_id)
    schemas = workspace_tool_schemas(session.policy)
    if not any(
        schema.get("function", {}).get("name") == RUN_COMMAND
        for schema in schemas
    ):
        return None
    return WorkspaceToolProvider(session), schemas


async def simulation_observations(
    state: WorkflowState, hypothesis: Hypothesis
) -> str | None:
    """Builds and runs a model of one hypothesis's mechanism.

    Args:
        state: The run's workflow state.
        hypothesis: The hypothesis whose mechanism to simulate.

    Returns:
        What the reviewer observed, as text for the review prompt, or
        None if this run cannot execute or the attempt produced nothing.
    """
    run_id = str(state.get("run_id") or "unknown")
    try:
        opened = _tool_provider(run_id, hypothesis.id)
    except Exception as exc:
        # Opening the workspace is the one step outside the loop that
        # touches the machine, so it is the one failure the guard around
        # the loop cannot see: a full or read-only workspace root raises
        # from `mkdir` before any of this module's own handling starts.
        # Unguarded it left the review raising the disk error rather than
        # degrading -- and on the durable path a raising review spends
        # its whole retry budget, so the hypothesis ends up with no
        # simulation review at all rather than a mental one.
        logger.warning(
            "simulation workspace unavailable for %s: %s", hypothesis.id, exc
        )
        return None
    if opened is None:
        logger.info(
            "simulation execution unavailable for %s; reviewing by "
            "mental simulation",
            hypothesis.id,
        )
        return None
    observations = await _run_simulation_loop(state, hypothesis, opened)
    if not observations:
        return None
    return truncate_for_prompt(observations, MAX_OBSERVATION_CHARS)


async def _run_simulation_loop(
    state: WorkflowState,
    hypothesis: Hypothesis,
    opened: tuple[WorkspaceToolProvider, list[dict[str, Any]]],
) -> str:
    """Drives the bounded tool loop, returning "" for every failure."""
    provider, schemas = opened
    try:
        return await _observe(state, hypothesis, provider, schemas)
    finally:
        # A command outliving run_command's yield becomes a session that
        # keeps running, which is what makes a hung simulation -- the
        # expected failure of model-written code -- an orphan holding a
        # sandbox open after the loop that started it is over. Nothing
        # else ends one the model never killed, so the caller does.
        #
        # Guarded because this runs in a `finally`: an exception here
        # would replace whatever the loop was returning, so a cleanup
        # failure after a *successful* simulation would fail the review
        # that had already got its answer.
        try:
            await provider.session.close()
        except Exception as exc:
            logger.warning(
                "could not close the simulation workspace for %s: %s",
                hypothesis.id,
                exc,
            )


def _simulation_loop(
    provider: WorkspaceToolProvider, schemas: list[dict[str, Any]]
) -> ToolLoop:
    """The bounds one simulation runs under, both of them.

    Args:
        provider: The workspace whose tools this simulation may call.
        schemas: Those tools, as the model sees them.

    Returns:
        A loop bounded by turns and by the prompt tokens those turns
        re-send -- see the two constants for why one ceiling is not
        enough.
    """
    return ToolLoop(
        tools=schemas,
        executor=provider.execute_tool_call,
        max_iterations=MAX_SIMULATION_TURNS,
        max_prompt_tokens=SIMULATION_TOKEN_BUDGET,
    )


async def _observe(
    state: WorkflowState,
    hypothesis: Hypothesis,
    provider: WorkspaceToolProvider,
    schemas: list[dict[str, Any]],
) -> str:
    """Runs the loop itself; every failure is an empty observation."""
    prompt = load_prompt(
        "simulation_execution",
        {
            "research_goal": state["research_goal"],
            "hypothesis_text": hypothesis.text,
            "environment_note": _NO_NETWORK_NOTE,
        },
    )
    try:
        observations, _ = await call_llm_with_tools(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=state["model_name"],
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
            ),
            loop=_simulation_loop(provider, schemas),
            options=LLMCallOptions(
                run_id=state.get("run_id"),
                prompt_name=f"simulation_execution_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        # Rare now that the loop harvests a partial answer at its
        # ceilings rather than raising at them: what reaches here is a
        # loop whose closing turn failed too. The mental simulation is a
        # complete review on its own.
        logger.warning(
            "simulation execution failed for %s: %s", hypothesis.id, exc
        )
        return ""
    return observations.strip()
