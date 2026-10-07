from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import sqlite3
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app import byok_models
from app.config import byok_default_model, settings
from app.llm_scope import budgeted

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-LLM-API-Key"
PROVIDER_HEADER = "X-LLM-Provider"
SUPERVISOR_API_KEY_HEADER = "X-LLM-Supervisor-API-Key"
SUPERVISOR_PROVIDER_HEADER = "X-LLM-Supervisor-Provider"

# Bound credential validation so a dead provider cannot hang run creation.
_VALIDATION_TIMEOUT_SECONDS = 30.0


class ByokRequestError(ValueError):
    """Malformed provider/key pairs are request errors."""


class ByokValidationError(Exception):
    """Rejected or unreachable provider credentials are refused before run
    creation.
    """


class ByokNotConfiguredError(RuntimeError):
    """Missing encryption support refuses credential-bearing requests."""


@dataclass(frozen=True)
class ByokCredential:
    """Plaintext keys exist only in scoped memory, never endpoint responses
    or checkpointed state.
    """

    provider: str
    api_key: str
    model: str
    supervisor_model: str | None = None
    # None means the supervisor shares the worker's provider and key.
    supervisor_provider: str | None = None
    supervisor_api_key: str | None = None

    @property
    def models(self) -> tuple[str, ...]:
        if self.supervisor_model in (None, self.model):
            return (self.model,)
        return (self.model, str(self.supervisor_model))

    @property
    def secrets(self) -> tuple[str, ...]:
        keys = (self.api_key, self.supervisor_api_key)
        return tuple(dict.fromkeys(key for key in keys if key))

    def keys_by_model(self) -> dict[str, str]:
        """Provider-qualified model strings identify which key pays for a
        call, so a mixed-provider run needs no per-call plumbing.
        """
        keys = {self.model: self.api_key}
        if self.supervisor_model:
            keys[self.supervisor_model] = self.supervisor_api_key or self.api_key
        return keys


def _fernet() -> Fernet:
    """HKDF derives a purpose-bound Fernet key from any nonempty deployment
    secret.
    """
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    secret = settings.byok_encryption_key
    if not secret:
        raise ByokNotConfiguredError("bring-your-own-key support requires BYOK_ENCRYPTION_KEY")
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"coscientist-byok-v1",
        info=b"fernet key",
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(token: str) -> str:
    """Corrupt or rotated ciphertext fails loudly rather than silently
    billing the deployment's credential.
    """
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError(
            "stored BYOK credential cannot be decrypted; the encryption key may have rotated"
        ) from exc


