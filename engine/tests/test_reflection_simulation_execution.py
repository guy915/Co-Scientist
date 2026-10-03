"""The simulation review, given something to simulate with.

The review's own prompt used to instruct the model to simulate the
mechanism *mentally, in your mind's eye* -- an instruction issued to
something with no way to run anything. These tests cover the instrument
that closes that, and, at least as importantly, that a run without the
instrument produces exactly the review it always produced.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import (
    comprehensive_reflection as review_prompt_context,
)
from co_scientist.agents.reflection import simulation_execution as se
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.generator import run_setup
from co_scientist.workspace.session import WorkspaceSession
from tests._state import make_hypothesis, make_state

# A tool surface that includes run_command, so the two tests below
# exercise the loop rather than the platform they happen to run on.
_RUNNABLE_TOOLS = [{"function": {"name": "run_command"}}]


def _state(**overrides: Any) -> Any:
    """A workflow state with the flags this module reads set."""
    state = make_state(hypotheses=[], current_iteration=0)
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


class TestWhenItRuns:
    """Three gates, all of which have to hold."""

    async def test_it_is_off_unless_the_caller_asked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = AsyncMock(return_value="observed something")
        monkeypatch.setattr(cr, "simulation_observations", called)

        observations = await cr._observations_for(
            _state(), make_hypothesis(text="a"), ReviewType.SIMULATION
        )

        assert observations is None
        assert called.await_count == 0

    async def test_only_the_simulation_review_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The other five reviews ask questions running code cannot
        # settle; offering it to them would be cost without a claim.
        called = AsyncMock(return_value="observed something")
        monkeypatch.setattr(cr, "simulation_observations", called)
        state = _state(enable_simulation_execution=True)

        for review_type in ReviewType:
            if review_type is ReviewType.SIMULATION:
                continue
            assert (
                await cr._observations_for(
                    state, make_hypothesis(text="a"), review_type
                )
                is None
            )
        assert called.await_count == 0

    async def test_it_runs_when_asked_for_the_simulation_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cr,
            "simulation_observations",
            AsyncMock(return_value="the model diverged at step 3"),
        )

        observations = await cr._observations_for(
            _state(enable_simulation_execution=True),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
        )

        assert observations == "the model diverged at step 3"


class TestTheOfflineBackendNeverExecutes:
    """The second gate, which the two host gates cannot stand in for."""

    def test_an_offline_run_stays_mental(self) -> None:
        # The offline responder answers completions locally and never
        # emits a tool call, so the loop would end on its first free-text
        # reply having run nothing -- billed turns for an observation
        # that is only the model's prose about a program it never wrote.
        assert (
            run_setup._resolve_simulation_execution(
                {"enable_simulation_execution": True}, "offline/deterministic"
            )
            is False
        )

    def test_a_real_model_asked_for_may_execute(self) -> None:
        assert (
            run_setup._resolve_simulation_execution(
                {"enable_simulation_execution": True}, "deepseek/some-model"
            )
            is True
        )

    def test_an_omitted_option_is_not_a_request(self) -> None:
        assert (
            run_setup._resolve_simulation_execution({}, "deepseek/some-model")
            is False
        )


class TestDegradation:
    """Every failure is the review that was always here, not an error."""

    async def test_an_unconfinable_host_reviews_mentally(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The fail-closed case, and the reason this is a capability.

        ``workspace_tool_schemas`` withholds ``run_command`` where no
        backend can confine it rather than offering a tool every call
        would refuse. A simulation that cannot run anything has nothing
        to add, so it says so and the review proceeds unchanged -- a
        review that errored because its optional instrument was absent
        would be worse than the review that never had one.
        """
        monkeypatch.setattr(se, "workspace_tool_schemas", lambda policy: [])
        monkeypatch.setattr(
            se,
            "open_review_workspace",
            lambda *a, **k: WorkspaceSession(tmp_path),
        )
        loop = AsyncMock()
        monkeypatch.setattr(se, "call_llm_with_tools", loop)

        result = await se.simulation_observations(
            _state(run_id="r1"), make_hypothesis(text="a")
        )

        assert result is None
        assert loop.await_count == 0

    async def test_an_unopenable_workspace_reviews_mentally(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one failure outside the loop, and so outside its guard.

        A full or read-only workspace root raises from ``mkdir`` before
        any of this module's handling begins. Unguarded, the review
        raised the disk error instead of degrading -- and on the durable
        path a raising review spends its whole retry budget, so the
        hypothesis ends with no simulation review at all rather than the
        mental one this module promises.
        """

        def _no_space(*_args: Any, **_kwargs: Any) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(se, "open_review_workspace", _no_space)

        assert (
            await se.simulation_observations(
                _state(run_id="r1"), make_hypothesis(text="a")
            )
            is None
        )

    async def test_a_failing_close_does_not_lose_the_observations(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The close runs in a `finally`, so an exception there replaces
        # what the loop was returning -- failing a review that had
        # already got its answer.
        session = WorkspaceSession(tmp_path)

        async def _wont_close() -> None:
            raise OSError("the sandbox is gone")

        monkeypatch.setattr(session.sessions, "close", _wont_close)
        monkeypatch.setattr(
            se, "open_review_workspace", lambda *a, **k: session
        )
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )
        monkeypatch.setattr(
            se,
            "call_llm_with_tools",
            AsyncMock(return_value=("the model held", [])),
        )

        assert (
            await se.simulation_observations(
                _state(run_id="r1"), make_hypothesis(text="a")
            )
            == "the model held"
        )

    async def test_a_failing_loop_reviews_mentally(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )
        monkeypatch.setattr(
            se,
            "open_review_workspace",
            lambda *a, **k: WorkspaceSession(tmp_path),
        )
        monkeypatch.setattr(
            se,
            "call_llm_with_tools",
            AsyncMock(side_effect=RuntimeError("provider fell over")),
        )

        assert (
            await se.simulation_observations(
                _state(run_id="r1"), make_hypothesis(text="a")
            )
            is None
        )

    async def test_an_empty_answer_is_not_an_observation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A blank reply is a simulation that produced nothing, which
        # must reach the review as "nothing ran" rather than as an empty
        # observations block it would read as "ran, saw nothing".
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )
        monkeypatch.setattr(
            se,
            "open_review_workspace",
            lambda *a, **k: WorkspaceSession(tmp_path),
        )
        monkeypatch.setattr(
            se, "call_llm_with_tools", AsyncMock(return_value=("  \n ", []))
        )

        assert (
            await se.simulation_observations(
                _state(run_id="r1"), make_hypothesis(text="a")
            )
            is None
        )


class TestTheSessionsItLeaves:
    """A hung simulation is the expected case, so nothing may outlive it."""

    async def test_a_command_still_running_is_ended_with_the_loop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``run_command`` starts sessions, and a session outlives its call.

        Model-written code that hangs is what the repair path exists for,
        so the review's most likely leftover is exactly the one nothing
        else ends: the ceiling is four live sessions per workspace, and a
        review pool multiplies that by the hypotheses in flight. The loop
        that started them closes them.
        """
        session = WorkspaceSession(tmp_path)
        monkeypatch.setattr(
            se, "open_review_workspace", lambda *a, **k: session
        )
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )

        started: list[dict[str, Any]] = []

        async def _hang(**kwargs: Any) -> tuple[str, list[Any]]:
            message = await kwargs["loop"].executor(
                _tool_call(argv=["bash", "-lc", "sleep 60"], yield_seconds=0.05)
            )
            started.append(json.loads(message["content"]))
            return "the model did not converge", []

        monkeypatch.setattr(se, "call_llm_with_tools", _hang)

        await se.simulation_observations(
            _state(run_id="r1"), make_hypothesis(text="a")
        )

        # Asserted outside the loop: `_observe` swallows every exception,
        # so a failure raised inside it would read as a clean pass.
        assert started and started[0]["running"] is True
        assert session.sessions._sessions == {}


