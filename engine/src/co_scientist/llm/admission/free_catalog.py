"""Fresh public OpenRouter metadata for zero-cost request admission."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm.profile import promotional_free_route

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
