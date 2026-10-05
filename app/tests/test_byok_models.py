from __future__ import annotations

from typing import Any

import pytest
from starlette.datastructures import Headers

from app import byok_models, credentials
from app.config import BYOK_PROVIDER_DEFAULT_MODELS, settings
from app.engine_adapter.opts import build_generator
from app.run_modes import resolved_run_config
from tests._store_helpers import seed_run

_KEY = "sk-model-choice-123456"


@pytest.fixture
def byok_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "byok_encryption_key", "model-choice")


def _headers(**extra: str) -> Headers:
    return Headers(
        {"X-LLM-API-Key": _KEY, "X-LLM-Provider": "deepseek", **extra}
    )


def test_every_provider_lists_its_default_first() -> None:
    catalog = byok_models.model_catalog()
    assert set(catalog) == set(BYOK_PROVIDER_DEFAULT_MODELS)
    for provider, models in catalog.items():
        assert models[0] == BYOK_PROVIDER_DEFAULT_MODELS[provider]
        assert len(models) == len(set(models))


def test_omitted_models_resolve_to_the_provider_default() -> None:
    cred = credentials.credential_from_headers(_headers())
    assert cred is not None
    assert cred.model == "deepseek/deepseek-flash"
    assert cred.supervisor_model == "deepseek/deepseek-flash"
    assert cred.models == ("deepseek/deepseek-flash",)


def test_chosen_models_ride_the_headers() -> None:
    cred = credentials.credential_from_headers(
        _headers(**{"X-LLM-Supervisor-Model": "deepseek/deepseek-v4-pro"})
    )
    assert cred is not None
    assert cred.model == "deepseek/deepseek-flash"
    assert cred.supervisor_model == "deepseek/deepseek-v4-pro"
    assert cred.models == (
        "deepseek/deepseek-flash",
        "deepseek/deepseek-v4-pro",
    )


def test_a_model_from_another_provider_is_refused() -> None:
    with pytest.raises(credentials.ByokRequestError):
        credentials.credential_from_headers(
            _headers(**{"X-LLM-Model": "openai/gpt-4o"})
        )


def test_supervisor_model_round_trips_through_storage(
    byok_secret: None,
) -> None:
    run = seed_run("goal", profile="express")
    cred = credentials.ByokCredential(
        provider="deepseek",
        api_key=_KEY,
        model="deepseek/deepseek-v4-flash",
        supervisor_model="deepseek/deepseek-v4-pro",
    )
    credentials.store_run_credential(run.id, run.client_id, cred)
    assert credentials.get_run_credential(run.id) == cred


async def test_validation_proves_each_distinct_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    async def fake_acompletion(**kwargs: object) -> None:
        seen.append(kwargs["model"])

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    cred = credentials.ByokCredential(
        provider="deepseek",
        api_key=_KEY,
        model="deepseek/deepseek-v4-flash",
        supervisor_model="deepseek/deepseek-v4-pro",
    )
    await credentials.validate_byok_credential(cred)
    assert seen == ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro"]


def test_generator_runs_each_tier_on_its_chosen_model() -> None:
    captured: dict[str, Any] = {}

    def generator(**kwargs: Any) -> None:
        captured.update(kwargs)

    cred = credentials.ByokCredential(
        provider="deepseek",
        api_key=_KEY,
        model="deepseek/deepseek-v4-flash",
        supervisor_model="deepseek/deepseek-v4-pro",
    )
    build_generator(generator, resolved_run_config({}), byok=cred)
    assert captured["model_name"] == "deepseek/deepseek-v4-flash"
    options = captured["options"]
    assert options.supervisor_model_name == "deepseek/deepseek-v4-pro"


def test_catalog_endpoint_lists_every_provider() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.get(
            "/api/byok-models", headers={"X-Client-ID": "catalog"}
        ).json()
    assert body["providers"] == byok_models.model_catalog()


_SUPERVISOR_KEY = "sk-gemini-supervisor-987654"
_MIXED = {
    "X-LLM-Supervisor-Provider": "gemini",
    "X-LLM-Supervisor-API-Key": _SUPERVISOR_KEY,
    "X-LLM-Supervisor-Model": "gemini/gemini-3.1-pro-preview",
}


def _mixed_credential() -> credentials.ByokCredential:
    cred = credentials.credential_from_headers(_headers(**_MIXED))
    assert cred is not None
    return cred


def test_a_supervisor_on_another_provider_carries_its_own_key() -> None:
    cred = _mixed_credential()
    assert (cred.provider, cred.api_key) == ("deepseek", _KEY)
    assert cred.supervisor_provider == "gemini"
    assert cred.supervisor_api_key == _SUPERVISOR_KEY
    assert cred.keys_by_model() == {
        "deepseek/deepseek-flash": _KEY,
        "gemini/gemini-3.1-pro-preview": _SUPERVISOR_KEY,
    }


@pytest.mark.parametrize("missing", list(_MIXED)[:2])
def test_supervisor_provider_and_key_travel_together(missing: str) -> None:
    extra = {k: v for k, v in _MIXED.items() if k != missing}
    with pytest.raises(credentials.ByokRequestError, match="together"):
        credentials.credential_from_headers(_headers(**extra))


def test_supervisor_model_must_belong_to_its_own_provider() -> None:
    extra = {**_MIXED, "X-LLM-Supervisor-Model": "deepseek/deepseek-v4-pro"}
    with pytest.raises(credentials.ByokRequestError):
        credentials.credential_from_headers(_headers(**extra))


def test_mixed_credential_round_trips_through_storage(
    byok_secret: None,
) -> None:
    run = seed_run("goal", profile="express")
    cred = _mixed_credential()
    credentials.store_run_credential(run.id, run.client_id, cred)
    assert credentials.get_run_credential(run.id) == cred


async def test_validation_probes_each_model_with_its_own_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[object, object]] = []

    async def fake_acompletion(**kwargs: object) -> None:
        seen.append((kwargs["model"], kwargs["api_key"]))

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    await credentials.validate_byok_credential(_mixed_credential())
    assert seen == [
        ("deepseek/deepseek-flash", _KEY),
        ("gemini/gemini-3.1-pro-preview", _SUPERVISOR_KEY),
    ]


def test_every_offered_model_thinks() -> None:
    from co_scientist.llm import model_reasons

    offered = [m for p in byok_models.model_catalog().values() for m in p]
    assert [m for m in offered if not model_reasons(m)] == []


def test_openrouter_keys_can_choose_the_free_default_route() -> None:
    from app.config import DEFAULT_MODEL

    assert DEFAULT_MODEL in byok_models.provider_models("openrouter")
