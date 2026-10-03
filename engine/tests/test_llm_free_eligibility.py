"""Offline contracts for llm free eligibility."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
import tiktoken

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    current_run_call_count,
    scoped_llm_call_budget,
)
from co_scientist.llm.admission import free_policy as free_catalog
from tests._llm_fake import (
    SEARCH_TOOL,
    _catalog,
    _mock_catalog,
    install_fake_backend,
    make_completion,
    make_message,
    make_tool_call,
    patch_acompletion,
)
from tests._llm_fake import _free_catalog as _isolated_catalog

__all__ = ["_isolated_catalog"]

_LLM_FREE_ELIGIBILITY_MODEL = "openrouter/campaign/zero:free"
_LLM_FREE_ELIGIBILITY_OPTIONS = LLMCallOptions(use_cache=False)


@pytest.mark.usefixtures("_isolated_catalog")
class TestLlmFreeEligibility:
    @pytest.mark.parametrize("entry_point", [call_llm, call_llm_json])
    @pytest.mark.parametrize(
        "pricing,expiration",
        [
            (None, None),
            ({}, None),
            ({"prompt": "0", "completion": "0.01"}, None),
            ({"prompt": "0", "completion": "0"}, "not-a-date"),
            ({"prompt": "0", "completion": "0"}, "2000-01-01"),
        ],
    )
    async def test_unverified_route_never_reaches_provider_or_consumes_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
        entry_point: Any,
        pricing: Any,
        expiration: str | None,
    ) -> None:
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        catalog = _catalog(pricing)
        if expiration is not None:
            catalog["data"][0]["expiration_date"] = expiration
        _mock_catalog(monkeypatch, catalog)
        requests: list[dict[str, Any]] = []
        patch_acompletion(
            monkeypatch,
            [make_completion(make_message('{"ok": true}'))],
            requests,
        )
        run_id = str(uuid4())
        with (
            scoped_llm_call_budget(run_id, 10),
            pytest.raises(RuntimeError, match="zero-cost"),
        ):
            await entry_point(
                "public probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )
        assert requests == []
        assert current_run_call_count(run_id) == 0

    @pytest.mark.parametrize(
        "price", ["NaN", "Infinity", "-1", "1e-999", None, 0, True]
    )
    async def test_invalid_or_nonzero_prices_are_not_rounded_to_free(
        self,
        monkeypatch: pytest.MonkeyPatch,
        price: Any,
    ) -> None:
        _mock_catalog(
            monkeypatch, _catalog({"prompt": "0", "completion": price})
        )
        requests: list[dict[str, Any]] = []
        patch_acompletion(monkeypatch, [], requests)
        with pytest.raises(RuntimeError, match="zero-cost"):
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        extra: dict[str, Any],
    ) -> None:
        _mock_catalog(
            monkeypatch, _catalog({"prompt": "0", "completion": "0", **extra})
        )
        patch_acompletion(monkeypatch, [])
        with pytest.raises(RuntimeError, match="zero-cost"):
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )

    async def test_retry_rechecks_expired_prices_before_counting_or_transport(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from co_scientist.llm.admission import free_policy as free_catalog

        monkeypatch.setattr(free_catalog, "CATALOG_TTL_SECONDS", 0)
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
            await call_llm_json(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )
        assert len(requests) == 1
        assert len(catalog_reads) == 2
        assert current_run_call_count(run_id) == 1

    @pytest.mark.parametrize("entry_point", [call_llm, call_llm_json])
    async def test_qualified_route_sends_zero_caps_and_pinned_endpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        entry_point: Any,
    ) -> None:
        catalog = _catalog({"prompt": "0", "completion": "0"})
        catalog["data"][0]["expiration_date"] = "9999-12-31"
        calls = _mock_catalog(monkeypatch, catalog)
        requests: list[dict[str, Any]] = []
        patch_acompletion(
            monkeypatch,
            [make_completion(make_message('{"ok": true}'))] * 2,
            requests,
        )
        for _ in range(2):
            await entry_point(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        campaign: bool,
        scoped: bool,
    ) -> None:
        from co_scientist.llm import scoped_api_key

        monkeypatch.setenv(
            "COSCIENTIST_REQUIRE_FREE_MODELS", str(int(campaign))
        )
        catalog = _catalog({"prompt": "0", "completion": "1"})
        catalog["data"][0]["expiration_date"] = "not-a-date"
        _mock_catalog(monkeypatch, catalog)
        requests: list[dict[str, Any]] = []
        patch_acompletion(
            monkeypatch, [make_completion(make_message("ok"))], requests
        )
        spec = CompletionSpec(
            _LLM_FREE_ELIGIBILITY_MODEL,
            api_key=None if scoped else "byok-test-key",
        )
        with scoped_api_key("byok-test-key" if scoped else None):
            if campaign:
                with pytest.raises(RuntimeError, match="zero-cost"):
                    await call_llm(
                        "probe", spec, options=_LLM_FREE_ELIGIBILITY_OPTIONS
                    )
            else:
                assert (
                    await call_llm(
                        "probe", spec, options=_LLM_FREE_ELIGIBILITY_OPTIONS
                    )
                    == "ok"
                )
        assert len(requests) == int(not campaign)
        # The bypass ends with the explicit/scoped credential.
        with pytest.raises(RuntimeError, match="zero-cost"):
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )

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
        self,
        monkeypatch: pytest.MonkeyPatch,
        body: dict[str, Any],
    ) -> None:
        from co_scientist.llm import enforce_free_request

        _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
        args = {
            "model": _LLM_FREE_ELIGIBILITY_MODEL,
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        changes: dict[str, Any],
    ) -> None:
        from co_scientist.llm import enforce_free_request

        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
        args = {
            "model": _LLM_FREE_ELIGIBILITY_MODEL,
            "messages": [{"role": "user", "content": "probe"}],
            **changes,
        }
        with pytest.raises(RuntimeError, match="zero-cost"):
            await enforce_free_request(args)

    async def test_catalog_failure_after_expiry_never_uses_stale_prices(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from co_scientist.llm.admission import free_policy as free_catalog

        monkeypatch.setattr(free_catalog, "CATALOG_TTL_SECONDS", 0)
        _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
        requests: list[dict[str, Any]] = []
        patch_acompletion(
            monkeypatch, [make_completion(make_message("ok"))], requests
        )
        await call_llm(
            "probe",
            CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
            options=_LLM_FREE_ELIGIBILITY_OPTIONS,
        )

        def unavailable(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("unavailable")

        monkeypatch.setattr(httpx, "get", unavailable)
        with pytest.raises(RuntimeError, match="zero-cost catalog"):
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )
        assert len(requests) == 1

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"data": []},
            {"data": None},
            {"data": [{"id": "x"}, {"id": "x"}]},
        ],
    )
    async def test_invalid_catalog_fails_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        payload: Any,
    ) -> None:
        _mock_catalog(monkeypatch, payload)
        patch_acompletion(monkeypatch, [])
        with pytest.raises(RuntimeError, match="zero-cost catalog"):
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )

    async def test_unknown_promotion_needs_explicit_ancillary_prices(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from co_scientist.llm import enforce_free_request
        from co_scientist.llm.admission import free_policy as free_catalog

        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        data = _catalog({"prompt": "0", "completion": "0"})
        data["data"][0]["id"] = "campaign/promo"
        _mock_catalog(monkeypatch, data)
        args: dict[str, Any] = {
            "model": "openrouter/campaign/promo",
            "messages": [{"role": "user", "content": "probe"}],
        }
        with pytest.raises(
            RuntimeError, match="zero-cost pricing is incomplete"
        ):
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
        free_catalog.invalidate_catalog()
        await enforce_free_request(args)
        assert args["extra_body"]["provider"]["max_price"]["request"] == 0

    def test_catalog_cache_is_shared_across_worker_event_loops(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from co_scientist.llm import enforce_free_request

        catalog = _catalog({"prompt": "0", "completion": "0"})
        catalog["data"][0]["expiration_date"] = None
        reads = _mock_catalog(monkeypatch, catalog)

        def verify(_: int) -> None:
            asyncio.run(
                enforce_free_request(
                    {"model": _LLM_FREE_ELIGIBILITY_MODEL, "messages": []}
                )
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(verify, range(8)))
        assert len(reads) == 1

    @pytest.mark.parametrize(
        "setting,value",
        [
            ("model_fallbacks", ["openai/paid"]),
            ("model_alias_map", {_LLM_FREE_ELIGIBILITY_MODEL: "openai/paid"}),
        ],
    )
    async def test_sdk_global_routing_cannot_bypass_admission(
        self,
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
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )
        assert requests == []

    @pytest.mark.parametrize("kind", ["text", "json", "tools"])
    async def test_campaign_does_not_reuse_paid_byok_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
        kind: str,
    ) -> None:
        from co_scientist.cache import LLMCache
        from co_scientist.llm import ToolLoop, call_llm_with_tools, precall

        cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
        monkeypatch.setattr(precall, "get_cache", lambda: cache)
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        changes: dict[str, Any],
    ) -> None:
        from co_scientist.exceptions import FreeModelEligibilityError
        from co_scientist.llm import enforce_free_request

        _mock_catalog(monkeypatch, _catalog({"prompt": "0", "completion": "0"}))
        with pytest.raises(FreeModelEligibilityError):
            await enforce_free_request(
                {"model": _LLM_FREE_ELIGIBILITY_MODEL, **changes}
            )

    @pytest.mark.parametrize("inputs", ["text", {"text": True}, 1])
    async def test_malformed_input_modalities_are_not_admitted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        inputs: Any,
    ) -> None:
        from co_scientist.exceptions import FreeModelEligibilityError

        data = _catalog({"prompt": "0", "completion": "0"})
        data["data"][0]["architecture"]["input_modalities"] = inputs
        _mock_catalog(monkeypatch, data)
        patch_acompletion(monkeypatch, [make_completion(make_message("ok"))])
        with pytest.raises(FreeModelEligibilityError):
            await call_llm(
                "probe",
                CompletionSpec(_LLM_FREE_ELIGIBILITY_MODEL),
                options=_LLM_FREE_ELIGIBILITY_OPTIONS,
            )

    @pytest.mark.parametrize("variant", ["pro", "mini"])
    @pytest.mark.parametrize("thinking", [False, True])
    async def test_nex_requests_fund_and_control_observed_reasoning(
        self, monkeypatch: pytest.MonkeyPatch, variant: str, thinking: bool
    ) -> None:
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


_LLM_FREE_PROMOTIONAL_ROUTE_MODEL = "openrouter/stealth/space-bunny-alpha"
_LLM_FREE_PROMOTIONAL_ROUTE_OPTIONS = LLMCallOptions(use_cache=False)


def _promotion(pricing: dict[str, str]) -> dict[str, Any]:
    catalog = _catalog(pricing)
    catalog["data"][0]["id"] = _LLM_FREE_PROMOTIONAL_ROUTE_MODEL.removeprefix(
        "openrouter/"
    )
    return catalog


@pytest.mark.usefixtures("_isolated_catalog")
class TestLlmFreePromotionalRoute:
    async def test_current_free_promotion_pins_provider_and_zero_token_price(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "0")
        _mock_catalog(
            monkeypatch, _promotion({"prompt": "0", "completion": "0"})
        )
        requests: list[dict[str, Any]] = []
        patch_acompletion(
            monkeypatch,
            [make_completion(make_message('{"answer": "ready"}'))],
            requests,
        )

        result = await call_llm_json(
            "Return ready as JSON",
            CompletionSpec(_LLM_FREE_PROMOTIONAL_ROUTE_MODEL),
            options=_LLM_FREE_PROMOTIONAL_ROUTE_OPTIONS,
        )

        assert result == {"answer": "ready"}
        assert len(requests) == 1
        assert requests[0]["extra_body"]["provider"]["max_price"] == {
            "prompt": 0,
            "completion": 0,
            "request": 0,
        }
        assert requests[0]["extra_body"]["provider"]["only"] == ["Stealth"]
        assert requests[0]["extra_body"]["provider"]["allow_fallbacks"] is False

    async def test_promotion_price_change_fails_before_transport(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _mock_catalog(
            monkeypatch, _promotion({"prompt": "0.01", "completion": "0"})
        )
        requests: list[dict[str, Any]] = []
        patch_acompletion(monkeypatch, [], requests)

        with pytest.raises(RuntimeError, match="zero-cost"):
            await call_llm_json(
                "Return ready as JSON",
                CompletionSpec(_LLM_FREE_PROMOTIONAL_ROUTE_MODEL),
                options=_LLM_FREE_PROMOTIONAL_ROUTE_OPTIONS,
            )
        assert requests == []


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

    install_fake_backend(monkeypatch, completion)
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
    # Request serialization does not need a production tokenizer. Build a
    # tiny byte tokenizer so an empty tiktoken cache never fetches a BPE
    # file from the network before the mocked HTTP transport is reached.
    tokenizer = tiktoken.Encoding(
        name="test-byte-tokenizer",
        pat_str="(?s).",
        mergeable_ranks={bytes([value]): value for value in range(256)},
        special_tokens={},
    )
    monkeypatch.setattr(tiktoken, "get_encoding", lambda _name: tokenizer)

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


@pytest.mark.usefixtures("_isolated_catalog")
class TestFreeCatalog:
    def test_expired_catalog_recovers_after_a_failed_refresh(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed refresh withholds stale prices and permits the next read."""
        monkeypatch.setattr(free_catalog, "CATALOG_TTL_SECONDS", 0)
        payload = _catalog({"prompt": "0", "completion": "0"})
        _mock_catalog(monkeypatch, payload)
        assert free_catalog.current_catalog()["campaign/zero:free"][
            "pricing"
        ] == {
            "prompt": "0",
            "completion": "0",
        }

        def unavailable(*_: Any, **__: Any) -> None:
            raise httpx.ConnectError("unavailable")

        monkeypatch.setattr(httpx, "get", unavailable)
        with pytest.raises(
            FreeModelEligibilityError, match="catalog unavailable"
        ):
            free_catalog.current_catalog()
        payload["data"][0]["pricing"]["completion"] = "1"
        reads = _mock_catalog(monkeypatch, payload)
        assert (
            free_catalog.current_catalog()["campaign/zero:free"]["pricing"][
                "completion"
            ]
            == "1"
        )
        assert len(reads) == 1

    def test_injected_reader_is_shared_by_worker_threads(self) -> None:
        """All cohort threads see the installed source and share its cache."""
        from concurrent.futures import ThreadPoolExecutor

        reads: list[int] = []

        def load() -> dict[str, Any]:
            reads.append(1)
            return {"injected": {"pricing": {"prompt": "0"}}}

        with (
            free_catalog.using_catalog_reader(free_catalog.CatalogReader(load)),
            ThreadPoolExecutor(max_workers=4) as pool,
        ):
            results = list(
                pool.map(lambda _: free_catalog.current_catalog(), range(8))
            )
        assert all(result == results[0] for result in results)
        assert "injected" in results[0]
        assert reads == [1]

    def test_nested_reader_scope_restores_its_predecessor_after_failure(
        self,
    ) -> None:
        outer = free_catalog.CatalogReader(lambda: {"outer": {}})
        inner = free_catalog.CatalogReader(lambda: {"inner": {}})
        with free_catalog.using_catalog_reader(outer):
            assert free_catalog.current_catalog() == {"outer": {}}
            with (
                pytest.raises(ValueError, match="scope failed"),
                free_catalog.using_catalog_reader(inner),
            ):
                assert free_catalog.current_catalog() == {"inner": {}}
                raise ValueError("scope failed")
            assert free_catalog.current_catalog() == {"outer": {}}
