"""Commands that outlive the tool call that started them.

The property under test throughout is that **"still running" is a
successful answer**. A bounded command has one move at its deadline --
kill it, report a timeout, and discard both the work and the output it
had already written -- and that move is wrong for every command worth
running at a terminal.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.workspace.command_session import (
    MAX_SESSION_OUTPUT_BYTES,
    SessionRegistry,
)
from co_scientist.workspace.session import WorkspaceSession
from co_scientist.workspace.tool_schemas import POLL_COMMAND, RUN_COMMAND
from co_scientist.workspace.tools import WorkspaceToolProvider


def _call(name: str, arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


async def _execute(
    provider: WorkspaceToolProvider, name: str, **arguments: Any
) -> dict[str, Any]:
    message = await provider.execute_tool_call(_call(name, arguments))
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


async def _wait_for_output(
    provider: WorkspaceToolProvider,
    payload: dict[str, Any],
    needle: str,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Polls a session until ``needle`` shows up in a read's stdout.

    The pump that fills a session's stdout is a background task racing
    whatever bounded wait a caller asks for; a loaded host -- or, on
    Linux, the landlock backend's own re-exec of a fresh interpreter
    before the child even starts -- can outlast a short yield window
    before anything has been written. That race is exactly what "still
    running" exists to tolerate, so it is resolved the way a real
    caller would: poll again, bounded by a total deadline rather than a
    fixed sleep.
    """
    deadline = time.monotonic() + timeout
    while needle not in payload["stdout"]:
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{needle!r} did not appear in stdout within {timeout}s"
            )
        payload = await _execute(
            provider,
            POLL_COMMAND,
            session_id=payload["session_id"],
            cursor=payload["cursor"],
            wait_seconds=0.5,
        )
    return payload


@pytest.fixture
def provider(tmp_path: Path) -> WorkspaceToolProvider:
    return WorkspaceToolProvider(WorkspaceSession(tmp_path))


class TestStillRunningIsAnAnswer:
    async def test_a_slow_command_comes_back_with_a_session(
        self, provider: WorkspaceToolProvider
    ) -> None:
        payload = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-c", "echo early; sleep 30"],
            yield_seconds=0.4,
        )
        assert payload["running"] is True
        assert payload["session_id"]
        # And the output it had already produced is here, which the
        # bounded path discards entirely on its timeout.
        payload = await _wait_for_output(provider, payload, "early")
        assert "early" in payload["stdout"]
        # The command outlives the call that started it on purpose; end
        # it explicitly rather than leaking a "sleep 30" past this test.
        await provider.session.sessions.close()

    async def test_a_fast_command_finishes_in_one_call(
        self, provider: WorkspaceToolProvider
    ) -> None:
        payload = await _execute(
            provider, RUN_COMMAND, argv=["bash", "-lc", "echo hi"]
        )
        assert payload["running"] is False
        assert payload["exit_code"] == 0
        assert "hi" in payload["stdout"]

    async def test_polling_carries_it_to_its_exit_code(
        self, provider: WorkspaceToolProvider
    ) -> None:
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-lc", "sleep 0.3; echo done; exit 7"],
            yield_seconds=0.05,
        )
        polled = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            cursor=started["cursor"],
            wait_seconds=10,
        )
        assert polled["running"] is False
        assert polled["exit_code"] == 7
        assert "done" in polled["stdout"]

    async def test_the_cursor_does_not_repeat_output(
        self, provider: WorkspaceToolProvider
    ) -> None:
        # Without this a chatty command re-sends its whole log on every
        # poll, and the transcript grows quadratically in what it says.
        # "second" is gated behind a read so it cannot exist until the
        # cursor has already advanced past "first" -- an unbounded
        # producer would let the two lines race the same short yield
        # window this test used to assert against directly.
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-c", "echo first; read line; echo second"],
            yield_seconds=0.1,
        )
        started = await _wait_for_output(provider, started, "first")
        assert "first" in started["stdout"]
        polled = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            cursor=started["cursor"],
            input="go\n",
            wait_seconds=10,
        )
        assert "second" in polled["stdout"]
        assert "first" not in polled["stdout"]

    async def test_no_cursor_reads_from_the_start(
        self, provider: WorkspaceToolProvider
    ) -> None:
        started = await _execute(
            provider, RUN_COMMAND, argv=["bash", "-lc", "echo whole"]
        )
        polled = await _execute(
            provider, POLL_COMMAND, session_id=started["session_id"]
        )
        assert "whole" in polled["stdout"]


