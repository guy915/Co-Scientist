"""Shared test fixtures for llm fake."""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import logging
import time
import types
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from litellm.exceptions import APIError, BadRequestError, RateLimitError
from litellm.exceptions import ContextWindowExceededError as ContextWindow
from litellm.exceptions import Timeout as LiteLLMTimeout

from co_scientist import cache
from co_scientist.cache import LLMCache
from co_scientist.exceptions import LLMCallBudgetExceededError
from co_scientist.generator import GeneratorOptions, HypothesisGenerator
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    precall,
    rate_limited_attempt_count,
    scoped_telemetry,
)
from co_scientist.llm.request import backend
from co_scientist.offline.llm import (
    _ARRAY_LENGTH_HINTS,
    _fill_schema,
    _FillHints,
    _prompt_text,
    _supervisor_allocation_response,
)
from co_scientist.offline.llm import _build_response as _fake_response

# Shared across every fake call in a test run so no two generated leaves
# (hypothesis text, free-form turns, etc.) ever collide.
_counter = itertools.count(1)


def _next_leaf(_field: str = "") -> str:
    """Returns the next process-wide-unique fake string leaf.

    Takes (and ignores) the property name ``_fill_schema`` now passes: the
    runtime router varies its prose by field, but tests want short,
    obviously-fake, globally unique values instead.

    Returns:
        ``"stub-<n>"`` for the next value of the shared ``_counter``.
    """
    return f"stub-{next(_counter)}"


Respond = Callable[..., Awaitable[Any]]


class FakeBackend:
    """Answers completions from a test's own coroutine function.

    Attributes:
        requests: The keyword arguments of every request, in order.
    """

    def __init__(
        self,
        respond: Respond,
        *,
        requests: list[dict[str, Any]] | None = None,
        supports_json_schema: Callable[[str], bool] | None = None,
    ) -> None:
        """Builds the fake.

        Args:
            respond: Awaited with each request's keyword arguments; what it
                returns (or raises) is the provider's answer.
            requests: A list to record into, when the test already holds one;
                otherwise a fresh one.
            supports_json_schema: The capability answer for any model; left
                out, the real default answer (profile, then litellm's
                registry) is used.
        """
        self._respond = respond
        self.requests: list[dict[str, Any]] = (
            [] if requests is None else requests
        )
        self._supports = supports_json_schema

    async def complete(self, **completion_args: Any) -> Any:
        """Records the request, then answers it."""
        self.requests.append(completion_args)
        return await self._respond(**completion_args)

    def supports_json_schema(self, model_name: str) -> bool:
        """Answers from the test when it gave an answer, else the default."""
        if self._supports is not None:
            return self._supports(model_name)
        return backend.litellm_supports_json_schema(model_name)


def restore_backend_at_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Puts back, when the test ends, whichever backend is installed now.

    Recording the current value with ``monkeypatch`` (even when set to
    itself) registers it for restoration; this is the one place a test
    reaches the registry's slot.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(backend, "_installed", backend._installed)


def install_fake_backend(
    monkeypatch: pytest.MonkeyPatch,
    respond: Respond,
    *,
    requests: list[dict[str, Any]] | None = None,
    supports_json_schema: Callable[[str], bool] | None = None,
) -> FakeBackend:
    """Installs a ``FakeBackend`` for the rest of the test.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        respond: Awaited with each request's keyword arguments.
        requests: A list to record into, when the test already holds one.
        supports_json_schema: The capability answer for any model; left out,
            the real default answer is used.

    Returns:
        The installed fake, for the test to inspect.
    """
    fake = FakeBackend(
        respond, requests=requests, supports_json_schema=supports_json_schema
    )
    restore_backend_at_teardown(monkeypatch)
    backend.install_backend(fake)
    return fake


def disable_llm_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``llm.precall.get_cache`` to hand back a disabled cache.

    A disabled ``LLMCache`` returns ``None`` from ``get`` and no-ops in
    ``set``, so the completion path always runs and nothing leaks between
    tests.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(precall, "get_cache", lambda: LLMCache(enabled=False))