def _tool_call(**arguments: Any) -> SimpleNamespace:
    """One run_command tool call in the shape the executor expects."""
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="run_command", arguments=json.dumps(arguments)
        ),
    )


class TestWhatTheReviewerSees:
    """The observations reach the prompt, and their absence is stated."""

    def test_observations_are_handed_to_the_reviewer(self) -> None:
        variables = cr._prompt_variables(
            _state(),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
            None,
            "peak concentration 4.1 uM at t=90s",
        )

        assert (
            "peak concentration 4.1 uM" in (variables["execution_observations"])
        )

    def test_no_execution_says_so_rather_than_leaving_a_gap(self) -> None:
        variables = cr._prompt_variables(
            _state(), make_hypothesis(text="a"), ReviewType.SIMULATION, None
        )

        assert (
            variables["execution_observations"]
            == review_prompt_context._NO_EXECUTION_NOTE
        )

    def test_the_template_carries_the_section(self) -> None:
        from co_scientist.prompts.loading import load_prompt

        prompt = load_prompt(
            "simulation_review",
            cr._prompt_variables(
                _state(),
                make_hypothesis(text="a"),
                ReviewType.SIMULATION,
                None,
                "the rate constant is 40x too small",
            ),
        )

        assert "the rate constant is 40x too small" in prompt
        assert "{{" not in prompt