class TestDrivingIt:
    async def test_input_reaches_a_waiting_command(
        self, provider: WorkspaceToolProvider
    ) -> None:
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-lc", "read line; echo got:$line"],
            yield_seconds=0.05,
        )
        polled = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            cursor=started["cursor"],
            input="hello\n",
            wait_seconds=10,
        )
        assert "got:hello" in polled["stdout"]

    async def test_kill_ends_it(self, provider: WorkspaceToolProvider) -> None:
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-lc", "sleep 60"],
            yield_seconds=0.05,
        )
        killed = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            kill=True,
        )
        assert killed["running"] is False

    async def test_input_to_a_finished_command_is_refused_legibly(
        self, provider: WorkspaceToolProvider
    ) -> None:
        """One poll too late is the model's mistake, not the harness's.

        These calls run under the loop's effect-batched gather, so an
        exception that is not a tool input error is reported as a
        harness fault and logged as one. The model can act on this: the
        command is over, and polling again without input still returns
        everything it printed.
        """
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-lc", "read line; echo got:$line"],
            yield_seconds=0.05,
        )
        await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            input="first\n",
            wait_seconds=10,
        )
        late = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            input="second\n",
        )
        assert "not accepting input" in json.dumps(late)
        assert "tool execution failed" not in json.dumps(late)
        # And the output is still there for a plain poll.
        again = await _execute(
            provider, POLL_COMMAND, session_id=started["session_id"]
        )
        assert "got:first" in again["stdout"]

    async def test_an_unknown_session_says_why(
        self, provider: WorkspaceToolProvider
    ) -> None:
        # The message names the real cause, because the common way to
        # reach it is a worker restart rather than a typo.
        payload = await _execute(provider, POLL_COMMAND, session_id="nope")
        assert "restart" in json.dumps(payload)


class TestBounds:
    async def test_output_is_capped_and_says_so(self, tmp_path: Path) -> None:
        # A command printing forever must not be a memory leak wearing a
        # session id.
        registry = SessionRegistry()
        session_ws = WorkspaceSession(tmp_path)
        session = await registry.start(
            [
                "bash",
                "-lc",
                f"head -c {MAX_SESSION_OUTPUT_BYTES * 2} /dev/zero | tr "
                "'\\0' 'x'",
            ],
            policy=session_ws.policy,
            cwd=session_ws.root,
        )
        await session.wait_for(20)
        read = session.read()
        assert read.truncated["stdout"] is True
        assert len(read.stdout) <= MAX_SESSION_OUTPUT_BYTES
        await registry.close()

    async def test_closing_the_registry_ends_a_live_command(
        self, tmp_path: Path
    ) -> None:
        # Otherwise a workspace that goes away leaves an orphan holding
        # a sandbox open.
        session_ws = WorkspaceSession(tmp_path)
        registry = SessionRegistry()
        session = await registry.start(
            ["bash", "-lc", "sleep 60"],
            policy=session_ws.policy,
            cwd=session_ws.root,
        )
        assert session.running
        await registry.close()
        await asyncio.sleep(0.05)
        assert not session.running

    async def test_too_many_live_commands_is_refused(
        self, tmp_path: Path
    ) -> None:
        # Refused rather than queued: a caller told "started" for
        # something that has not started cannot poll it.
        session_ws = WorkspaceSession(tmp_path)
        registry = SessionRegistry()
        for _ in range(4):
            await registry.start(
                ["bash", "-lc", "sleep 60"],
                policy=session_ws.policy,
                cwd=session_ws.root,
            )
        with pytest.raises(RuntimeError, match="already running"):
            await registry.start(
                ["bash", "-lc", "sleep 60"],
                policy=session_ws.policy,
                cwd=session_ws.root,
            )
        await registry.close()


class TestAnInterruptedCommand:
    """The two halves together, against a command that really was cut.

    A session belongs to the process that started it, so a worker that
    dies takes it with it. What matters is not that this is avoidable
    -- surviving a restart needs a supervisor outside the worker -- but
    that the loss reaches the model as an explicit aborted result
    instead of a conversation the provider refuses.
    """

    async def test_the_resumed_transcript_says_the_call_was_aborted(
        self, tmp_path: Path
    ) -> None:
        from co_scientist.llm.tools.transcript import (
            ABORTED_RESULT,
            normalize_tool_transcript,
        )

        provider = WorkspaceToolProvider(WorkspaceSession(tmp_path))
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-lc", "sleep 60"],
            yield_seconds=0.05,
        )
        assert started["running"] is True

        # The turn as it stands when the worker dies here: the model's
        # request is recorded, the poll that would have answered it is
        # not.
        interrupted = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_poll",
                        "type": "function",
                        "function": {
                            "name": POLL_COMMAND,
                            "arguments": json.dumps(
                                {"session_id": started["session_id"]}
                            ),
                        },
                    }
                ],
            }
        ]
        await provider.session.sessions.close()

        repaired = normalize_tool_transcript(interrupted)
        assert repaired[1]["tool_call_id"] == "call_poll"
        assert json.loads(repaired[1]["content"]) == ABORTED_RESULT

    async def test_polling_a_session_the_restart_ended_is_legible(
        self, tmp_path: Path
    ) -> None:
        # And if the model does poll it anyway, the refusal names the
        # cause rather than reading as a bad session id.
        provider = WorkspaceToolProvider(WorkspaceSession(tmp_path))
        started = await _execute(
            provider,
            RUN_COMMAND,
            argv=["bash", "-lc", "sleep 60"],
            yield_seconds=0.05,
        )
        await provider.session.sessions.close()
        payload = await _execute(
            provider, POLL_COMMAND, session_id=started["session_id"]
        )
        assert "restart" in json.dumps(payload)
