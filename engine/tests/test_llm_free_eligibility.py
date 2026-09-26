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
from tests._llm_free_fakes import _catalog, _mock_catalog
from tests._llm_free_fakes import _free_catalog as _free_catalog
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    patch_acompletion,
)

MODEL = "openrouter/campaign/zero:free"
OPTIONS = LLMCallOptions(use_cache=False)


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
    catalog = _catalog({"prompt": "0", "completion": "1"})
    catalog["data"][0]["expiration_date"] = "not-a-date"
    _mock_catalog(monkeypatch, catalog)
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
    args: dict[str, Any] = {
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

    catalog = _catalog({"prompt": "0", "completion": "0"})
    catalog["data"][0]["expiration_date"] = None
    reads = _mock_catalog(monkeypatch, catalog)

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


async def test_groq_free_route_is_admitted_only_with_fresh_key_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Campaign admission pins the exact direct route without price caps."""
    import hashlib
    from datetime import datetime, timezone

    from co_scientist import llm_free_policy
    from co_scientist.llm_free_policy import enforce_free_request

    key = "groq-test-key"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{fingerprint}",
    )
    monkeypatch.setattr(
        llm_free_policy,
        "current_catalog",
        lambda: pytest.fail("Groq admission must not query price metadata"),
    )
    args: dict[str, Any] = {
        "model": "groq/openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": "probe"}],
    }

    assert await enforce_free_request(args) is True
    assert args["api_base"] == "https://api.groq.com/openai/v1"
    assert "extra_body" not in args


@pytest.mark.parametrize("stream", [True, False])
async def test_groq_campaign_admits_boolean_stream_values(
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    import hashlib
    from datetime import datetime, timezone

    from co_scientist.llm_free_policy import enforce_free_request

    key = "groq-stream-test-key"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{fingerprint}",
    )
    args: dict[str, Any] = {
        "model": "groq/openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": "probe"}],
        "stream": stream,
    }

    assert await enforce_free_request(args) is True
    assert args["stream"] is stream
    assert args["api_base"] == "https://api.groq.com/openai/v1"


@pytest.mark.parametrize("stream", ["true", 1, None])
async def test_groq_campaign_rejects_non_boolean_stream_values(
    monkeypatch: pytest.MonkeyPatch,
    stream: Any,
) -> None:
    import hashlib
    from datetime import datetime, timezone

    from co_scientist.llm_free_policy import enforce_free_request

    key = "groq-invalid-stream-test-key"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{fingerprint}",
    )
    args: dict[str, Any] = {
        "model": "groq/openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": "probe"}],
        "stream": stream,
    }

    with pytest.raises(RuntimeError, match="zero-cost request"):
        await enforce_free_request(args)


@pytest.mark.parametrize(
    "model",
    ["groq/gpt-oss-120b", "groq/openai/gpt-oss-20b"],
)
async def test_public_system_default_groq_routes_reject_unqualified_models(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    monkeypatch.delenv("COSCIENT_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.delenv("COSCIENT_GROQ_FREE_ZDR_ATTESTATION", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-default-key")
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("unexpected"))], requests
    )

    with pytest.raises(RuntimeError, match="qualified Groq route"):
        await call_llm("public probe", CompletionSpec(model), options=OPTIONS)
    assert requests == []


async def test_public_groq_request_uses_pinned_direct_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public wrapper sends the exact route after its admission gate."""
    import hashlib
    from datetime import datetime, timezone

    from co_scientist import llm_free_policy

    key = "groq-public-test-key"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{fingerprint}",
    )
    monkeypatch.setattr(
        llm_free_policy,
        "current_catalog",
        lambda: pytest.fail("Groq admission must not query price metadata"),
    )
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("ok"))], requests
    )

    assert (
        await call_llm(
            "public probe",
            CompletionSpec("groq/openai/gpt-oss-120b"),
            options=OPTIONS,
        )
        == "ok"
    )
    assert len(requests) == 1
    assert requests[0]["model"] == "groq/openai/gpt-oss-120b"
    assert requests[0]["api_base"] == "https://api.groq.com/openai/v1"
    assert "extra_body" not in requests[0]
    assert "api_key" not in requests[0]


@pytest.mark.parametrize(
    "attestation",
    [
        "",
        "2000-01-01:" + "0" * 64,
    ],
)
async def test_public_groq_request_fails_closed_without_fresh_key_attestation(
    monkeypatch: pytest.MonkeyPatch,
    attestation: str,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-public-test-key")
    monkeypatch.setenv("COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION", attestation)
    requests: list[dict[str, Any]] = []
    patch_acompletion(monkeypatch, [], requests)

    with pytest.raises(RuntimeError, match="Groq Free/ZDR attestation"):
        await call_llm(
            "public probe",
            CompletionSpec("groq/openai/gpt-oss-120b"),
            options=OPTIONS,
        )
    assert requests == []


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "groq/gpt-oss-120b"},
        {"model": "groq/openai/gpt-oss-120b:free"},
        {"api_base": "https://example.invalid/v1"},
        {"extra_body": {}},
        {"extra_body": {"plugins": [{"id": "web"}]}},
        {"plugins": []},
        {"service_tier": "priority"},
        {"reasoning_effort": "high"},
        {"stream": "true"},
        {"stream": 1},
        {"stream_options": {"include_usage": True}},
        {"stream": True, "stream_options": {"include_usage": False}},
        {"stream": True, "stream_options": {"include_usage": True, "other": 1}},
        {"tool_choice": "auto"},
        {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": "x"}],
                }
            ]
        },
        {"tools": [{"type": "web_search"}]},
    ],
)
async def test_groq_route_rejects_aliases_and_unqualified_request_shapes(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    import hashlib
    from datetime import datetime, timezone

    from co_scientist import llm_free_policy
    from co_scientist.llm_free_policy import enforce_free_request

    key = "groq-shape-test-key"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{fingerprint}",
    )
    monkeypatch.setattr(
        llm_free_policy,
        "current_catalog",
        lambda: pytest.fail("Groq admission must not query price metadata"),
    )
    args: dict[str, Any] = {
        "model": "groq/openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": "probe"}],
        **changes,
    }
    with pytest.raises(RuntimeError, match=r"zero-cost|Groq"):
        await enforce_free_request(args)


async def test_groq_campaign_keeps_local_function_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    from datetime import datetime, timezone

    from co_scientist.llm import ToolLoop, call_llm_with_tools

    key = "groq-tool-test-key"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{fingerprint}",
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Local lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("ok"))], requests
    )

    async def unused_tool(_call: Any) -> dict[str, Any]:
        pytest.fail("the fixture does not request a tool call")

    result, _ = await call_llm_with_tools(
        "probe",
        CompletionSpec("groq/openai/gpt-oss-120b"),
        ToolLoop(tools=tools, executor=unused_tool),
        options=OPTIONS,
    )
    assert result == "ok"
    assert requests[0]["tools"] == tools
    assert requests[0]["api_base"] == "https://api.groq.com/openai/v1"
    assert "extra_body" not in requests[0]


@pytest.mark.parametrize(
    "model",
    ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"],
)
async def test_groq_byok_bypasses_system_default_free_attestation(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    monkeypatch.delenv("COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [make_completion(make_message("ok"))], requests
    )

    assert (
        await call_llm(
            "public probe",
            CompletionSpec(
                model,
                api_key="groq-explicit-byok-key",
            ),
            options=OPTIONS,
        )
        == "ok"
    )
    assert requests[0]["api_key"] == "groq-explicit-byok-key"
    assert "api_base" not in requests[0]
