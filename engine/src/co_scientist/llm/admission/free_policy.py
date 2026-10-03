"""Provider credentials and the verified free-model admission policy."""

import asyncio
import contextlib
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import litellm

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm.profile import promotional_free_route

_byok_api_key: ContextVar[str | None] = ContextVar("byok_api_key", default=None)


def current_api_key() -> str | None:
    """Return the BYOK key scoped to the current task, if any.

    Returns:
        The key set by an enclosing ``scoped_api_key`` block, else None.
    """
    return _byok_api_key.get()


@contextlib.contextmanager
def scoped_api_key(api_key: str | None) -> Iterator[None]:
    """Scope a BYOK key to the current asyncio task for the block.

    Args:
        api_key: The provider key every completion inside the block
            should use, or None for a no-op scope (callers can pass an
            optional credential straight through).

    Yields:
        None.
    """
    if api_key is None:
        yield
        return
    token = _byok_api_key.set(api_key)
    try:
        yield
    finally:
        _byok_api_key.reset(token)


FREE_MODE_ENV = "COSCIENTIST_REQUIRE_FREE_MODELS"
_API_BASE = "https://openrouter.ai/api/v1"
_REQUEST_FIELDS = {
    "model",
    "messages",
    "max_tokens",
    "temperature",
    "drop_params",
    "timeout",
    "api_key",
    "api_base",
    "extra_body",
    "response_format",
    "reasoning_effort",
    "tools",
    "tool_choice",
    "stream",
    "stream_options",
}
_BODY_FIELDS = {"provider", "models", "reasoning"}
_campaign_mode: ContextVar[bool] = ContextVar("campaign_mode", default=False)


CATALOG_URL = "https://openrouter.ai/api/v1/models"
CATALOG_TTL_SECONDS = 60


class CatalogReader:
    """A metadata source with one cache shared across worker event loops.

    Inject the synchronous loader when constructing a reader. Each reader
    owns its snapshot and threading lock; replacing one cannot carry prices
    from its predecessor into the new source. Loaders run off the event loop.
    """

    def __init__(
        self, loader: Callable[[], dict[str, Any]] | None = None
    ) -> None:
        """Use OpenRouter's public metadata unless a loader is supplied."""
        self._loader = loader if loader is not None else _fetch_catalog
        self._lock = threading.Lock()
        self._snapshot: tuple[float, dict[str, Any]] | None = None

    def read(self) -> dict[str, Any]:
        """Fetch fresh metadata, withholding an expired snapshot on failure."""
        with self._lock:
            if (
                self._snapshot is not None
                and time.monotonic() < self._snapshot[0]
            ):
                return self._snapshot[1]
            self._snapshot = None
            catalog = self._loader()
            self._snapshot = (time.monotonic() + CATALOG_TTL_SECONDS, catalog)
            return catalog

    def invalidate(self) -> None:
        """Require the next read to refresh metadata from this source."""
        with self._lock:
            self._snapshot = None


def _fetch_catalog() -> dict[str, Any]:
    try:
        response = httpx.get(CATALOG_URL, timeout=15, trust_env=False)
        response.raise_for_status()
        rows = response.json()["data"]
        catalog = {row["id"]: row for row in rows}
        if not rows or len(catalog) != len(rows):
            raise ValueError("empty or duplicate model entries")
        return catalog
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise FreeModelEligibilityError(
            "zero-cost catalog unavailable or invalid"
        ) from exc


# Installed once for all worker threads, like the completion backend. A
# ContextVar would make a source installed on the API loop invisible to them.
_reader = CatalogReader()


def current_catalog() -> dict[str, Any]:
    """Read the installed source off the event loop; never use stale prices."""
    return _reader.read()


def install_catalog_reader(reader: CatalogReader) -> CatalogReader:
    """Install a process-wide reader and return its predecessor."""
    global _reader
    previous, _reader = _reader, reader
    return previous


