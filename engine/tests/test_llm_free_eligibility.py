"""Zero-cost policy is enforced before the public LLM APIs send a request."""

from typing import Any
from uuid import uuid4

import httpx
import pytest

from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
)
from co_scientist.llm_call_budget import (
    current_run_call_count,
    scoped_llm_call_budget,
)
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    patch_acompletion,
)

MODEL = "openrouter/campaign/zero:free"
OPTIONS = LLMCallOptions(use_cache=False)


@pytest.fixture(autouse=True)
def _free_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from co_scientist import llm_free_catalog

    monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)


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


@pytest.mark.parametrize("entry_point", [call_llm, call_llm_json])
@pytest.mark.parametrize(
    "pricing", [None, {}, {"prompt": "0", "completion": "0.01"}]
)
async def test_unverified_price_never_reaches_provider_or_consumes_budget(
    monkeypatch: pytest.MonkeyPatch,
    entry_point: Any,
    pricing: Any,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: httpx.Response(
            200, json=_catalog(pricing), request=httpx.Request("GET", a[0])
        ),
    )
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message('{"ok": true}'))], requests
    )
    run_id = str(uuid4())
    with (
        scoped_llm_call_budget(run_id, 10),
        pytest.raises(RuntimeError, match="zero-cost"),
    ):
        await entry_point(
            "public probe", CompletionSpec(MODEL), options=OPTIONS
        )
    assert requests == []
    assert current_run_call_count(run_id) == 0


def _mock_catalog(monkeypatch: pytest.MonkeyPatch, data: Any) -> list[str]:
    calls: list[str] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(url)
        assert kwargs == {"timeout": 15, "trust_env": False}
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    return calls


@pytest.mark.parametrize(
    "price", ["NaN", "Infinity", "-1", "1e-999", None, 0, True]
)
async def test_invalid_or_nonzero_prices_are_not_rounded_to_free(
    monkeypatch: pytest.MonkeyPatch,
    price: Any,
) -> None:
    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": price}))
    requests: list[dict[str, Any]] = []
    patch_acompletion(monkeypatch, [], requests)
    with pytest.raises(RuntimeError, match="zero-cost"):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)
    assert requests == []


@pytest.mark.parametrize(
    "extra",
    [
        {"request": "0.1"},
        {"input_cache_read": "0.01"},
        {"internal_reasoning": "0.1"},
        {"web_search": "0.01"},
        {"overrides": [{"min_prompt_tokens": 100, "completion": "1"}]},
    ],
)
async def test_ancillary_and_conditional_charges_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, Any],
) -> None:
    _mock_catalog(
        monkeypatch, _catalog({"prompt": "0", "completion": "0", **extra})
    )
    patch_acompletion(monkeypatch, [])
    with pytest.raises(RuntimeError, match="zero-cost"):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)


async def test_retry_rechecks_expired_prices_before_counting_or_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist import llm_free_catalog

    monkeypatch.setattr(llm_free_catalog, "CATALOG_TTL_SECONDS", 0)
    catalog_reads: list[str] = []

    def get(url: str, **kwargs: Any) -> httpx.Response:
        catalog_reads.append(url)
        price = "0" if len(catalog_reads) == 1 else "0.1"
        return httpx.Response(
            200,
            json=_catalog({"prompt": "0", "completion": price}),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", get)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message(""), finish_reason="length")],
        requests,
    )
    run_id = str(uuid4())
    with (
        scoped_llm_call_budget(run_id, 10),
        pytest.raises(RuntimeError, match="zero-cost"),
    ):
        await call_llm_json("probe", CompletionSpec(MODEL), options=OPTIONS)
    assert len(requests) == 1
    assert len(catalog_reads) == 2
    assert current_run_call_count(run_id) == 1


