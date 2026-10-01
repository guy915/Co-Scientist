"""The Supervisor allocation schema's declared constraints are executable.

``_DECISION_SCHEMA`` reads like documentation, and in production nothing
server-side checks it: DeepSeek only accepts json_object, so the schema
reaches the model as prompt text. The enforcement is in-process instead --
``call_llm_json`` validates every parsed response against that same schema
before returning it. These tests pin that, because the natural reading of
"the provider ignores the schema" is that its bounds are advisory, and
under that reading the obvious move is to widen one to quiet a retry.

So each test drives the *real* ``call_llm_json`` by patching the raw
response seam (``llm._call_llm_for_json``), not by patching
``call_llm_json`` itself the way the sibling tests in
``test_supervisor_decision.py`` do. Patching the wrapper would skip the
validation under test and every assertion here would hold vacuously.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from co_scientist.agents.supervisor import supervisor_decision
from co_scientist.llm import call as llm_call
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
)
from tests._state import make_state

# A model in llm.request.thinking._JSON_OBJECT_ONLY_MODEL_FAMILIES, i.e. the
# production shape: the json_schema response format is unavailable, so
# whatever holds has to hold in-process.
_JSON_OBJECT_MODEL = "deepseek/deepseek-v4-flash"


def _allocation_text(**queue_action: Any) -> str:
    """Serialize a well-formed allocation carrying one queue action.

    Args:
        **queue_action: Fields to add to (or override on) the single
            ``reprioritize`` action, e.g. ``priority=999``.

    Returns:
        The raw JSON response text a model attempt would return.
    """
    return json.dumps(
        {
            "next_task": "evolve",
            "reason": "Improve mature leaders.",
            "queue_actions": [
                {
                    "action": "reprioritize",
                    "task_id": "task-1",
                    "reason": "Evidence gap is urgent.",
                    **queue_action,
                }
            ],
        }
    )


async def _allocate(
    monkeypatch: pytest.MonkeyPatch,
    raw_response: str,
    model: str = _JSON_OBJECT_MODEL,
) -> tuple[SupervisorDecision, str, list[str]]:
    """Run one allocation over the real call_llm_json parse/validate loop.

    Args:
        monkeypatch: Fixture used to install the raw-response seam.
        raw_response: The text every attempt's LLM call returns.
        model: Model name, which decides whether the json_object
            provider-capability shim applies.

    Returns:
        The decision, its provenance, and the prompt sent on each attempt
        (so a caller can assert on the retry count and its feedback).
    """
    prompts: list[str] = []

    async def _fake_call(
        prompt: str, spec: Any, enable_thinking: bool = True
    ) -> str:
        prompts.append(prompt)
        return raw_response

    monkeypatch.setattr(llm_call, "_call_llm_for_json", _fake_call)
    state = make_state(
        research_goal="Find a testable mechanism.",
        model_name=model,
        supervisor_model_name=model,
        run_id="run-1",
        supervisor_guidance={"workflow_plan": {}},
        task_history=[],
        meta_review={},
        pending_steering=False,
        held_for_review=[],
    )
    decision, provenance, _ = await supervisor_decision.choose_supervisor_task(
        state,
        SchedulerStats(pool_size=4, reviewed_count=4, iteration=1),
        Budget(max_iterations=4),
    )
    return decision, provenance, prompts


@pytest.mark.asyncio
async def test_in_range_queue_action_priority_reaches_the_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema-conforming queue action survives validation intact.

    The control for the two rejection tests below: without it they could
    both pass because the seam never delivered a usable response at all.
    """
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=88)
    )

    assert provenance == "model"
    assert decision.next_task is TaskType.EVOLVE
    assert decision.queue_actions[0]["priority"] == 88
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_out_of_range_queue_action_priority_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A priority past the declared maximum never reaches the decision.

    Not clamped: rejected. The retry hands the model the validation error,
    and a model that keeps violating loses the allocation to the
    deterministic scheduler rather than having its value quietly bounded.
    """
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=999)
    )

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()
    assert len(prompts) == 5
    assert "VALIDATION ERROR" in prompts[1]
    assert "maximum" in prompts[1]


@pytest.mark.asyncio
async def test_non_integer_queue_action_priority_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-integer priority never reaches the decision either.

    The declared type is as load-bearing as the bounds: this is the value
    that would otherwise be handed to a downstream ``int()``.
    """
    decision, provenance, _ = await _allocate(
        monkeypatch, _allocation_text(priority="urgent")
    )

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()


@pytest.mark.asyncio
async def test_null_queue_action_priority_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null stays legal: the bounds constrain numbers, not the union.

    ``["integer", "null"]`` with ``minimum``/``maximum`` alongside is easy
    to misread as bounding null out. It does not, and must not -- null is
    how a cancel/retry action declines to set a priority at all.
    """
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=None)
    )

    assert provenance == "model"
    assert decision.queue_actions[0]["priority"] is None
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_integral_float_priority_is_normalized_to_an_int(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The surviving live effect of the top-level clamp.

    JSON Schema's "integer" admits a float with no fractional part, so
    ``55.0`` validates. The clamp's ``int()`` is what makes the value that
    leaves the engine a real int.
    """
    body = json.loads(_allocation_text(priority=88))
    body["priority"] = 55.0
    decision, provenance, _ = await _allocate(monkeypatch, json.dumps(body))

    assert provenance == "model"
    assert decision.priority == 55
    assert isinstance(decision.priority, int)


@pytest.mark.asyncio
async def test_missing_next_task_is_backfilled_on_json_object_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one constraint in this schema that production does not enforce.

    ``required`` is relaxed at the top level by the json_object shim: a
    reply with no ``next_task`` at all is completed with the enum's first
    value and recorded as provenance "model" -- a decision the model never
    made -- without so much as a retry. Asserted against the enum source
    rather than the literal, because the substituted value silently
    follows whatever ``_PRODUCTIVE_TASKS`` lists first.
    """
    first_of_enum = supervisor_decision._PRODUCTIVE_TASKS[0]
    decision, provenance, prompts = await _allocate(
        monkeypatch, json.dumps({"reason": "No next_task field at all."})
    )

    assert provenance == "model"
    assert decision.next_task is first_of_enum
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_queue_action_required_fields_are_not_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backfill's reach stops at the array, bounding the gap above.

    ``_backfill_required_fields`` returns at a non-dict, so it never
    descends into ``queue_actions`` items. A queue action missing
    ``task_id`` is therefore rejected even on the provider whose top-level
    required fields get filled in for it.
    """
    body = {
        "next_task": "evolve",
        "reason": "Improve mature leaders.",
        "queue_actions": [{"action": "cancel", "reason": "Superseded."}],
    }
    decision, provenance, _ = await _allocate(monkeypatch, json.dumps(body))

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()