def stub_call_llm_json(
    monkeypatch: pytest.MonkeyPatch,
    module: types.ModuleType,
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    """Patch one node module's ``call_llm_json`` to a fixed response.

    The node-level unit-test idiom (see the module docstring): a node
    imports ``call_llm_json`` into its own namespace, so patching that name
    on the node's module replaces its only LLM dependency. The same
    ``response`` comes back regardless of arguments, so in a parallel path
    every item receives an identical result.

    Every invocation is recorded, which callers that only need the stub can
    ignore.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        module: The node module whose imported ``call_llm_json`` to patch.
        response: The dict the stub returns for every call.

    Returns:
        A list the stub appends each call's kwargs to, for spy assertions.
    """
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return response

    monkeypatch.setattr(module, "call_llm_json", fake)
    return calls


def make_test_generator() -> HypothesisGenerator:
    """Builds a small, fast HypothesisGenerator for the end-to-end tests.

    Sized so a full run stays quick: one iteration, two initial
    hypotheses, two evolution slots, and a two-pair tournament, with the
    LLM cache off so the faked completions above are never replayed from
    an earlier test's on-disk entries.

    Returns:
        A HypothesisGenerator over the fake ``"fake/model"`` name.
    """
    return HypothesisGenerator(
        model_name="fake/model",
        max_iterations=1,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
        ),
    )