@pytest.mark.parametrize("entry_point", [call_llm, call_llm_json])
async def test_qualified_route_sends_zero_caps_and_pinned_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    entry_point: Any,
) -> None:
    calls = _mock_catalog(
        monkeypatch, _catalog({"prompt": "0", "completion": "0"})
    )
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"ok": true}'))] * 2,
        requests,
    )
    for _ in range(2):
        await entry_point("probe", CompletionSpec(MODEL), options=OPTIONS)
    assert len(calls) == 1
    assert len(requests) == 2
    assert requests[0]["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert requests[0]["api_base"] == "https://openrouter.ai/api/v1"


@pytest.mark.parametrize("campaign", [False, True])
@pytest.mark.parametrize("scoped", [False, True])
async def test_byok_separation_and_campaign_override(
    monkeypatch: pytest.MonkeyPatch,
    campaign: bool,
    scoped: bool,
) -> None:
    from co_scientist.llm_credentials import scoped_api_key

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", str(int(campaign)))
    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "1"}))
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("ok"))], requests
    )
    spec = CompletionSpec(MODEL, api_key=None if scoped else "byok-test-key")
    with scoped_api_key("byok-test-key" if scoped else None):
        if campaign:
            with pytest.raises(RuntimeError, match="zero-cost"):
                await call_llm("probe", spec, options=OPTIONS)
        else:
            assert await call_llm("probe", spec, options=OPTIONS) == "ok"
    assert len(requests) == int(not campaign)
    # The bypass ends with the explicit/scoped credential.
    with pytest.raises(RuntimeError, match="zero-cost"):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)


@pytest.mark.parametrize(
    "body",
    [
        {"plugins": [{"id": "web"}]},
        {"model": "paid/model"},
        {"models": ["paid/model"]},
        {"models": ["missing/model:free"]},
        {"models": ["openrouter/free"]},
        {"service_tier": "priority"},
    ],
)
async def test_unqualified_fallbacks_and_addons_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
) -> None:
    from co_scientist.llm_free_policy import enforce_free_request

    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
    args = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "probe"}],
        "extra_body": body,
    }
    with pytest.raises(RuntimeError, match="zero-cost"):
        await enforce_free_request(args)


@pytest.mark.parametrize(
    "changes",
    [
        {"api_base": "https://different.example/api"},
        {"plugins": []},
        {"tools": [{"type": "web_search"}]},
        {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": "x"}],
                }
            ]
        },
        {"model": "openai/paid"},
        {"model": "openrouter/missing/model"},
    ],
)
async def test_campaign_rejects_unverified_request_shapes(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    from co_scientist.llm_free_policy import enforce_free_request

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
    args = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "probe"}],
        **changes,
    }
    with pytest.raises(RuntimeError, match="zero-cost"):
        await enforce_free_request(args)


async def test_catalog_failure_after_expiry_never_uses_stale_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist import llm_free_catalog

    monkeypatch.setattr(llm_free_catalog, "CATALOG_TTL_SECONDS", 0)
    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("ok"))], requests
    )
    await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx, "get", unavailable)
    with pytest.raises(RuntimeError, match="zero-cost catalog"):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": []}, {"data": None}, {"data": [{"id": "x"}, {"id": "x"}]}],
)
async def test_invalid_catalog_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
) -> None:
    _mock_catalog(monkeypatch, payload)
    patch_acompletion(monkeypatch, [])
    with pytest.raises(RuntimeError, match="zero-cost catalog"):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)


async def test_unknown_promotion_needs_explicit_ancillary_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist import llm_free_catalog
    from co_scientist.llm_free_policy import enforce_free_request

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    data = _catalog({"prompt": "0", "completion": "0"})
    data["data"][0]["id"] = "campaign/promo"
    _mock_catalog(monkeypatch, data)
    args = {
        "model": "openrouter/campaign/promo",
        "messages": [{"role": "user", "content": "probe"}],
    }
    with pytest.raises(RuntimeError, match="zero-cost pricing is incomplete"):
        await enforce_free_request(args)
    data["data"][0]["pricing"].update(
        dict.fromkeys(
            (
                "request",
                "internal_reasoning",
                "input_cache_read",
                "input_cache_write",
            ),
            "0",
        )
    )
    monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
    await enforce_free_request(args)
    assert args["extra_body"]["provider"]["max_price"]["request"] == 0


def test_catalog_cache_is_shared_across_worker_event_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from co_scientist.llm_free_policy import enforce_free_request

    reads = _mock_catalog(
        monkeypatch, _catalog({"prompt": "0", "completion": "0"})
    )

    def verify(_: int) -> None:
        asyncio.run(enforce_free_request({"model": MODEL, "messages": []}))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(verify, range(8)))
    assert len(reads) == 1


