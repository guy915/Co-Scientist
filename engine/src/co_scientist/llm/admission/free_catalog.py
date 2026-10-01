"""Fresh public OpenRouter metadata for zero-cost request admission."""

import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from co_scientist.exceptions import FreeModelEligibilityError

CATALOG_URL = "https://openrouter.ai/api/v1/models"
CATALOG_TTL_SECONDS = 60
# The official model page calls this exact preview free despite its unsuffixed
# ID. Fresh catalog prices and zero token-price ceilings gate campaign calls.
PROMOTIONAL_FREE_MODELS = frozenset({"stealth/space-bunny-alpha"})
_lock = threading.Lock()
_snapshot: tuple[float, dict[str, Any]] | None = None


def current_catalog() -> dict[str, Any]:
    """Read metadata off the event loop; never reuse an expired snapshot."""
    global _snapshot
    with _lock:
        if _snapshot is not None and time.monotonic() < _snapshot[0]:
            return _snapshot[1]
        _snapshot = None
        catalog = _fetch_catalog()
        _snapshot = (time.monotonic() + CATALOG_TTL_SECONDS, catalog)
        return catalog


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
        if model.endswith(":free") or model in PROMOTIONAL_FREE_MODELS
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
