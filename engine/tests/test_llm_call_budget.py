"""The run-scoped provider-request counter and the ceiling it enforces.

Pins ``llm.admission.call_budget`` directly (scope entry/exit, no-run-id safety,
per-run isolation, eviction) and, through ``call_llm``/``call_llm_json``/
``call_llm_with_tools``, that the seam actually counts one increment per
outbound request -- retries and tool-loop turns included -- and that the
error it raises escapes every retry loop rather than being swallowed.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from co_scientist.agents.supervisor.orchestrator_stats import _compute_stats
from co_scientist.exceptions import LLMCallBudgetExceededError
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    current_run_call_count,
    release_run_call_budget,
    scoped_llm_call_budget,
)
from co_scientist.llm.admission.call_budget import (
    _MAX_TRACKED_RUNS,
    record_provider_request,
)
from co_scientist.state import WorkflowState
from tests._llm_backend_fake import install_fake_backend
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import make_completion as _completion
from tests._llm_wrapper_fakes import make_message as _message

_MODEL = "deepseek/deepseek-v4-flash"
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


def _record(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[SimpleNamespace | Exception],
) -> list[dict[str, Any]]:
    """Patches the completion seam, recording each call and its kwargs.

    An ``Exception`` entry is raised instead of returned, so a caller can
    script "fails N times, then answers" without a second fake.
    """
    calls: list[dict[str, Any]] = []
    queue = iter(responses)

    async def fake(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        item = next(queue)
        if isinstance(item, Exception):
            raise item
        return item

    install_fake_backend(monkeypatch, fake)
    return calls


def _flaky(
    fail_times: int, ok: SimpleNamespace
) -> list[SimpleNamespace | Exception]:
    """A response sequence that fails for the first N calls, then answers."""
    failures: list[SimpleNamespace | Exception] = [
        ValueError("transient provider hiccup") for _ in range(fail_times)
    ]
    return [*failures, ok]


# --- unit: the counter module itself ----------------------------------------


def test_no_run_id_never_raises_and_counts_nothing() -> None:
    """A call made with no scope entered is a pure no-op."""
    record_provider_request()  # must not raise
    record_provider_request()


def test_scope_with_none_run_id_is_also_a_no_op() -> None:
    with scoped_llm_call_budget(None, ceiling=1):
        record_provider_request()
        record_provider_request()
        record_provider_request()  # would exceed ceiling=1 if it counted


def test_counts_increment_within_a_scope() -> None:
    run_id = "run-count-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
        record_provider_request()
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_under_ceiling_is_untouched() -> None:
    run_id = "run-under-1"
    with scoped_llm_call_budget(run_id, ceiling=100):
        for _ in range(3):
            record_provider_request()
    assert current_run_call_count(run_id) == 3
    release_run_call_budget(run_id)


def test_exceeding_ceiling_raises_with_count_and_ceiling() -> None:
    run_id = "run-over-1"
    with scoped_llm_call_budget(run_id, ceiling=2):
        record_provider_request()
        record_provider_request()
        with pytest.raises(LLMCallBudgetExceededError) as excinfo:
            record_provider_request()
    assert excinfo.value.count == 3
    assert excinfo.value.ceiling == 2
    release_run_call_budget(run_id)


def test_reentering_a_run_scope_keeps_its_running_count() -> None:
    """A durable run is many tasks; each enters its own scope on one run id."""
    run_id = "run-reenter-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_first_ceiling_seen_wins_on_reentry() -> None:
    """A later task's ceiling argument does not override an already-set one."""
    run_id = "run-reenter-ceiling"
    with scoped_llm_call_budget(run_id, ceiling=1):
        record_provider_request()
    with (
        scoped_llm_call_budget(run_id, ceiling=1000),
        pytest.raises(LLMCallBudgetExceededError),
    ):
        record_provider_request()
    release_run_call_budget(run_id)


def test_two_concurrent_runs_are_counted_independently() -> None:
    """Two threads, each its own event loop's worth of scope, do not mix."""
    results: dict[str, int] = {}

    def _drive(run_id: str, n: int) -> None:
        with scoped_llm_call_budget(run_id, ceiling=None):
            for _ in range(n):
                record_provider_request()
        results[run_id] = current_run_call_count(run_id)

    t1 = threading.Thread(target=_drive, args=("run-a", 5))
    t2 = threading.Thread(target=_drive, args=("run-b", 9))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results == {"run-a": 5, "run-b": 9}
    release_run_call_budget("run-a")
    release_run_call_budget("run-b")


def test_release_drops_the_counter() -> None:
    run_id = "run-release-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    assert current_run_call_count(run_id) == 1
    release_run_call_budget(run_id)
    assert current_run_call_count(run_id) == 0