@pytest.mark.parametrize(
    "setting,value",
    [
        ("model_fallbacks", ["openai/paid"]),
        ("model_alias_map", {MODEL: "openai/paid"}),
    ],
)
async def test_sdk_global_routing_cannot_bypass_admission(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: Any,
) -> None:
    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
    monkeypatch.setattr(f"litellm.{setting}", value)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("ok"))], requests
    )
    with pytest.raises(RuntimeError, match="zero-cost"):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)
    assert requests == []


@pytest.mark.parametrize("kind", ["text", "json", "tools"])
async def test_campaign_does_not_reuse_paid_byok_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    kind: str,
) -> None:
    from co_scientist import llm_tool_loop
    from co_scientist.cache import LLMCache
    from co_scientist.llm import ToolLoop, call_llm_with_tools

    cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
    monkeypatch.setattr(llm_tool_loop, "get_cache", lambda: cache)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"answer": "cached"}'))],
        requests,
    )
    spec = CompletionSpec("openai/paid", api_key="byok-test-key")

    async def unused_tool(call: Any) -> dict[str, Any]:
        pytest.fail("fixture does not call a tool")

    async def invoke() -> Any:
        if kind == "tools":
            return await call_llm_with_tools(
                "probe", spec, ToolLoop(tools=[], executor=unused_tool)
            )
        entry = call_llm if kind == "text" else call_llm_json
        return await entry("probe", spec)

    await invoke()
    await invoke()
    assert len(requests) == 1
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="zero-cost"):
        await invoke()
    assert len(requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"messages": None},
        {"messages": [None]},
        {"messages": "text"},
        {"tools": None},
        {"tools": [None]},
        {"extra_body": {"provider": None}},
    ],
)
async def test_malformed_containers_raise_terminal_policy_error(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    from co_scientist.exceptions import FreeModelEligibilityError
    from co_scientist.llm_free_policy import enforce_free_request

    _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
    with pytest.raises(FreeModelEligibilityError):
        await enforce_free_request({"model": MODEL, **changes})


@pytest.mark.parametrize("inputs", ["text", {"text": True}, 1])
async def test_malformed_input_modalities_are_not_admitted(
    monkeypatch: pytest.MonkeyPatch,
    inputs: Any,
) -> None:
    from co_scientist.exceptions import FreeModelEligibilityError

    data = _catalog({"prompt": "0", "completion": "0"})
    data["data"][0]["architecture"]["input_modalities"] = inputs
    _mock_catalog(monkeypatch, data)
    patch_acompletion(monkeypatch, [make_completion(make_message("ok"))])
    with pytest.raises(FreeModelEligibilityError):
        await call_llm("probe", CompletionSpec(MODEL), options=OPTIONS)


@pytest.mark.parametrize("variant", ["pro", "mini"])
@pytest.mark.parametrize("thinking", [False, True])
async def test_nex_requests_fund_and_control_observed_reasoning(
    monkeypatch: pytest.MonkeyPatch, variant: str, thinking: bool
) -> None:
    """Observed reasoning gets an explicit control and funded answer budget."""
    from co_scientist.constants import (
        MINIMAL_REASONING_MAX_TOKENS,
        THINKING_FLOOR_MAX_TOKENS,
    )

    model = f"openrouter/nex-agi/nex-n2.5-{variant}:free"
    catalog = _catalog({"prompt": "0", "completion": "0"})
    catalog["data"][0]["id"] = model.removeprefix("openrouter/")
    _mock_catalog(monkeypatch, catalog)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message('{"answer":"public"}'))],
        requests,
    )
    await call_llm_json(
        "public probe",
        CompletionSpec(
            model_name=model,
            max_tokens=100,
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        ),
        options=LLMCallOptions(use_cache=False, enable_thinking=thinking),
        max_attempts=1,
    )
    assert requests[0]["response_format"] == {"type": "json_object"}
    body = requests[0]["extra_body"]
    assert body["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert "models" not in body
    if thinking:
        assert body["reasoning"] == {"enabled": True, "effort": "high"}
    else:
        assert body["reasoning"] == {
            "enabled": True,
            "max_tokens": MINIMAL_REASONING_MAX_TOKENS,
        }
    assert requests[0]["max_tokens"] >= THINKING_FLOOR_MAX_TOKENS
