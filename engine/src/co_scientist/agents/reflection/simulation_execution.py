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

# Longest observation kept. Capped here, at the one place observations are
# produced, so the same bound reaches both readers: the review prompt,
# whose every other section is bounded, and the stored result, which rides
# into `enrichments` and from there into every checkpoint envelope. An
# uncapped field in either is the tool loop's whole output budget --
# thousands of tokens of prose -- landing somewhere sized for a paragraph.
MAX_OBSERVATION_CHARS = 12000


def _tool_provider(
    run_id: str, hypothesis_id: str
) -> tuple[WorkspaceToolProvider, list[dict[str, Any]]] | None:
    """Opens this review's workspace and the tools it may offer.

    Returns None when the host cannot confine a command, which is the
    fail-closed case: ``workspace_tool_schemas`` withholds
    ``run_command`` there rather than offering a tool every call would
    refuse, and a simulation that cannot run anything has nothing to
    add to the review.
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
            loop=ToolLoop(
                tools=schemas,
                executor=provider.execute_tool_call,
                max_iterations=MAX_SIMULATION_TURNS,
            ),
            options=LLMCallOptions(
                run_id=state.get("run_id"),
                prompt_name=f"simulation_execution_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        # Including an exhausted turn budget: a loop that never settled
        # has no observation to report, and the mental simulation is a
        # complete review on its own.
        logger.warning(
            "simulation execution failed for %s: %s", hypothesis.id, exc
        )
        return ""
    return observations.strip()
