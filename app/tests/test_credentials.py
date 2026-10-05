from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from starlette.datastructures import Headers

from app import credentials
from app.config import settings
from app.store import db
from app.store.models import RunRow
from tests._store_helpers import seed_run

_SECRET = "unit-test-byok-secret"
_KEY = "sk-test-1234567890"
_SECOND_KEY = "sk-second-0987654321"


@pytest.fixture
def byok_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "byok_encryption_key", _SECRET)
    return _SECRET


def _make_run(goal: str = "goal") -> RunRow:
    return seed_run(goal, profile="express")


def test_encrypt_decrypt_round_trip(byok_secret: str) -> None:
    token = credentials.encrypt_api_key(_KEY)
    assert token != _KEY
    assert credentials.decrypt_api_key(token) == _KEY


def test_decrypt_rejects_a_tampered_token(byok_secret: str) -> None:
    token = credentials.encrypt_api_key(_KEY)
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    with pytest.raises(RuntimeError):
        credentials.decrypt_api_key(tampered)


def test_decrypt_with_a_different_secret_fails(
    byok_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = credentials.encrypt_api_key(_KEY)
    monkeypatch.setattr(settings, "byok_encryption_key", "another-secret")
    with pytest.raises(RuntimeError):
        credentials.decrypt_api_key(token)


def test_credential_from_headers_maps_provider_model(
    byok_secret: str,
) -> None:
    request = Headers({"X-LLM-API-Key": _KEY, "X-LLM-Provider": "deepseek"})
    cred = credentials.credential_from_headers(request)
    assert cred is not None
    assert cred.provider == "deepseek"
    assert cred.api_key == _KEY
    assert cred.model == "deepseek/deepseek-flash"


def test_credential_from_headers_absent() -> None:
    assert credentials.credential_from_headers(Headers({})) is None


def test_credential_from_headers_key_without_provider(
    byok_secret: str,
) -> None:
    request = Headers({"X-LLM-API-Key": _KEY})
    with pytest.raises(credentials.ByokRequestError):
        credentials.credential_from_headers(request)


def test_credential_from_headers_unknown_provider(
    byok_secret: str,
) -> None:
    request = Headers({"X-LLM-API-Key": _KEY, "X-LLM-Provider": "skynet"})
    with pytest.raises(credentials.ByokRequestError):
        credentials.credential_from_headers(request)


def test_store_and_load_run_credential(byok_secret: str) -> None:
    run = _make_run()
    cred = credentials.ByokCredential(
        provider="deepseek", api_key=_KEY, model="deepseek/deepseek-v4-flash"
    )
    credentials.store_run_credential(run.id, run.client_id, cred)
    loaded = credentials.get_run_credential(run.id)
    assert loaded == cred


def test_run_credential_deleted_with_the_run(byok_secret: str) -> None:
    run = _make_run()
    cred = credentials.ByokCredential(
        provider="openai", api_key=_KEY, model="openai/gpt-4o"
    )
    credentials.store_run_credential(run.id, run.client_id, cred)
    with db.connect() as conn:
        conn.execute("DELETE FROM runs WHERE id=?", (run.id,))
    assert credentials.get_run_credential(run.id) is None


def test_stored_token_is_not_plaintext(byok_secret: str) -> None:
    run = _make_run()
    cred = credentials.ByokCredential(
        provider="openai", api_key=_KEY, model="openai/gpt-4o"
    )
    credentials.store_run_credential(run.id, run.client_id, cred)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT encrypted_key FROM run_credentials WHERE run_id=?",
            (run.id,),
        ).fetchone()
    assert row is not None
    assert _KEY not in row["encrypted_key"]


async def test_validation_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    cred = credentials.ByokCredential(
        provider="deepseek", api_key=_KEY, model="deepseek/deepseek-v4-flash"
    )
    await credentials.validate_byok_credential(cred)
    assert seen["api_key"] == _KEY
    assert seen["model"] == "deepseek/deepseek-v4-flash"
    assert seen["max_tokens"] == 1


