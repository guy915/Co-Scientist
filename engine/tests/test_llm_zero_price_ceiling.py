"""Free routes retain price ceilings at the provider request boundary."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from co_scientist.llm import (
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
)
from co_scientist.llm_types import CompletionSpec
from tests._llm_wrapper_fakes import (
    SEARCH_TOOL,
    make_completion,
    make_message,
    make_tool_call,
    patch_acompletion,
)

_FREE_MODEL = "openrouter/minimax/minimax-m3:free"
_NO_CACHE = LLMCallOptions(use_cache=False)


async def _tool_executor(call: Any) -> dict[str, str]:
    return {"role": "tool", "tool_call_id": call.id, "content": "tool result"}


async def _invoke(entry_point: str, spec: CompletionSpec) -> None:
    if entry_point == "text":
        await call_llm("Price ceiling probe", spec, options=_NO_CACHE)
    elif entry_point == "json_retry":
        await call_llm_json(
            "Price ceiling probe", spec, options=_NO_CACHE, max_attempts=2
        )
    else:
        await call_llm_with_tools(
            "Price ceiling probe",
            spec,
            ToolLoop(
                tools=SEARCH_TOOL, executor=_tool_executor, max_iterations=2
            ),
            options=_NO_CACHE,
        )


def _responses(entry_point: str) -> list[SimpleNamespace]:
    final = make_completion(make_message('{"answer": "ok"}'))
    if entry_point == "tools":
        return [
            make_completion(
                make_message(
                    None,
                    tool_calls=[make_tool_call("call-1", "search", '{"q": 1}')],
                )
            ),
            final,
        ]
    if entry_point == "json_retry":
        return [
            make_completion(make_message(""), finish_reason="length"),
            final,
        ]
    return [final]


@pytest.mark.parametrize("entry_point", ["text", "json_retry", "tools"])
@pytest.mark.parametrize("api_key", [None, "test-free-byok-key"])
async def test_free_completions_send_zero_price_ceiling_on_every_attempt(
    monkeypatch: pytest.MonkeyPatch, entry_point: str, api_key: str | None
) -> None:
    requests: list[dict[str, Any]] = []

    patch_acompletion(monkeypatch, _responses(entry_point), recorder=requests)
    await _invoke(entry_point, CompletionSpec(_FREE_MODEL, api_key=api_key))

    assert len(requests) == (1 if entry_point == "text" else 2)
    if entry_point == "tools":
        assert {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": "tool result",
        } in requests[1]["messages"]
    if entry_point == "json_retry":
        assert requests[1]["max_tokens"] > requests[0]["max_tokens"]
    for request in requests:
        assert request.get("api_key") == api_key
        body = request["extra_body"]
        assert body["provider"]["max_price"] == {
            "prompt": 0,
            "completion": 0,
            "request": 0,
        }
        assert body["models"] == [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-31b-it:free",
            "minimax/minimax-m2.7:free",
        ]


async def test_explicit_paid_byok_keeps_its_priced_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    async def completion(**kwargs: Any) -> SimpleNamespace:
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    monkeypatch.setattr("litellm.acompletion", completion)
    await call_llm(
        "BYOK probe",
        CompletionSpec(
            model_name="openrouter/z-ai/glm-5.3-flash", api_key="test-byok-key"
        ),
        options=_NO_CACHE,
    )

    assert requests[0]["api_key"] == "test-byok-key"
    cap = requests[0]["extra_body"]["provider"]["max_price"]
    assert cap["prompt"] > 0
    assert cap["completion"] > 0


async def test_litellm_serializes_zero_ceiling_into_openrouter_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed SDK must preserve the cap, not merely accept kwargs."""
    requests: list[httpx.Request] = []

    async def send(
        _client: httpx.AsyncClient, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "test-zero-cap",
                "object": "chat.completion",
                "created": 1,
                "model": "minimax/minimax-m3:free",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-house-key")
    monkeypatch.setenv("OPENROUTER_API_BASE", "https://unverified.example/v1")
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    answer = await call_llm(
        "Price ceiling probe", CompletionSpec(_FREE_MODEL), options=_NO_CACHE
    )

    assert answer == "ok"
    assert len(requests) == 1
    assert str(requests[0].url) == (
        "https://openrouter.ai/api/v1/chat/completions"
    )
    body = json.loads(requests[0].content)
    assert body["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
