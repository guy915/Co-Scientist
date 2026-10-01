"""A scripted provider, a fake sleep and a log reader for the attempt loops.

Drives the three public entry points -- ``call_llm``, ``call_llm_json`` and
``call_llm_with_tools`` -- against the one real boundary,
``litellm.acompletion``, and records everything observable about one call:
what each attempt sent, how long the loop waited, what came back or was
raised, which retry lines were logged at which level, and what the
process-wide throttle counter and the retry telemetry recorded. Used by
``test_llm_attempt_loop.py`` and ``test_llm_attempt_loop_tools.py``.

It imports nothing from beneath ``co_scientist.llm``, so it holds across a
regrouping of the attempt modules. The fake sleep replaces ``asyncio.sleep``
itself -- the one name every wait is looked up under -- rather than a
module's reference to it.
"""

import asyncio
import copy
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from litellm.exceptions import APIError, BadRequestError, RateLimitError
from litellm.exceptions import ContextWindowExceededError as ContextWindow
from litellm.exceptions import Timeout as LiteLLMTimeout

from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    rate_limited_attempt_count,
    scoped_telemetry,
)
from tests._llm_backend_fake import install_fake_backend
from tests._llm_fake import disable_llm_cache
from tests._llm_wrapper_fakes import SEARCH_TOOL
from tests._llm_wrapper_fakes import make_completion as _completion
from tests._llm_wrapper_fakes import make_message as _message
from tests._llm_wrapper_fakes import make_usage as _usage

_MODEL = "deepseek/deepseek-v4-flash"
# Not a declared gateway model, so the rung that answers a mandatory
# reasoning refusal is observable on the wire as a reasoning knob.
GATEWAY_MODEL = "openrouter/deepseek/deepseek-v4-flash"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}

SCHEMA_FEEDBACK = "VALIDATION ERROR FROM PREVIOUS ATTEMPT"

# What each retry line is called below. A message matching none of these at
# WARNING or above is reported as ``other`` so a new line cannot slip in.
_LINE_KINDS: tuple[tuple[str, str], ...] = (
    ("LLM call failed", "failed"),
    ("waiting", "waited"),
    ("not retrying", "terminal"),
    ("Error in LLM tool call loop", "tool-terminal"),
    ("Platform rate limit", "park"),
    ("retrying with", "escalated"),
    ("Schema validation failed", "schema"),
    ("retrying llm call", "retry-debug"),
    ("added validation feedback", "feedback-debug"),
)

Line = tuple[str, str]


async def echo_executor(tc: Any) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tc.id, "content": "result"}


@dataclass(frozen=True)
class Entry:
    """One public entry point, as the tests call it.

    Attributes:
        kind: ``"text"`` (``call_llm``), ``"json"`` (``call_llm_json``) or
            ``"tools"`` (``call_llm_with_tools``).
        model: The model the call names.
        options: The call options, if any.
        executor: What runs a tool call, for the ``"tools"`` kind.
    """

    kind: str
    model: str = _MODEL
    options: LLMCallOptions | None = None
    executor: Callable[[Any], Awaitable[dict[str, Any]]] = echo_executor

    async def __call__(self, max_attempts: int) -> Any:
        """Makes the call; a tool turn has no attempt budget to hand over."""
        spec = CompletionSpec(model_name=self.model, max_tokens=8000)
        if self.kind == "text":
            return await call_llm("a prompt", spec, self.options, max_attempts)
        if self.kind == "json":
            spec = replace(spec, json_schema=_SCHEMA)
            return await call_llm_json(
                "a prompt", spec, max_attempts, self.options
            )
        loop = ToolLoop(tools=SEARCH_TOOL, executor=self.executor)
        return await call_llm_with_tools("a prompt", spec, loop, self.options)


TEXT = Entry("text")
JSON = Entry("json")
TOOLS = Entry("tools")

STANDARD = pytest.mark.parametrize(
    "entry", [TEXT, JSON], ids=["call_llm", "call_llm_json"]
)


@dataclass
class Run:
    """Everything observable about one scripted call."""

    calls: list[dict[str, Any]]
    slept: list[float]
    error: Exception | None
    result: Any
    lines: list[Line]
    throttled: int
    retries: int

    @property
    def max_tokens(self) -> list[int]:
        """The budget each attempt asked for."""
        return [call["max_tokens"] for call in self.calls]

    @property
    def thinking(self) -> list[str]:
        """Whether each attempt asked for thinking, as the wire says it."""
        return [call["extra_body"]["thinking"]["type"] for call in self.calls]

    @property
    def reasoning(self) -> list[Any]:
        """The reasoning knob each attempt carried, where the route has one."""
        return [call["extra_body"].get("reasoning") for call in self.calls]

    @property
    def prompts(self) -> list[str]:
        """The prompt text each attempt sent."""
        return [call["messages"][0]["content"] for call in self.calls]

    @property
    def logged(self) -> list[Line]:
        """The lines a reader of a production log (WARNING and up) sees."""
        return [line for line in self.lines if line[1] != "DEBUG"]

    @property
    def retry_debug(self) -> list[Line]:
        """The loop's own per-retry debug lines."""
        return [line for line in self.lines if line[0] == "retry-debug"]