def test_release_of_an_unseen_run_does_not_raise() -> None:
    release_run_call_budget("run-never-seen")


def test_tracking_cap_evicts_the_oldest_run() -> None:
    """Past the cap, the process cannot grow the tracker unboundedly."""
    run_ids = [f"run-evict-{i}" for i in range(_MAX_TRACKED_RUNS + 1)]
    try:
        for run_id in run_ids:
            with scoped_llm_call_budget(run_id, ceiling=None):
                record_provider_request()
        assert current_run_call_count(run_ids[0]) == 0
        assert current_run_call_count(run_ids[-1]) == 1
    finally:
        for run_id in run_ids:
            release_run_call_budget(run_id)


# --- integration: the seam, through call_llm/call_llm_json/tool loop -------


async def test_call_llm_json_counts_one_per_provider_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every retried attempt is a real request and must be counted."""
    _disable_cache(monkeypatch)
    ok = _completion(_message('{"a": 1}'))
    _record(monkeypatch, _flaky(2, ok))
    run_id = "run-json-attempts"

    with scoped_llm_call_budget(run_id, ceiling=None):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_SCHEMA),
            max_attempts=5,
        )

    assert result == {"a": 1}
    assert current_run_call_count(run_id) == 3
    release_run_call_budget(run_id)


async def test_ceiling_exceeded_escapes_call_llm_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget error must reach the caller, not be retried into oblivion."""
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message('{"a": 1}'))])
    run_id = "run-json-ceiling"

    with (
        scoped_llm_call_budget(run_id, ceiling=0),
        pytest.raises(LLMCallBudgetExceededError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_SCHEMA),
            max_attempts=5,
        )
    release_run_call_budget(run_id)


async def test_ceiling_exceeded_escapes_call_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message("hello"))])
    run_id = "run-text-ceiling"

    with (
        scoped_llm_call_budget(run_id, ceiling=0),
        pytest.raises(LLMCallBudgetExceededError),
    ):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_MODEL), max_attempts=3
        )
    release_run_call_budget(run_id)


async def test_under_ceiling_call_llm_json_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message('{"a": 1}'))])
    run_id = "run-json-under"

    with scoped_llm_call_budget(run_id, ceiling=100):
        result = await call_llm_json(
            "a prompt", CompletionSpec(model_name=_MODEL, json_schema=_SCHEMA)
        )

    assert result == {"a": 1}
    assert current_run_call_count(run_id) == 1
    release_run_call_budget(run_id)


async def test_tool_loop_turns_are_each_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A multi-turn tool loop counts one request per turn, not per loop."""
    from tests._llm_wrapper_fakes import SEARCH_TOOL, make_tool_call

    _disable_cache(monkeypatch)

    async def _executor(tc: Any) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": tc.id, "content": "result"}

    _record(
        monkeypatch,
        [
            _completion(
                _message(
                    None,
                    tool_calls=[
                        make_tool_call("call-1", "search_pubmed", "{}")
                    ],
                )
            ),
            _completion(_message("final answer")),
        ],
    )
    run_id = "run-tool-loop"

    with scoped_llm_call_budget(run_id, ceiling=None):
        text, _ = await call_llm_with_tools(
            prompt="a prompt",
            spec=CompletionSpec(model_name=_MODEL, max_tokens=8000),
            loop=ToolLoop(tools=SEARCH_TOOL, executor=_executor),
        )

    assert text == "final answer"
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_between_task_check_reads_the_seam_count_not_the_self_report() -> None:
    """``_compute_stats`` sees the seam's count even when metrics reports 0.

    Pins the fix for the under-counting bug: a dozen nodes never wrote
    ``metrics.llm_calls`` at all, so the self-reported figure could sit at
    0 through an entire run that made hundreds of real requests. With no
    ``metrics`` key in state (mirroring a node that never reported), the
    scheduler's own observed ``llm_calls`` must still reflect the seam.
    """
    run_id = "run-between-tasks"
    with scoped_llm_call_budget(run_id, ceiling=None):
        for _ in range(7):
            record_provider_request()
    try:
        state = cast(WorkflowState, {"hypotheses": [], "run_id": run_id})
        stats = _compute_stats(state, {})
        assert stats.llm_calls == 7
    finally:
        release_run_call_budget(run_id)


async def test_no_run_id_llm_options_does_not_crash_or_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call under no scope must not raise and must not touch any run."""
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message('{"a": 1}'))])

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name=_MODEL, json_schema=_SCHEMA),
        options=LLMCallOptions(),
    )

    assert result == {"a": 1}
