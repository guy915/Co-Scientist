"""Bring-your-own-key (BYOK) credentials: transport, crypto, storage.

A scientist may supply their own provider API key, sent as request
headers (never query parameters -- URLs leak into history, logs, and
referrers). This module owns the whole life of that key:

- Transport: ``credential_from_headers`` reads ``X-LLM-API-Key`` /
  ``X-LLM-Provider`` and pairs the key with its provider's default
  model (``config.BYOK_PROVIDER_DEFAULT_MODELS``).
- Validation: ``validate_byok_credential`` proves the pair with a cheap
  one-token completion BEFORE a run accepts it, so a rejected or
  expired key surfaces at creation time, not mid-run.
- Storage: the durable task model decides this -- a run's tasks lease
  independently and may execute later or elsewhere than the request
  that created the run -- so the key is persisted for the run's
  lifetime, encrypted at rest (Fernet, key material derived from
  ``settings.byok_encryption_key``) in ``run_credentials``, scoped to
  the owning client, and cascaded away when the run is deleted.
- Scoping: ``scoped_byok`` binds a credential to the current (async)
  execution context so the app's own LLM calls (interview, Q&A, title,
  safety, claim verification) resolve it without threading it through
  every signature. Never a process global: each durable task scopes its
  own run's credential.

The plaintext key is never logged (see ``ByokRedactionFilter``), never
returned by any endpoint, and never placed in checkpointed state.
"""

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

from app.config import byok_default_model, settings

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-LLM-API-Key"
PROVIDER_HEADER = "X-LLM-Provider"

# Wall clock for the cheap validation completion. Generous enough for a
# cold provider round trip, tight enough that run creation cannot hang
# on a dead endpoint.
_VALIDATION_TIMEOUT_SECONDS = 30.0


class ByokRequestError(ValueError):
    """A malformed BYOK request (missing/unknown provider). Maps to 400."""


class ByokValidationError(Exception):
    """The provider rejected the key or could not be reached. Maps to 400."""


class ByokNotConfiguredError(RuntimeError):
    """This deployment has no BYOK encryption secret configured. 503."""


@dataclass(frozen=True)
class ByokCredential:
    """One validated bring-your-own-key credential.

    Attributes:
        provider: Provider id, one of ``config.PROVIDER_CREDENTIAL_ENV``.
        api_key: The provider API key (plaintext only in memory).
        model: The litellm model this credential runs (the provider's
            default-model table entry, recorded at validation time).
    """

    provider: str
    api_key: str
    model: str


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    """Return a Fernet cipher keyed from the deployment's BYOK secret.

    The Fernet key is derived (HKDF-SHA256) from the configured secret so
    operators may set any non-empty string; a fixed salt/info pair binds
    the derivation to this one purpose.

    Raises:
        ByokNotConfiguredError: When ``byok_encryption_key`` is unset.
    """
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    secret = settings.byok_encryption_key
    if not secret:
        raise ByokNotConfiguredError(
            "bring-your-own-key support requires BYOK_ENCRYPTION_KEY"
        )
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"coscientist-byok-v1",
        info=b"fernet key",
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key for storage at rest.

    Args:
        api_key: The plaintext provider key.

    Returns:
        The Fernet token (URL-safe string) to persist.
    """
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(token: str) -> str:
    """Decrypt a stored API key token.

    Args:
        token: The persisted Fernet token.

    Returns:
        The plaintext provider key.

    Raises:
        RuntimeError: When the token is corrupt or was sealed under a
            different secret (e.g. after a rotation). Failing loudly
            beats silently billing the deployment's credential.
    """
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError(
            "stored BYOK credential cannot be decrypted; the encryption "
            "key may have rotated"
        ) from exc


def idempotency_secret_fingerprint(api_key: str) -> str:
    """HMAC a BYOK secret for a run-create receipt without storing it.

    The domain prefix keeps this fingerprint separate from other uses of
    the BYOK encryption secret.
    """
    secret = settings.byok_encryption_key
    if not secret:
        raise ByokNotConfiguredError(
            "bring-your-own-key support requires BYOK_ENCRYPTION_KEY"
        )
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
) -> str:
    """Digest parsed run intent and a keyed fingerprint of an explicit key."""
    key = (api_key or "").strip()
    fingerprint = idempotency_secret_fingerprint(key) if key else None
    canonical = json.dumps(
        {
            "request": request_fields,
            "byok_provider": (provider or "").strip().lower() if key else None,
            "byok_secret_fingerprint": fingerprint,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest_input = b"co-scientist/run-create/v1\0" + canonical
    return hashlib.sha256(digest_input).hexdigest()


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def credential_from_headers(
    headers: Mapping[str, str],
) -> ByokCredential | None:
    """Parse the BYOK headers into a credential, when a key is sent.

    Args:
        headers: Request headers (case-insensitive mapping).

    Returns:
        The credential with the provider's default model resolved, or
        None when no key was sent.

    Raises:
        ByokRequestError: A key without a provider, or a provider the
            default-model table does not know.
    """
    api_key = (headers.get(API_KEY_HEADER) or "").strip()
    if not api_key:
        return None
    provider = (headers.get(PROVIDER_HEADER) or "").strip().lower()
    if not provider:
        raise ByokRequestError(
            f"the {API_KEY_HEADER} header requires {PROVIDER_HEADER}"
        )
    model = byok_default_model(provider)
    if model is None:
        raise ByokRequestError(f"unsupported provider: {provider}")
    return ByokCredential(provider=provider, api_key=api_key, model=model)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def store_run_credential(
    run_id: str,
    client_id: str,
    credential: ByokCredential,
    db_path: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist a run's encrypted credential, replacing any prior one.

    Args:
        run_id: The run that owns the credential.
        client_id: The owning client/researcher identity.
        credential: The validated credential to store.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to join an existing transaction.
    """
    from app.store.db import _now, _use_conn

    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO run_credentials (run_id, client_id, provider, "
            "model, encrypted_key, created_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET client_id=excluded."
            "client_id, provider=excluded.provider, "
            "model=excluded.model, encrypted_key=excluded.encrypted_key",
            (
                run_id,
                client_id,
                credential.provider,
                credential.model,
                encrypt_api_key(credential.api_key),
                _now(),
            ),
        )