def idempotency_secret_fingerprint(api_key: str) -> str:
    """A purpose-separated keyed digest identifies receipt intent without
    persisting plaintext credentials.
    """
    secret = settings.byok_encryption_key
    if not secret:
        raise ByokNotConfiguredError("bring-your-own-key support requires BYOK_ENCRYPTION_KEY")
    return hmac.new(
        secret.encode("utf-8"),
        b"co-scientist/run-create-idempotency/v1\0" + api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def run_creation_request_digest(
    request_fields: Mapping[str, Any],
    *,
    api_key: str | None = None,
    provider: str | None = None,
    supervisor_api_key: str | None = None,
    supervisor_provider: str | None = None,
) -> str:
    key = (api_key or "").strip()
    supervisor_key = (supervisor_api_key or "").strip()
    fingerprint = idempotency_secret_fingerprint(key) if key else None
    canonical = json.dumps(
        {
            "request": request_fields,
            "byok_provider": (provider or "").strip().lower() if key else None,
            "byok_secret_fingerprint": fingerprint,
            "byok_supervisor_provider": (supervisor_provider or "").strip().lower()
            if supervisor_key
            else None,
            "byok_supervisor_fingerprint": (
                idempotency_secret_fingerprint(supervisor_key) if supervisor_key else None
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest_input = b"co-scientist/run-create/v1\0" + canonical
    return hashlib.sha256(digest_input).hexdigest()


def _supervisor_route(
    headers: Mapping[str, str], provider: str, api_key: str
) -> tuple[str, str | None, str | None]:
    """A supervisor on another provider needs both its provider and its own
    key; one without the other is a malformed request. Returns the provider
    its model resolves against plus the credential fields to store.
    """
    sup_provider = (headers.get(SUPERVISOR_PROVIDER_HEADER) or "").strip()
    sup_key = (headers.get(SUPERVISOR_API_KEY_HEADER) or "").strip()
    if bool(sup_provider) != bool(sup_key):
        raise ByokRequestError(
            f"{SUPERVISOR_PROVIDER_HEADER} and {SUPERVISOR_API_KEY_HEADER} must be sent together"
        )
    sup_provider = sup_provider.lower()
    if not sup_provider or (sup_provider == provider and sup_key == api_key):
        return provider, None, None
    if byok_default_model(sup_provider) is None:
        raise ByokRequestError(f"unsupported provider: {sup_provider}")
    return sup_provider, sup_provider, sup_key


def credential_from_headers(
    headers: Mapping[str, str],
) -> ByokCredential | None:
    api_key = (headers.get(API_KEY_HEADER) or "").strip()
    if not api_key:
        return None
    provider = (headers.get(PROVIDER_HEADER) or "").strip().lower()
    if not provider:
        raise ByokRequestError(f"the {API_KEY_HEADER} header requires {PROVIDER_HEADER}")
    if byok_default_model(provider) is None:
        raise ByokRequestError(f"unsupported provider: {provider}")
    supervisor_route, sup_provider, sup_key = _supervisor_route(headers, provider, api_key)
    try:
        model = byok_models.resolve_model_choice(
            provider, headers.get(byok_models.WORKER_MODEL_HEADER)
        )
        supervisor = byok_models.resolve_model_choice(
            supervisor_route, headers.get(byok_models.SUPERVISOR_MODEL_HEADER)
        )
    except byok_models.ByokModelError as exc:
        raise ByokRequestError(str(exc)) from exc
    return ByokCredential(
        provider=provider,
        api_key=api_key,
        model=model,
        supervisor_model=supervisor,
        supervisor_provider=sup_provider,
        supervisor_api_key=sup_key,
    )


def store_run_credential(
    run_id: str,
    client_id: str,
    credential: ByokCredential,
    db_path: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    from app.store.db import _now, _use_conn

    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO run_credentials (run_id, client_id, provider, "
            "model, supervisor_model, encrypted_key, created_at, "
            "supervisor_provider, encrypted_supervisor_key) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET client_id=excluded."
            "client_id, provider=excluded.provider, "
            "model=excluded.model, "
            "supervisor_model=excluded.supervisor_model, "
            "encrypted_key=excluded.encrypted_key, "
            "supervisor_provider=excluded.supervisor_provider, "
            "encrypted_supervisor_key=excluded.encrypted_supervisor_key",
            (
                run_id,
                client_id,
                credential.provider,
                credential.model,
                credential.supervisor_model,
                encrypt_api_key(credential.api_key),
                _now(),
                credential.supervisor_provider,
                encrypt_api_key(credential.supervisor_api_key)
                if credential.supervisor_api_key
                else None,
            ),
        )


def get_run_credential(run_id: str, db_path: str | None = None) -> ByokCredential | None:
    from app.store.db import connect

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT provider, model, supervisor_model, encrypted_key, "
            "supervisor_provider, encrypted_supervisor_key "
            "FROM run_credentials "
            "WHERE run_id=?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return ByokCredential(
        provider=row["provider"],
        api_key=decrypt_api_key(row["encrypted_key"]),
        model=row["model"],
        supervisor_model=row["supervisor_model"],
        supervisor_provider=row["supervisor_provider"],
        supervisor_api_key=decrypt_api_key(row["encrypted_supervisor_key"])
        if row["encrypted_supervisor_key"]
        else None,
    )


async def _acompletion(**kwargs: Any) -> object:
    """Forwarded parameters retain Any because LiteLLM's heterogeneous
    completion signature cannot be represented by object.
    """
    from app import llm_request

    return await llm_request.acompletion(**kwargs)


@budgeted("credential_probe")
async def validate_byok_credential(credential: ByokCredential) -> None:
    """Credential validation is provider I/O and must complete outside
    SQLite write transactions.
    """
    from litellm.exceptions import AuthenticationError

    try:
        with scoped_byok(credential):
            for model, api_key in credential.keys_by_model().items():
                await _acompletion(
                    model=model,
                    api_key=api_key,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    temperature=0,
                    timeout=_VALIDATION_TIMEOUT_SECONDS,
                    drop_params=True,
                )
    except AuthenticationError as exc:
        raise ByokValidationError("the provider rejected the API key (invalid or expired)") from exc
    except ByokValidationError:
        raise
    except Exception as exc:
        # Provider error details must never echo the submitted credential.
        raise ByokValidationError(
            f"the API key could not be verified with the provider: {_redact(str(exc), credential)}"
        ) from exc


_current_byok: ContextVar[ByokCredential | None] = ContextVar("cosci_byok", default=None)


def current_byok() -> ByokCredential | None:
    return _current_byok.get()


def _redact(text: str, credential: ByokCredential) -> str:
    for secret in credential.secrets:
        text = text.replace(secret, "[REDACTED]")
    return text


def redact_byok_text(text: str) -> str:
    credential = current_byok()
    return text if credential is None else _redact(text, credential)


@contextlib.contextmanager
def scoped_byok(
    credential: ByokCredential | None,
) -> Iterator[None]:
    if credential is None:
        yield
        return
    token = _current_byok.set(credential)
    try:
        yield
    finally:
        _current_byok.reset(token)


def byok_model_and_key(model: str) -> tuple[str, str | None]:
    """Scoped credentials override model and key for this execution only,
    without mutating deployment defaults.
    """
    credential = current_byok()
    if credential is None:
        return model, None
    return credential.model, credential.api_key


def _redact_log_details(record: logging.LogRecord) -> None:
    if record.exc_info:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    for field in ("exc_text", "stack_info"):
        value = getattr(record, field)
        if value:
            setattr(record, field, redact_byok_text(value))


class ByokRedactionFilter(logging.Filter):
    """Provider libraries can embed keys in errors; stdout and persistence
    both need scoped credential redaction.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if current_byok() is None:
            return True
        try:
            message = record.getMessage()
            redacted = redact_byok_text(message)
            if redacted != message:
                record.msg = redacted
                record.args = None
            _redact_log_details(record)
        except Exception:
            # Credential redaction must never break logging itself.
            return True
        return True