async def _fake_acompletion(**kwargs: Any) -> Any:
    """Stands in for ``litellm.acompletion``: schema-true JSON or free text.

    Args:
        **kwargs: The completion arguments built by
            ``co_scientist.llm._build_completion_args`` (model, messages,
            response_format, ...); only ``response_format`` and the
            outgoing prompt text are inspected.

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    response_format = kwargs.get("response_format")
    if response_format and response_format.get("type") == "json_schema":
        json_schema = response_format["json_schema"]
        schema = json_schema["schema"]
        if json_schema.get("name") == "supervisor_allocation":
            # Exercise model-directed scheduling with a stable adaptive
            # portfolio: improve leaders first, then explore new regions.
            content = _supervisor_allocation_response(_prompt_text(kwargs))
            return _fake_response(content)
        length_hint = _ARRAY_LENGTH_HINTS.get(json_schema.get("name", ""))
        hints = _FillHints(
            array_lengths=(
                length_hint(_prompt_text(kwargs)) if length_hint else {}
            )
        )
        content = json.dumps(_fill_schema(schema, _next_leaf, hints))
    elif response_format and response_format.get("type") == "json_object":
        # No production call site reaches this branch (every call site
        # that requests JSON also supplies a schema), but it is kept as a
        # safe, schema-less fallback.
        content = "{}"
    else:
        content = f"free-form response {next(_counter)}"
    return _fake_response(content)


def install_fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patches the LLM and cache boundaries for a fast, deterministic run.

    Installs a fake completion backend (see module docstring) and forces LLM
    caching off. The cache override resets the process-wide singleton in
    ``co_scientist.cache`` in addition to setting the env var: the
    singleton is memoized on first use and other test modules may have
    already initialized it as enabled earlier in the same pytest process,
    a state a plain env-var override cannot undo.

    Also forces every schema'd call onto the native "json_schema" response
    format, regardless of the (made-up) test model name: real litellm's
    provider registry does not recognize it and reports no json_schema
    support, which would otherwise route every call through the
    json_object provider-capability shim (schema restated as prompt text
    instead of structured ``response_format``) -- a real production path,
    but not the one this fake speaks, since it builds its response from
    the structured schema rather than parsing it back out of prompt text.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    install_fake_backend(
        monkeypatch,
        _fake_acompletion,
        supports_json_schema=lambda _model_name: True,
    )
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "false")
    monkeypatch.setattr(cache, "_global_cache", None)


# A schema with a nested required object, shared by the capability-shim
# tests (prompt injection) and the back-fill tests (recursion into
# nested objects) so both exercise the same shape.
NESTED_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_test",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "assessment": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["holds", "weakened"],
                    },
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["verdict", "notes"],
            },
        },
        "required": ["summary", "assessment"],
    },
}


def make_message(
    content: str | None,
    tool_calls: list[Any] | None = None,
    role: str = "assistant",
) -> SimpleNamespace:
    """Build a litellm-shaped ``choices[0].message`` object.

    Args:
        content: The assistant message text (``None`` mirrors an empty
            completion).
        tool_calls: Optional list of tool-call namespaces; ``None`` ends the
            tool loop because the wrapper guards with
            ``and message.tool_calls``.
        role: The message role echoed back into the message history.

    Returns:
        A ``SimpleNamespace`` exposing ``role``, ``content``, and
        ``tool_calls``.
    """
    return SimpleNamespace(role=role, content=content, tool_calls=tool_calls)


def make_usage(
    prompt_tokens: int, completion_tokens: int, reasoning_tokens: int = 0
) -> SimpleNamespace:
    """Build a litellm-shaped ``response.usage`` object.

    Args:
        prompt_tokens: Prompt tokens to report.
        completion_tokens: Completion tokens to report.
        reasoning_tokens: Reasoning tokens to report under
            ``completion_tokens_details.reasoning_tokens``; 0 omits nothing
            (the field is still present, just zero).

    Returns:
        A namespace exposing ``prompt_tokens``, ``completion_tokens``, and
        ``completion_tokens_details.reasoning_tokens``.
    """
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        completion_tokens_details=SimpleNamespace(
            reasoning_tokens=reasoning_tokens
        ),
    )


def make_completion(
    message: SimpleNamespace,
    usage: SimpleNamespace | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    """Wrap a message in the ``choices[0].message`` envelope litellm returns.

    Args:
        message: The message namespace from :func:`make_message`.
        usage: Optional token-usage namespace from :func:`make_usage`;
            omitted (``None``) mirrors a response with no usage reported.
        finish_reason: Why the provider stopped. Omitted (``None``) leaves
            the attribute off the choice entirely, mirroring a provider
            that does not report one -- which is what the readers in
            ``llm.request.response`` are written to tolerate.

    Returns:
        A response namespace with a single choice carrying ``message``,
        plus ``usage`` when given.
    """
    choice = SimpleNamespace(message=message)
    if finish_reason is not None:
        choice.finish_reason = finish_reason
    return SimpleNamespace(choices=[choice], usage=usage)


def make_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    """Build a litellm-shaped tool-call namespace.

    Args:
        call_id: The tool-call id echoed into the message history.
        name: The function name the wrapper reads via ``tc.function.name``.
        arguments: The raw JSON argument string (kept opaque by the wrapper).

    Returns:
        A namespace exposing ``id`` and ``function.{name,arguments}``.
    """
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def patch_acompletion(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[SimpleNamespace],
    recorder: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Install a fake backend that returns queued responses in order.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        responses: Completion namespaces to return on successive calls.
        recorder: Appended the keyword arguments of each call, for tests
            asserting on what was actually sent rather than on what came
            back.

    Returns:
        A mutable dict whose ``"calls"`` key counts how many times the fake ran.
    """
    state = {"calls": 0}
    queue = iter(responses)

    async def fake_acompletion(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        state["calls"] += 1
        return next(queue)

    install_fake_backend(monkeypatch, fake_acompletion, requests=recorder)
    return state


# The tool schema shared verbatim by every call_llm_with_tools test; the
# wrapper only reads it (passes it through to the fake acompletion), never
# mutates it, so sharing one instance across tests is safe.
SEARCH_TOOL: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "search"}}
]

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
    return make_completion(make_message(text))


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
    return make_completion(
        make_message(None),
        usage=make_usage(500, 18000, reasoning_tokens=18000),
        finish_reason="length",
    )


def thinking_only() -> SimpleNamespace:
    """A completion that reasoned, stopped normally and wrote nothing."""
    return make_completion(
        make_message(None),
        usage=make_usage(500, 1149, reasoning_tokens=1149),
        finish_reason="stop",
    )


def wrong_type() -> SimpleNamespace:
    """A completion whose JSON parses but breaks the schema."""
    return make_completion(make_message('{"a": "not a number"}'))


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