def get_run_credential(
    run_id: str, db_path: str | None = None
) -> ByokCredential | None:
    """Return a run's decrypted credential, or None when it has none.

    Args:
        run_id: The run whose credential is requested.
        db_path: Optional override for the SQLite database path.

    Returns:
        The decrypted credential, or None for a non-BYOK run.
    """
    from app.store.db import connect

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT provider, model, encrypted_key FROM run_credentials "
            "WHERE run_id=?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return ByokCredential(
        provider=row["provider"],
        api_key=decrypt_api_key(row["encrypted_key"]),
        model=row["model"],
    )


def delete_run_credential(run_id: str, db_path: str | None = None) -> None:
    """Delete a run's stored credential (idempotent).

    Args:
        run_id: The run whose credential to remove.
        db_path: Optional override for the SQLite database path.
    """
    from app.store.db import connect

    with connect(db_path) as conn:
        conn.execute("DELETE FROM run_credentials WHERE run_id=?", (run_id,))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def _acompletion(**kwargs: Any) -> object:
    """Indirection over litellm.acompletion so tests can monkeypatch.

    Typed ``Any`` rather than ``object`` because these are forwarded
    verbatim to a signature of ~40 specifically-typed parameters, which a
    checker resolving that signature reads as one type error per parameter.
    """
    from app import llm_request

    return await llm_request.acompletion(**kwargs)


def _sanitized_detail(credential: ByokCredential, exc: Exception) -> str:
    """Return an error detail that can never echo the key back."""
    return str(exc).replace(credential.api_key, "[REDACTED]")


async def validate_byok_credential(credential: ByokCredential) -> None:
    """Prove a credential with a cheap one-token completion.

    Must run OUTSIDE any database transaction: it is a network call, and
    the store's single writer must not be held across it.

    Args:
        credential: The provider/key/model pair to prove.

    Raises:
        ByokValidationError: When the provider rejects the key (worded
            exactly as a rejection) or the call cannot complete.
    """
    from litellm.exceptions import AuthenticationError

    try:
        with scoped_byok(credential):
            await _acompletion(
                model=credential.model,
                api_key=credential.api_key,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
                timeout=_VALIDATION_TIMEOUT_SECONDS,
                drop_params=True,
            )
    except AuthenticationError as exc:
        raise ByokValidationError(
            "the provider rejected the API key (invalid or expired)"
        ) from exc
    except ByokValidationError:
        raise
    except Exception as exc:
        raise ByokValidationError(
            "the API key could not be verified with the provider: "
            f"{_sanitized_detail(credential, exc)}"
        ) from exc


# ---------------------------------------------------------------------------
# Request/task scoping
# ---------------------------------------------------------------------------

_current_byok: ContextVar[ByokCredential | None] = ContextVar(
    "cosci_byok", default=None
)


def current_byok() -> ByokCredential | None:
    """Return the credential scoped to the current context, if any."""
    return _current_byok.get()


def redact_byok_text(text: str) -> str:
    """Replace the current run's exact key in diagnostic text."""
    credential = current_byok()
    if credential is None or not credential.api_key:
        return text
    return text.replace(credential.api_key, "[REDACTED]")


@contextlib.contextmanager
def scoped_byok(
    credential: ByokCredential | None,
) -> Iterator[None]:
    """Scope a BYOK credential to the current (async) execution context.

    Args:
        credential: The run's credential, or None for a no-op scope so
            callers can pass an optional credential straight through.

    Yields:
        None.
    """
    if credential is None:
        yield
        return
    token = _current_byok.set(credential)
    try:
        yield
    finally:
        _current_byok.reset(token)


def byok_model_and_key(model: str) -> tuple[str, str | None]:
    """Resolve the effective (model, api_key) for an app LLM call.

    With a scoped BYOK credential the call uses the credential's model
    and key -- overriding the deployment model and credential for this
    run only; without one the deployment model is kept and litellm
    resolves the deployment's environment credential as usual.

    Args:
        model: The deployment model the call site would otherwise use.

    Returns:
        ``(byok_model, byok_key)`` when a credential is scoped, else
        ``(model, None)``.
    """
    from app.execution_policy import effective_execution_model

    campaign_model = effective_execution_model(None)
    if campaign_model is not None:
        return campaign_model, None
    credential = current_byok()
    if credential is None:
        return model, None
    return credential.model, credential.api_key


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------


def _redact_log_details(record: logging.LogRecord) -> None:
    """Redact formatted traceback and stack text on a log record."""
    if record.exc_info:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    for field in ("exc_text", "stack_info"):
        value = getattr(record, field)
        if value:
            setattr(record, field, redact_byok_text(value))


class ByokRedactionFilter(logging.Filter):
    """Scrubs a scoped BYOK key out of any record that carries it.

    Defense in depth: no code path logs the key deliberately, but a
    provider error message could embed it, and records from libraries
    are not ours to control. Attached to both the stdout handler and the
    persistent capture pipeline (see ``logging_setup``); when no
    credential is scoped the filter is a cheap no-op.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the scoped key from the record, keeping the record."""
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
            # Redaction must never break logging itself.
            return True
        return True
