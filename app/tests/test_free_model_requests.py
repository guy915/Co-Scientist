"""App completion boundaries enforce the engine's zero-cost policy."""

from types import SimpleNamespace
from typing import Any

import pytest

from app import (
    credentials,
    goal_restatement,
    interviews_model,
    qa_stream,
    run_start_announcement,
    store,
    title_gen,
)
from app.config import settings

MODEL = "openrouter/campaign/chat:free"
KINDS = ["interview", "qa", "announcement", "title", "restatement", "probe"]


async def _stream_call(kind: str, model: str) -> Any:
    if kind == "interview":
        return await interviews_model._stream_interview_content(
            {
                "turns": [{"role": "user", "content": "Public research"}],
                "fields": {},
            },
            interviews_model.TurnSinks(),
        )
    if kind == "qa":
        return [
            item
            async for item in qa_stream.stream_llm_deltas(
                model, "system", "question", []
            )
        ]
    run = store.create_run("Public research", "express", "engine", {})
    return [
        item
        async for item in run_start_announcement._stream_model_fragments(run)
    ]


async def _invoke(kind: str, model: str) -> Any:
    if kind == "title":
        return await title_gen._request_title_completion("Public research")
    if kind == "restatement":
        return await goal_restatement._request_restatement_completion(
            "Public research"
        )
    if kind == "probe":
        return await credentials.validate_byok_credential(
            credentials.ByokCredential("openrouter", "test-user-key", model)
        )
    return await _stream_call(kind, model)


@pytest.fixture
def captured(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> list[dict[str, Any]]:
    import litellm
    from co_scientist import llm_free_catalog

    monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
    monkeypatch.setattr(
        llm_free_catalog,
        "_fetch_catalog",
        lambda: {
            "campaign/chat:free": {
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )
    monkeypatch.setattr(settings, "chat_model_name", MODEL)
    calls: list[dict[str, Any]] = []

    async def chunks() -> Any:
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="answer", reasoning_content="reasoning"
                    )
                )
            ]
        )

    async def complete(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if kwargs.get("stream"):
            return chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))]
        )

    monkeypatch.setattr(litellm, "acompletion", complete)
    return calls


@pytest.mark.parametrize("kind", KINDS)
async def test_campaign_blocks_paid_app_calls(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[dict[str, Any]],
    kind: str,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setattr(settings, "chat_model_name", "openrouter/campaign/paid")
    with pytest.raises(Exception, match="zero-cost"):
        await _invoke(kind, "openrouter/campaign/paid")
    assert captured == []


@pytest.mark.parametrize("kind", KINDS)
async def test_campaign_free_requests_keep_streams_and_zero_caps(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[dict[str, Any]],
    kind: str,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    result = await _invoke(kind, MODEL)
    assert len(captured) == 1
    request = captured[0]
    assert request["api_base"] == "https://openrouter.ai/api/v1"
    assert request["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    if kind in {"qa", "announcement"}:
        assert ("reasoning", "reasoning") in result
        assert ("chunk", "answer") in result
    if kind == "interview":
        assert result[0] == "answer"
    assert request.get("stream", False) == (
        kind in {"interview", "qa", "announcement"}
    )


@pytest.mark.parametrize("kind", KINDS)
async def test_user_byok_stays_separate_outside_campaign(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[dict[str, Any]],
    kind: str,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    credential = credentials.ByokCredential(
        "openrouter", "test-user-key", "openrouter/campaign/paid"
    )
    with credentials.scoped_byok(credential):
        await _invoke(kind, credential.model)
    assert captured[0]["api_key"] == credential.api_key
    assert captured[0]["model"] == credential.model
    captured.clear()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with (
        credentials.scoped_byok(credential),
        pytest.raises(Exception, match="zero-cost"),
    ):
        await _invoke(kind, credential.model)
    assert captured == []


async def test_free_qa_tool_continuation_keeps_admission(
    monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, Any]]
) -> None:
    import litellm

    from tests.test_qa_ideas import (
        _chunk,
        _idea,
        _scripted_litellm,
        _search_call_chunk,
    )

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    fake = _scripted_litellm([[_search_call_chunk()], [_chunk("answer")]])
    monkeypatch.setattr(litellm, "acompletion", fake.acompletion)
    result = [
        item
        async for item in qa_stream.stream_llm_deltas(
            MODEL, "system", "question", [_idea("Lipid repair")]
        )
    ]
    assert result == [("chunk", "answer")]
    assert len(fake.sent) == 2
    assert fake.sent[1]["messages"][-1]["role"] == "tool"
    assert "Lipid repair" in fake.sent[1]["messages"][-1]["content"]
    for request in fake.sent:
        assert request["extra_body"]["provider"]["max_price"] == {
            "prompt": 0,
            "completion": 0,
            "request": 0,
        }


async def test_interview_reasoning_retry_rechecks_admission(
    monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, Any]]
) -> None:
    import litellm
    from co_scientist import llm_free_catalog
    from co_scientist.exceptions import FreeModelEligibilityError

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")

    async def complete(**kwargs: Any) -> Any:
        captured.append(kwargs)

        async def chunks() -> Any:
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None, reasoning_content="thinking only"
                        )
                    )
                ]
            )
            # The catalog expires between the reasoning-only reply and re-ask.
            monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
            monkeypatch.setattr(llm_free_catalog, "_fetch_catalog", lambda: {})

        return chunks()

    monkeypatch.setattr(litellm, "acompletion", complete)
    with pytest.raises(FreeModelEligibilityError):
        await _invoke("interview", MODEL)
    assert len(captured) == 1


async def test_unscoped_flag_cannot_bypass_offline_guard(
    monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, Any]]
) -> None:
    from app import llm_request
    from app.offline_guard import OfflineModeError

    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    with pytest.raises(OfflineModeError):
        await llm_request.acompletion(byok=True, model=MODEL, messages=[])
    assert captured == []