async def test_validation_rejected_key_surfaces_as_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from litellm.exceptions import AuthenticationError

    async def fake_acompletion(**kwargs: object) -> None:
        raise AuthenticationError(
            "Invalid API key",
            llm_provider="deepseek",
            model="deepseek/deepseek-v4-flash",
        )

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    cred = credentials.ByokCredential(
        provider="deepseek", api_key=_KEY, model="deepseek/deepseek-v4-flash"
    )
    with pytest.raises(credentials.ByokValidationError) as exc_info:
        await credentials.validate_byok_credential(cred)
    message = str(exc_info.value)
    assert "rejected" in message
    assert _KEY not in message


async def test_validation_error_never_echoes_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> None:
        raise RuntimeError(f"provider exploded while using {_KEY}")

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    cred = credentials.ByokCredential(
        provider="deepseek", api_key=_KEY, model="deepseek/deepseek-v4-flash"
    )
    with pytest.raises(credentials.ByokValidationError) as exc_info:
        await credentials.validate_byok_credential(cred)
    assert _KEY not in str(exc_info.value)


def test_byok_model_and_key_prefers_scoped_credential(
    byok_secret: str,
) -> None:
    cred = credentials.ByokCredential(
        provider="openai", api_key=_KEY, model="openai/gpt-4o"
    )
    assert credentials.byok_model_and_key("chat-model") == (
        "chat-model",
        None,
    )
    with credentials.scoped_byok(cred):
        assert credentials.byok_model_and_key("chat-model") == (
            "openai/gpt-4o",
            _KEY,
        )
    assert credentials.byok_model_and_key("chat-model") == (
        "chat-model",
        None,
    )


def test_redaction_filter_scrubs_scoped_key(
    byok_secret: str,
) -> None:
    cred = credentials.ByokCredential(
        provider="openai", api_key=_KEY, model="openai/gpt-4o"
    )
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, f"call failed key={_KEY}", (), None
    )
    redactor = credentials.ByokRedactionFilter()
    with credentials.scoped_byok(cred):
        assert redactor.filter(record)
    assert _KEY not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def _mixed() -> credentials.ByokCredential:
    return credentials.ByokCredential(
        provider="openai",
        api_key=_KEY,
        model="openai/gpt-6.1-sol",
        supervisor_model="gemini/gemini-3.8-flash",
        supervisor_provider="gemini",
        supervisor_api_key=_SECOND_KEY,
    )


def test_redaction_scrubs_both_keys(byok_secret: str) -> None:
    message = f"{_KEY} then {_SECOND_KEY}"
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, message, (), None
    )
    with credentials.scoped_byok(_mixed()):
        assert credentials.ByokRedactionFilter().filter(record)
    assert record.getMessage() == "[REDACTED] then [REDACTED]"


async def test_validation_error_never_echoes_the_supervisor_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> None:
        raise RuntimeError(f"exploded using {kwargs['api_key']}")

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    with pytest.raises(credentials.ByokValidationError) as exc_info:
        await credentials.validate_byok_credential(_mixed())
    assert _KEY not in str(exc_info.value)
    assert _SECOND_KEY not in str(exc_info.value)


def test_idempotency_digest_covers_the_supervisor_credential(
    byok_secret: str,
) -> None:
    def digest(**extra: str) -> str:
        return credentials.run_creation_request_digest(
            {"goal": "g"}, api_key=_KEY, provider="openai", **extra
        )

    sup = digest(supervisor_api_key=_SECOND_KEY, supervisor_provider="gemini")
    assert sup != digest()
    assert sup != digest(
        supervisor_api_key="sk-other", supervisor_provider="gemini"
    )
    assert sup != digest(
        supervisor_api_key=_SECOND_KEY, supervisor_provider="anthropic"
    )


def test_existing_database_gains_the_supervisor_columns(
    byok_secret: str, tmp_path: Path
) -> None:
    path = str(tmp_path / "old.db")
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE run_credentials (run_id TEXT PRIMARY KEY, client_id "
        "TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, "
        "supervisor_model TEXT, encrypted_key TEXT NOT NULL, "
        "created_at REAL NOT NULL)"
    )
    legacy.close()

    run = seed_run("goal", profile="express", db_path=path)
    credentials.store_run_credential(
        run.id, run.client_id, _mixed(), db_path=path
    )
    assert credentials.get_run_credential(run.id, db_path=path) == _mixed()