@pytest.fixture
def _free_catalog(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from co_scientist.llm.admission import free_policy as free_catalog

    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    with free_catalog.using_catalog_reader(free_catalog.CatalogReader()):
        yield


def _catalog(pricing: Any) -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "campaign/zero:free",
                "pricing": pricing,
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        ]
    }


def _mock_catalog(monkeypatch: pytest.MonkeyPatch, data: Any) -> list[str]:
    calls: list[str] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(url)
        assert kwargs == {"timeout": 15, "trust_env": False}
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    return calls


_FREE: Any = [
    [0.0, 0.0, 0.0],
    0.0,
    {"max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}},
]
_UNPRICED: Any = [None, 0.0, {}]
_STEALTH_PIN: Any = {
    "allow_fallbacks": False,
    "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0},
    "only": ["Stealth"],
    "order": None,
}
_CAP_1: Any = {"max_price": {"prompt": 0.462, "completion": 1.3860000000000001}}
_CAP_2: Any = {"max_price": {"prompt": 1.3860000000000001, "completion": 4.158}}
_CAP_3: Any = {
    "max_price": {"prompt": 0.2625, "completion": 1.5750000000000002}
}
_CAP_4: Any = {"max_price": {"prompt": 2.625, "completion": 10.5}}
_KNOBS_1: Any = [
    {"enabled": True, "effort": "high"},
    {"enabled": True, "max_tokens": 2048},
    {"enabled": True, "effort": "low"},
]
_KNOBS_2: Any = [
    {"enabled": True, "effort": "high"},
    {"enabled": False},
    {"enabled": True, "effort": "low"},
]
_REQUESTS_1: Any = [
    ["json_object", True, 18000, True],
    ["json_object", False, 18000, True],
]
_REQUESTS_2: Any = [
    ["json_object", True, 18000, True],
    ["json_object", False, 4000, True],
]
_REQUESTS_3: Any = [
    ["json_schema", False, 4000, True],
    ["json_object", False, 4000, True],
]

CAPABILITIES: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        (
            "openrouter/nex-agi/nex-n2.5-pro:free",
            "openrouter/nex-agi/nex-n2.5-mini:free",
            "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
            "openrouter/google/gemma-4-31b-it:free",
            "openrouter/minimax/minimax-m2.7:free",
            "openrouter/dots-studio/dots-3-note-preview:free",
            "openrouter/nvidia/nemotron-3.5-lightning:free",
            "openrouter/stealth/space-bunny-alpha",
        ),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {"provider": "gateway provider"},
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_1,
        },
    ),
    (
        ("openrouter/qwen/qwen3.8-27b:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {"provider": "gateway provider"},
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": True,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": [
                ["json_schema", False, 18000, True],
                ["json_object", False, 18000, True],
            ],
        },
    ),
    (
        ("openrouter/z-ai/glm-5.2:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {
                "provider": "gateway provider",
                "models": [
                    "minimax/minimax-m3:free",
                    "nvidia/nemotron-3-super-120b-a12b:free",
                    "nvidia/nemotron-3.5-lightning:free",
                ],
            },
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_1,
        },
    ),
    (
        ("openrouter/minimax/minimax-m3:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {
                "provider": "gateway provider",
                "models": [
                    "nvidia/nemotron-3-super-120b-a12b:free",
                    "google/gemma-4-31b-it:free",
                    "minimax/minimax-m2.7:free",
                ],
            },
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_1,
        },
    ),
    (
        ("openrouter/z-ai/glm-5.3-flash",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {
                "provider": "gateway provider",
                "models": [
                    "minimax/minimax-m3:free",
                    "nvidia/nemotron-3.5-lightning:free",
                ],
            },
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_1,
        },
    ),
    (
        (
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-reasoner",
            "deepseek/deepseek-v5-x",
            "vendor/mydeepseek-r9",
            "DeepSeek/DeepSeek-V4-Flash",
        ),
        {
            "reasons": True,
            "effort": [{"reasoning_effort": "high"}, {}],
            "knobs": [
                {"type": "enabled"},
                {"type": "disabled"},
                {"type": "disabled"},
            ],
            "routing": {},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_2,
        },
    ),
    (
        (
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.5-flash-lite",
            "gemini/gemini-2.5-pro",
            "openai/gpt-4o",
            "azure/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4-5",
            "gpt-4o",
            "ollama/llama3",
            "openrouter/x/y",
            "openrouter/qwen/qwen3.8-27b",
            "openrouter/stealth/space-bunny-alpha-2",
            "gemini/gemini-2.0-flash",
        ),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": "registry",
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_3,
        },
    ),
    (
        (
            "gemini/gemini-3.1-flash-lite",
            "gemini/gemini-3-x",
            "gemini/gemini-3.5-flash",
            "openrouter/google/gemini-3-x",
            "Gemini/Gemini-3.1-Flash-Lite",
        ),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": "registry",
            "temperature": [1.0, 1.0, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_3,
        },
    ),
    (
        (
            "openrouter/deepseek/deepseek-v4-flash",
            "openrouter/deepseek/deepseek-v4-flash-0731",
            "openrouter/deepseek/deepseek-v4-pro",
            "openrouter/deepseek/deepseek-v5-x",
        ),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_2,
            "routing": {"provider": "gateway provider"},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_2,
        },
    ),
    (
        ("openrouter/google/gemma-4-26b-a4b-it:free",),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": [
                ["json_object", True, 4000, True],
                ["json_object", False, 4000, True],
            ],
        },
    ),
    (
        ("stealth/space-bunny-alpha", "openrouter/x/y:free"),
        {
            "reasons": False,
            "effort": [{}, {}],
            "knobs": [None, None, None],
            "routing": {},
            "thinks": [False, True],
            "floor": [4000, 4000],
            "schema": "registry",
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_3,
        },
    ),
    (
        ("openrouter/deepseek/deepseek-v4-flash:free",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_2,
            "routing": {"provider": "gateway provider"},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [True, False],
            "free_row": "ok",
            "requests": _REQUESTS_2,
        },
    ),
    (
        ("openrouter/vendor/gemini-3-deepseek-hybrid",),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_2,
            "routing": {"provider": "gateway provider"},
            "thinks": [False, True],
            "floor": [18000, 4000],
            "schema": False,
            "temperature": [1.0, 1.0, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_2,
        },
    ),
    (
        (
            "OpenRouter/Stealth/Space-Bunny-Alpha",
            "OpenRouter/NEX-AGI/NEX-N2.5-PRO:FREE",
        ),
        {
            "reasons": True,
            "effort": [{}, {}],
            "knobs": _KNOBS_1,
            "routing": {"provider": "gateway provider"},
            "thinks": [True, True],
            "floor": [18000, 18000],
            "schema": False,
            "temperature": [0.0, 0.7, 1.0],
            "free": [False, False],
            "free_row": "zero-cost pricing is incomplete",
            "requests": _REQUESTS_1,
        },
    ),
]

