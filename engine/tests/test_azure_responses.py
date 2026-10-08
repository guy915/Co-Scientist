from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest

from co_scientist.core.exceptions import LLMTimeoutError, ProviderAdmissionError
from co_scientist.platform.db import connect, transaction
from co_scientist.platform.llm.request.azure import (
    LUNA,
    NANO,
    AzureResponsesBackend,
    Completion,
    ResponsesStream,
    normalize_response,
    normalize_usage,
    response_input,
    response_request,
)
from co_scientist.platform.llm.request.backend import LitellmBackend, using_backend
from co_scientist.platform.llm.request.transport import complete_request
from co_scientist.platform.llm.roles import scoped_call_policy
from co_scientist.platform.llm.tools.transcript import _message_to_history_dict

DEPLOYMENTS = {LUNA: "supervisor-deployment", NANO: "worker-deployment"}


def _response(**changes: Any) -> dict[str, Any]:
    return {
        "id": "response-one",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "deployment",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "answer", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 90,
            "output_tokens": 30,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 20},
        },
        **changes,
    }


def _request(**changes: Any) -> dict[str, Any]:
    return {
        "model": NANO,
        "messages": [{"role": "user", "content": "answer"}],
        "max_tokens": 18000,
        **changes,
    }


def _backend(handler: Any) -> AzureResponsesBackend:
    client = openai.OpenAI(
        api_key="fake",
        base_url="https://test.openai.azure.com/openai/v1/",
        max_retries=4,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return AzureResponsesBackend(client, DEPLOYMENTS)


async def test_responses_wire_and_usage_keep_chat_contract_without_sdk_retries() -> None:
    captured = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_response())

    backend = _backend(respond)
    try:
        with scoped_call_policy("overview_outline"):
            answer = await backend.complete(
                **_request(
                    model=LUNA,
                    temperature=0.2,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "result", "schema": {"type": "object"}},
                    },
                )
            )
        assert isinstance(answer, Completion)
        assert answer.choices[0].message.content == "answer"
        assert answer.usage and answer.usage.prompt_tokens == 90
        assert answer.usage.completion_tokens == 30
        assert answer.usage.completion_tokens_details.reasoning_tokens == 20
        body = json.loads(captured[0].content)
        assert captured[0].url.path == "/openai/v1/responses"
        assert body["model"] == DEPLOYMENTS[LUNA]
        assert body["max_output_tokens"] == 18000
        assert body["reasoning"] == {"effort": "none"}
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["store"] is False and "temperature" not in body
    finally:
        backend.close()


async def test_provider_429_is_one_http_request_even_if_sdk_was_configured_to_retry() -> None:
    requests = []

    def refuse(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            429, json={"error": {"message": "rate limited", "type": "rate_limit"}}
        )

    backend = _backend(refuse)
    try:
        with pytest.raises(openai.RateLimitError):
            await backend.complete(**_request())
        assert len(requests) == 1
    finally:
        backend.close()


async def test_gateway_settles_normalized_usage_without_holding_writer_over_http() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        with transaction() as conn:
            conn.execute("UPDATE provider_admissions SET tokens=tokens")
        return httpx.Response(200, json=_response())

    backend = _backend(respond)
    try:
        with using_backend(backend):
            await complete_request(_request(), NANO, byok=False, timeout_seconds=5)
        with connect() as conn:
            tokens = conn.execute("SELECT tokens FROM provider_admissions").fetchall()
        assert len(tokens) == 3 and all(row[0] == 120 for row in tokens)
    finally:
        backend.close()


def test_reasoning_and_call_ids_survive_tool_turn_with_repaired_arguments() -> None:
    items: list[dict[str, Any]] = [
        {"type": "reasoning", "id": "reason-one", "summary": [], "encrypted_content": "opaque"},
        {
            "type": "function_call",
            "id": "item-one",
            "call_id": "call-one",
            "name": "search",
            "arguments": "malformed",
        },
    ]
    result = normalize_response(_response(output=items), NANO)
    history = _message_to_history_dict(result.choices[0].message)
    history["tool_calls"][0]["function"]["arguments"] = '{"query":"short"}'
    converted = response_input(
        [history, {"role": "tool", "tool_call_id": "call-one", "content": "found"}]
    )
    assert converted[0] == items[0]
    assert converted[1]["call_id"] == "call-one" and converted[1]["id"] == "item-one"
    assert converted[1]["arguments"] == '{"query":"short"}'
    assert converted[2] == {
        "type": "function_call_output",
        "call_id": "call-one",
        "output": "found",
    }
    assert items[1]["arguments"] == "malformed"