@contextmanager
def using_catalog_reader(reader: CatalogReader) -> Iterator[None]:
    """Use a source for a scope, restoring the prior reader on any exit."""
    previous = install_catalog_reader(reader)
    try:
        yield
    finally:
        install_catalog_reader(previous)


def invalidate_catalog() -> None:
    """Require the installed reader to fetch fresh metadata next time."""
    _reader.invalidate()


def _is_zero(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        number = Decimal(value)
        return number.is_finite() and number == 0
    except InvalidOperation:
        return False


def verify_model(model: str, catalog: dict[str, Any]) -> None:
    """Require an exact catalog entry and evidence covering text inference."""
    row = catalog.get(model)
    if not isinstance(row, dict) or model.startswith(("openrouter/", "~")):
        raise FreeModelEligibilityError(
            "zero-cost model is not an explicit catalog route"
        )
    _verify_expiration(row)
    architecture = row.get("architecture", {})
    if not isinstance(architecture, dict):
        raise FreeModelEligibilityError(
            "zero-cost route architecture is invalid"
        )
    inputs = architecture.get("input_modalities")
    if not isinstance(inputs, list) or "text" not in inputs:
        raise FreeModelEligibilityError("zero-cost route cannot accept text")
    if architecture.get("output_modalities") != ["text"]:
        raise FreeModelEligibilityError(
            "zero-cost route must produce only text"
        )
    _verify_pricing(model, row.get("pricing"))


def _utc_today() -> date:
    """Return the current UTC calendar date for catalog expiration checks."""
    return datetime.now(timezone.utc).date()


def _verify_expiration(row: dict[str, Any]) -> None:
    """Reject malformed or elapsed catalog expiry dates, when supplied."""
    if "expiration_date" not in row or row["expiration_date"] is None:
        return
    value = row["expiration_date"]
    try:
        expiration = (
            date.fromisoformat(value) if isinstance(value, str) else None
        )
    except ValueError:
        expiration = None
    if expiration is None or expiration.isoformat() != value:
        raise FreeModelEligibilityError(
            "zero-cost route expiration date is invalid"
        )
    # OpenRouter publishes dates without times; treat the named UTC date as
    # the last valid day, expiring the route once the next UTC day begins.
    if expiration < _utc_today():
        raise FreeModelEligibilityError(
            "zero-cost route expiration date has elapsed"
        )


def _verify_pricing(model: str, pricing: Any) -> None:
    if not isinstance(pricing, dict):
        raise FreeModelEligibilityError("zero-cost pricing is missing")
    # Free-suffixed variants and the explicitly admitted promotion may omit
    # ancillary rates. Other promotions must list them; absent rates are not
    # evidence of a zero price.
    ancillary = {
        "request",
        "internal_reasoning",
        "input_cache_read",
        "input_cache_write",
    }
    required = {"prompt", "completion"} | (
        set()
        if model.endswith(":free") or promotional_free_route(model)
        else ancillary
    )
    if not required <= pricing.keys():
        raise FreeModelEligibilityError("zero-cost pricing is incomplete")
    if pricing.get("overrides", []) != []:
        raise FreeModelEligibilityError(
            "zero-cost conditional pricing is not qualified"
        )
    rates = dict(pricing)
    rates.pop("overrides", None)
    if not all(_is_zero(value) for value in rates.values()):
        raise FreeModelEligibilityError(
            "zero-cost route has paid or invalid pricing"
        )


def campaign_free_mode() -> bool:
    """Return whether every campaign request requires zero-cost admission."""
    configured = os.getenv(FREE_MODE_ENV, "0").strip().lower()
    if configured not in {"0", "false", "", "1", "true"}:
        raise FreeModelEligibilityError("zero-cost mode setting is invalid")
    return _campaign_mode.get() or configured in {"1", "true"}


@contextlib.contextmanager
def scoped_campaign_mode(enabled: bool) -> Iterator[None]:
    """Scope campaign free-model admission to the current task.

    The scope is monotone: nested callers can enable campaign mode but cannot
    weaken an already-active campaign scope.
    """
    token = _campaign_mode.set(_campaign_mode.get() or enabled)
    try:
        yield
    finally:
        _campaign_mode.reset(token)


def _requires_free(args: dict[str, Any], byok: bool) -> bool:
    model = str(args.get("model", ""))
    return campaign_free_mode() or (
        not byok
        and (
            ":free" in model
            or promotional_free_route(model.removeprefix("openrouter/"))
        )
    )


def _request_body(args: dict[str, Any]) -> dict[str, Any]:
    if litellm.model_fallbacks or litellm.model_alias_map:
        raise FreeModelEligibilityError(
            "zero-cost SDK routing overrides are unqualified"
        )
    if args.keys() - _REQUEST_FIELDS:
        raise FreeModelEligibilityError(
            "zero-cost request contains unqualified options"
        )
    if args.get("api_base", _API_BASE) != _API_BASE:
        raise FreeModelEligibilityError(
            "zero-cost request uses an unverified endpoint"
        )
    body = args.get("extra_body", {})
    if not isinstance(body, dict) or body.keys() - _BODY_FIELDS:
        raise FreeModelEligibilityError(
            "zero-cost request contains plugins or unqualified routing"
        )
    _verify_messages(args.get("messages", []))
    _verify_tools(args.get("tools", []))
    return body


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise FreeModelEligibilityError(
            "zero-cost request requires a list of objects"
        )
    return value


def _verify_messages(messages: Any) -> None:
    for message in _object_list(messages):
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise FreeModelEligibilityError(
                "zero-cost request contains non-text input"
            )
        if message.keys() - {
            "role",
            "content",
            "tool_calls",
            "tool_call_id",
            "name",
            "reasoning_content",
            "reasoning",
            "reasoning_details",
        }:
            raise FreeModelEligibilityError(
                "zero-cost message contains unqualified fields"
            )


def _verify_tools(tools: Any) -> None:
    for tool in _object_list(tools):
        if tool.get("type") != "function" or set(tool) != {"type", "function"}:
            raise FreeModelEligibilityError(
                "zero-cost request contains a server tool"
            )


def _routes(args: dict[str, Any], body: dict[str, Any]) -> list[str]:
    primary = args.get("model", "")
    if not isinstance(primary, str) or not primary.startswith("openrouter/"):
        raise FreeModelEligibilityError("zero-cost requests require OpenRouter")
    fallbacks = body.get("models", [])
    if not isinstance(fallbacks, list) or not all(
        isinstance(m, str) for m in fallbacks
    ):
        raise FreeModelEligibilityError("zero-cost fallback list is invalid")
    return [primary.removeprefix("openrouter/"), *fallbacks]


async def enforce_free_request(
    args: dict[str, Any], *, byok: bool = False
) -> bool:
    """Validate routes before transport and attach binding zero-price ceilings.

    Campaign mode overrides BYOK. Outside it, the caller supplies credential
    provenance explicitly; a deployment key in kwargs is not a BYOK signal.
    """
    if not _requires_free(args, byok):
        return False
    body = _request_body(args)
    routes = _routes(args, body)
    catalog = await asyncio.to_thread(current_catalog)
    for model in routes:
        verify_model(model, catalog)
    raw_provider = body.get("provider", {})
    if not isinstance(raw_provider, dict):
        raise FreeModelEligibilityError(
            "zero-cost provider options must be an object"
        )
    provider = dict(raw_provider)
    provider["max_price"] = {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    provider["require_parameters"] = True
    args["extra_body"] = {**body, "provider": provider}
    # Pin the transport too: an environment-level proxy/base override must
    # not send an OpenRouter-qualified route to a different billing service.
    args["api_base"] = _API_BASE
    return True