MONEY: dict[str, Any] = {
    "openrouter/nex-agi/nex-n2.5-pro:free": _FREE,
    "openrouter/nex-agi/nex-n2.5-mini:free": _FREE,
    "openrouter/qwen/qwen3.8-27b:free": [
        [0.0, 0.0, 0.0],
        0.0,
        {
            "data_collection": "deny",
            "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0},
            "only": ["modelrun"],
            "order": None,
            "zdr": True,
        },
    ],
    "openrouter/z-ai/glm-5.2:free": _FREE,
    "openrouter/minimax/minimax-m3:free": _FREE,
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": _FREE,
    "openrouter/google/gemma-4-31b-it:free": _FREE,
    "openrouter/minimax/minimax-m2.7:free": _FREE,
    "openrouter/dots-studio/dots-3-note-preview:free": _FREE,
    "openrouter/nvidia/nemotron-3.5-lightning:free": _FREE,
    "openrouter/stealth/space-bunny-alpha": [
        [0.0, 0.0, 0.0],
        0.0,
        _STEALTH_PIN,
    ],
    "openrouter/z-ai/glm-5.3-flash": [
        [0.075, 0.25, 0.015],
        0.295,
        {"max_price": {"prompt": 0.07875, "completion": 0.2625}},
    ],
    "deepseek/deepseek-v4-flash": [[0.44, 1.32, 0.0], 1.76, _CAP_1],
    "deepseek/deepseek-v4-pro": [[1.32, 3.96, 0.0], 5.28, _CAP_2],
    "deepseek/deepseek-chat": [[0.44, 1.32, 0.0], 1.76, _CAP_1],
    "deepseek/deepseek-reasoner": [[1.32, 3.96, 0.0], 5.28, _CAP_2],
    "gemini/gemini-2.5-flash": [
        [0.3, 2.5, 0.0],
        2.8,
        {"max_price": {"prompt": 0.315, "completion": 2.625}},
    ],
    "gemini/gemini-2.5-flash-lite": [
        [0.1, 0.4, 0.0],
        0.5,
        {
            "max_price": {
                "prompt": 0.10500000000000001,
                "completion": 0.42000000000000004,
            }
        },
    ],
    "gemini/gemini-2.5-pro": [
        [1.25, 10.0, 0.0],
        11.25,
        {"max_price": {"prompt": 1.3125, "completion": 10.5}},
    ],
    "gemini/gemini-3.1-flash-lite": [[0.25, 1.5, 0.0], 1.75, _CAP_3],
    "openrouter/deepseek/deepseek-v4-flash": [
        [0.083, 0.165, 0.017],
        0.21500000000000002,
        {"max_price": {"prompt": 0.08715, "completion": 0.17325000000000002}},
    ],
    "openrouter/deepseek/deepseek-v4-flash-0731": [
        [0.13, 0.28, 0.028],
        0.35900000000000004,
        {"max_price": {"prompt": 0.1365, "completion": 0.29400000000000004}},
    ],
    "openrouter/deepseek/deepseek-v4-pro": [
        [1.6, 3.2, 0.13],
        4.065,
        {
            "max_price": {
                "prompt": 1.6800000000000002,
                "completion": 3.3600000000000003,
            }
        },
    ],
    "openai/gpt-4o": [[2.5, 10.0, 0.0], 12.5, _CAP_4],
    "azure/gpt-4o": [[2.5, 10.0, 0.0], 12.5, _CAP_4],
    "openai/gpt-4o-mini": [
        [0.15, 0.6, 0.0],
        0.75,
        {"max_price": {"prompt": 0.1575, "completion": 0.63}},
    ],
    "anthropic/claude-sonnet-4-5": [
        [3.0, 15.0, 0.0],
        18.0,
        {"max_price": {"prompt": 3.1500000000000004, "completion": 15.75}},
    ],
    "openrouter/google/gemma-4-26b-a4b-it:free": _UNPRICED,
    "stealth/space-bunny-alpha": _UNPRICED,
    "gpt-4o": _UNPRICED,
    "ollama/llama3": _UNPRICED,
    "openrouter/x/y": _UNPRICED,
    "openrouter/x/y:free": _UNPRICED,
    "openrouter/qwen/qwen3.8-27b": _UNPRICED,
    "openrouter/stealth/space-bunny-alpha-2": _UNPRICED,
    "deepseek/deepseek-v5-x": _UNPRICED,
    "openrouter/deepseek/deepseek-v5-x": _UNPRICED,
    "openrouter/deepseek/deepseek-v4-flash:free": _UNPRICED,
    "vendor/mydeepseek-r9": _UNPRICED,
    "gemini/gemini-3-x": _UNPRICED,
    "gemini/gemini-3.5-flash": _UNPRICED,
    "openrouter/google/gemini-3-x": _UNPRICED,
    "gemini/gemini-2.0-flash": _UNPRICED,
    "openrouter/vendor/gemini-3-deepseek-hybrid": _UNPRICED,
    "DeepSeek/DeepSeek-V4-Flash": [None, 0.0, _CAP_1],
    "OpenRouter/Stealth/Space-Bunny-Alpha": [None, 0.0, _STEALTH_PIN],
    "OpenRouter/NEX-AGI/NEX-N2.5-PRO:FREE": [
        None,
        0.0,
        {"max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}},
    ],
    "Gemini/Gemini-3.1-Flash-Lite": [None, 0.0, _CAP_3],
}