def test_missing_usage_is_unknown_and_reasoning_is_not_added_to_output() -> None:
    assert normalize_usage(None) is None
    usage = normalize_usage(
        {"output_tokens": 30, "output_tokens_details": {"reasoning_tokens": 20}}
    )
    assert usage and usage.prompt_tokens is None and usage.completion_tokens == 30
    assert (
        normalize_response(
            _response(status="incomplete", incomplete_details={"reason": "max_output_tokens"}), NANO
        )
        .choices[0]
        .finish_reason
        == "length"
    )
    assert (
        normalize_response(
            _response(
                output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]
            ),
            NANO,
        )
        .choices[0]
        .finish_reason
        == "content_filter"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "azure/unknown"},
        {"reasoning_effort": "high"},
        {"reasoning_effort": "none"},
        {"max_tokens": None},
        {"tools": [{"type": "web_search"}]},
    ],
)
def test_unknown_price_unbounded_output_and_hosted_tools_are_refused(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ProviderAdmissionError):
        response_request(_request(**changes), DEPLOYMENTS)


def test_nested_hosted_tool_type_cannot_override_function_type() -> None:
    function = {"type": "web_search", "name": "lookup", "parameters": {"type": "object"}}
    body = response_request(
        _request(tools=[{"type": "function", "function": function}]), DEPLOYMENTS
    )
    assert body["tools"] == [
        {"type": "function", "name": "lookup", "parameters": {"type": "object"}}
    ]


async def test_stream_normalizes_text_tool_fragments_reasoning_items_and_final_usage() -> None:
    output: list[dict[str, Any]] = [
        {"type": "reasoning", "id": "reason-one", "summary": [], "encrypted_content": "opaque"},
        {
            "type": "function_call",
            "id": "item-one",
            "call_id": "call-one",
            "name": "search",
            "arguments": '{"q":"x"}',
        },
    ]
    events = [
        {"type": "response.output_text.delta", "delta": "hello"},
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {**output[1], "arguments": ""},
        },
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"q":'},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '"x"}'},
        {"type": "response.output_item.done", "output_index": 1, "item": output[1]},
        {"type": "response.completed", "response": _response(output=output)},
    ]
    wire = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    backend = _backend(
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=wire)
    )
    try:
        stream = await backend.complete(**_request(stream=True))
        assert isinstance(stream, ResponsesStream)
        chunks = [chunk async for chunk in stream]
        assert chunks[0].choices[0].delta.content == "hello"
        assert chunks[-1].usage and chunks[-1].usage.prompt_tokens == 90
        assert chunks[-1].choices[0].delta.tool_calls[0].responses_items == output
        args = "".join(
            call.function.arguments
            for chunk in chunks
            for call in chunk.choices[0].delta.tool_calls
        )
        assert args == '{"q":"x"}'
    finally:
        backend.close()


async def test_stream_without_terminal_event_does_not_claim_success() -> None:
    backend = _backend(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
        )
    )
    try:
        stream = await backend.complete(**_request(stream=True))
        assert isinstance(stream, ResponsesStream)
        assert (await stream.__anext__()).choices[0].delta.content == "partial"
        with pytest.raises(LLMTimeoutError):
            await stream.__anext__()
    finally:
        backend.close()


async def test_litellm_retry_knobs_cannot_bypass_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = []

    async def complete(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("co_scientist.platform.llm.request.backend.litellm.acompletion", complete)
    await LitellmBackend().complete(model="test/model", max_retries=9, num_retries=7)
    assert captured[0]["max_retries"] == captured[0]["num_retries"] == 0


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://test.openai.azure.com",
        "https://test.invalid",
        "https://test.openai.azure.com/path",
        "https://key@test.openai.azure.com",
    ],
)
def test_factory_refuses_non_resource_endpoints_without_http(
    monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    with pytest.raises(ProviderAdmissionError):
        AzureResponsesBackend.from_environment()