def _classify(record: logging.LogRecord) -> Line | None:
    """Name a record by the retry line it is, or None when it is neither."""
    text = record.getMessage()
    for needle, kind in _LINE_KINDS:
        if needle in text:
            return kind, record.levelname
    if record.levelno >= logging.WARNING:
        return f"other: {text[:50]}", record.levelname
    return None


class Driver:
    """Calls an entry point against a scripted provider and a fake sleep."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._monkeypatch = monkeypatch
        self._caplog = caplog

    async def __call__(
        self, entry: Entry, script: list[Any], max_attempts: int = 3
    ) -> Run:
        """Runs ``entry`` once and records what happened.

        Args:
            entry: The entry point under test.
            script: What the provider does on successive calls; an
                exception is raised, anything else is returned, and the
                last entry repeats.
            max_attempts: The attempt budget handed to the entry point.

        Returns:
            What went out, what came back and what was logged.
        """
        disable_llm_cache(self._monkeypatch)
        calls: list[dict[str, Any]] = []
        slept: list[float] = []
        queue = list(script)

        async def provider(**kwargs: Any) -> Any:
            # A snapshot: the tool loop keeps appending to its transcript.
            calls.append(copy.deepcopy(kwargs))
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(item, Exception):
                raise item
            return item

        async def sleep(seconds: float) -> None:
            slept.append(seconds)

        install_fake_backend(self._monkeypatch, provider)
        self._monkeypatch.setattr(asyncio, "sleep", sleep)
        throttled_before = rate_limited_attempt_count()
        error: Exception | None = None
        result: Any = None
        with (
            scoped_telemetry("characterization") as telemetry,
            self._caplog.at_level(logging.DEBUG, logger="co_scientist"),
        ):
            try:
                result = await entry(max_attempts)
            except Exception as exc:
                error = exc
        records = self._caplog.records
        return Run(
            calls=calls,
            slept=slept,
            error=error,
            result=result,
            lines=[k for r in records if (k := _classify(r)) is not None],
            throttled=rate_limited_attempt_count() - throttled_before,
            retries=sum(
                usage["retries"] for usage in telemetry.snapshot().values()
            ),
        )


@pytest.fixture
def drive(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Driver:
    """The scripted-provider driver, bound to this test's fixtures."""
    return Driver(monkeypatch, caplog)


def ok(entry: Entry) -> SimpleNamespace:
    """The completion that answers ``entry`` successfully."""
    text = '{"a": 1}' if entry.kind == "json" else "fine"
    return _completion(_message(text))


def rate_limited(reset_in: float | None = None) -> RateLimitError:
    """A 429; with ``reset_in`` it names a platform cap that far off."""
    response = None
    if reset_in is not None:
        reset_ms = int((time.time() + reset_in) * 1000)
        response = httpx.Response(
            status_code=429,
            headers={"x-ratelimit-reset": str(reset_ms)},
            request=httpx.Request("POST", "https://openrouter.ai/api/v1"),
        )
    return RateLimitError(
        message="RateLimitError: OpenrouterException - rate limited",
        llm_provider="openrouter",
        model="m",
        response=response,
    )


def overloaded() -> APIError:
    return APIError(
        status_code=500,
        message=(
            "litellm.APIError: OpenrouterException - Upstream error from "
            "Nvidia: Service temporarily overloaded"
        ),
        llm_provider="openrouter",
        model="m",
    )


def reasoning_mandatory() -> BadRequestError:
    return BadRequestError(
        message=(
            'OpenrouterException - {"error":{"message":"Reasoning is '
            'mandatory for this endpoint and cannot be disabled.",'
            '"code":400}}'
        ),
        model=GATEWAY_MODEL,
        llm_provider="openrouter",
    )


def exhausted() -> SimpleNamespace:
    """A completion that reasoned to its ceiling and wrote nothing."""
    return _completion(
        _message(None),
        usage=_usage(500, 18000, reasoning_tokens=18000),
        finish_reason="length",
    )


def thinking_only() -> SimpleNamespace:
    """A completion that reasoned, stopped normally and wrote nothing."""
    return _completion(
        _message(None),
        usage=_usage(500, 1149, reasoning_tokens=1149),
        finish_reason="stop",
    )


def wrong_type() -> SimpleNamespace:
    """A completion whose JSON parses but breaks the schema."""
    return _completion(_message('{"a": "not a number"}'))


def call_ceiling() -> LLMCallBudgetExceededError:
    return LLMCallBudgetExceededError(count=7, ceiling=5)


def timed_out() -> LiteLLMTimeout:
    return LiteLLMTimeout(message="read timed out", model="m", llm_provider="p")


def too_big() -> ContextWindow:
    return ContextWindow(message="too many tokens", model="m", llm_provider="p")


WAITED_THEN_GAVE_UP: list[Line] = [
    ("failed", "WARNING"),
    ("waited", "WARNING"),
    ("failed", "WARNING"),
    ("waited", "WARNING"),
    ("failed", "ERROR"),
]