class TestProvenance:
    """Whether a verdict was run or imagined is recorded, not inferred."""

    async def test_an_executed_review_is_marked_executed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cr, "call_llm_json", AsyncMock(return_value={"verdict": "holds"})
        )
        monkeypatch.setattr(
            cr,
            "simulation_observations",
            AsyncMock(return_value="it held to 3 sig figs"),
        )

        _, result, _ = await cr._run_review(
            _state(enable_simulation_execution=True),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
        )

        assert result is not None
        assert result["executed"] is True
        assert result["execution_observations"] == "it held to 3 sig figs"

    async def test_a_mental_review_is_marked_not_executed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The distinction the reader needs: a `breaks_down` from a run
        # and one from imagination are different kinds of claim, and a
        # missing flag would let the second pass for the first.
        monkeypatch.setattr(
            cr,
            "call_llm_json",
            AsyncMock(return_value={"verdict": "breaks_down"}),
        )

        _, result, _ = await cr._run_review(
            _state(), make_hypothesis(text="a"), ReviewType.SIMULATION
        )

        assert result is not None
        assert result["executed"] is False
        assert "execution_observations" not in result

    async def test_other_reviews_carry_no_execution_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
        )

        _, result, _ = await cr._run_review(
            _state(), make_hypothesis(text="a"), ReviewType.FULL
        )

        assert result is not None
        assert "executed" not in result


class TestIsolation:
    """One workspace per hypothesis, for the reason variants get one."""

    def test_two_reviews_of_one_run_do_not_share_a_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Review items fan out as separate leased tasks and run at once.

        A shared directory would have two simulations each reading part
        of the other's model, and both would then report a coherent
        observation about the wrong hypothesis -- a failure no review
        makes visible, which is why the isolation is structural rather
        than a convention about who writes when.
        """
        from co_scientist.workspace import run_workspace

        monkeypatch.setattr(run_workspace, "workspaces_root", lambda: tmp_path)

        first = run_workspace.open_review_workspace("run-1", "hyp-a")
        second = run_workspace.open_review_workspace("run-1", "hyp-b")

        assert first.root != second.root
        assert first.root.is_dir() and second.root.is_dir()


def test_the_simulation_loop_carries_its_own_spend_ceiling() -> None:
    """A turn ceiling cannot bound what a growing transcript costs.

    Measured on a live extended run: simulations that produced an
    observation spent 50-130k prompt tokens, and the nine that reached the
    14-turn ceiling -- and so produced nothing, since reaching it is what
    failing means -- spent 190-266k, 1.81M between them and 24% of the
    run's entire input. The ceiling here is tighter than the generic
    backstop because a simulation's spend has actually been measured:
    a sweep of seven budgets found nothing above 45k that any observation
    was better for (see the constant's own comment).
    """
    from co_scientist.agents.reflection.simulation_execution import (
        MAX_SIMULATION_TURNS,
        SIMULATION_TOKEN_BUDGET,
    )
    from co_scientist.llm import DEFAULT_TOOL_LOOP_TOKEN_BUDGET

    assert SIMULATION_TOKEN_BUDGET < DEFAULT_TOOL_LOOP_TOKEN_BUDGET
    # Enough for the six-to-eight turns the useful work takes, and for
    # some simulations to still finish rather than be harvested; below
    # the range where more turns stopped buying a better observation.
    assert 30_000 <= SIMULATION_TOKEN_BUDGET <= 60_000
    assert MAX_SIMULATION_TURNS == 14
