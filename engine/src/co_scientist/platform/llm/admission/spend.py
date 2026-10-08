from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db import current_time
from co_scientist.platform.db.spend import UNAVAILABLE, SpendRecord, SpendReservation
from co_scientist.platform.llm.profile import model_profile
from co_scientist.platform.llm.roles import current_call_policy

_blocked: set[str] = set()
_lock = threading.Lock()
_MAX_INTEGER = 2**63 - 1


def _enabled(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() in ("1", "true"):
        return True
    if value.lower() in ("0", "false"):
        return False
    raise ProviderAdmissionError(UNAVAILABLE)


def require_enabled() -> None:
    if not _enabled("LLM_ENABLED", True):
        raise ProviderAdmissionError(UNAVAILABLE)


def _decimal(value: str | None) -> Decimal:
    try:
        result = Decimal(value or "")
        if not result.is_finite() or result <= 0:
            raise InvalidOperation
        return result
    except InvalidOperation as error:
        raise ProviderAdmissionError(UNAVAILABLE) from error


def _microeur(value: Decimal) -> int:
    result = int(value.to_integral_value(rounding=ROUND_CEILING))
    if not 0 <= result <= _MAX_INTEGER:
        raise ProviderAdmissionError(UNAVAILABLE)
    return result


@dataclass(frozen=True)
class SpendConfig:
    total: int
    fx: Decimal
    cutoff: float


def azure_config() -> SpendConfig:
    require_enabled()
    if not _enabled("LLM_AZURE_ENABLED", False):
        raise ProviderAdmissionError(UNAVAILABLE)
    total = _decimal(os.getenv("LLM_TOTAL_BUDGET_EUR"))
    fx = _decimal(os.getenv("LLM_USD_TO_EUR", "0.88"))
    try:
        raw = os.getenv("LLM_AZURE_UNTIL", "")
        until = date.fromisoformat(raw)
        if until.isoformat() != raw:
            raise ValueError
        # The portal shows a date without a time zone. Stop at its UTC start
        # rather than risk card charges during the unconfirmed final day.
        cutoff = datetime.combine(until, time.min, timezone.utc).timestamp()
    except ValueError as error:
        raise ProviderAdmissionError(UNAVAILABLE) from error
    if current_time() >= cutoff:
        raise ProviderAdmissionError(UNAVAILABLE)
    limit = int((total * 1_000_000).to_integral_value(rounding=ROUND_FLOOR))
    if not 0 < limit <= _MAX_INTEGER:
        raise ProviderAdmissionError(UNAVAILABLE)
    return SpendConfig(limit, fx, cutoff)


def block_spending(db_path: str) -> None:
    with _lock:
        _blocked.add(db_path)


def _blocked_path(db_path: str) -> bool:
    with _lock:
        return db_path in _blocked


def paid_dispatch_config(db_path: str) -> SpendConfig:
    config = azure_config()
    if _blocked_path(db_path):
        raise ProviderAdmissionError(UNAVAILABLE)
    return config


def prepare_spend(request: dict[str, Any], tokens: int, db_path: str) -> SpendReservation | None:
    require_enabled()
    model = str(request.get("model", "")).replace("azure/responses/", "azure/")
    if not model.startswith("azure/"):
        return None
    config = paid_dispatch_config(db_path)
    price = model_profile(model).price
    if price is None or model_profile(model).version is None:
        raise ProviderAdmissionError(UNAVAILABLE)
    # The short/long boundary is unconfirmed; use the higher known rates.
    price = price.long_context or price
    rates = {
        "input": str(price.prompt_usd_per_million),
        "output": str(price.completion_usd_per_million),
        "cached": str(price.cached_prompt_usd_per_million),
        "write": str(price.cache_write_usd_per_million),
        "fx": str(config.fx),
    }
    output = request.get("max_completion_tokens", request.get("max_tokens"))
    if not isinstance(output, int) or isinstance(output, bool) or output <= 0:
        raise ProviderAdmissionError(UNAVAILABLE)
    inputs = tokens - output
    amount = price_cost(rates, inputs, output, cached=0, written=4 * inputs)
    return SpendReservation(
        model,
        current_call_policy().role,
        amount,
        config.total,
        config.cutoff,
        inputs,
        output,
        json.dumps(rates),
    )


def price_cost(
    rates: dict[str, str], inputs: int, outputs: int, *, cached: int, written: int
) -> int:
    # Rates are USD per million tokens; multiplying by FX yields micro-EUR
    # per token. Reasoning is already within output, never an extra charge.
    value = (
        (inputs - cached) * Decimal(rates["input"])
        + cached * Decimal(rates["cached"])
        + outputs * Decimal(rates["output"])
        + written * Decimal(rates["write"])
    ) * Decimal(rates["fx"])
    return _microeur(value)


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _number(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def settled_cost(
    row: SpendRecord, usage: Any
) -> tuple[int, int, int, int | None, int | None] | None:
    if row.settled:
        return None
    prompt = _number(_field(usage, "prompt_tokens"))
    output = _number(_field(usage, "completion_tokens"))
    details = _field(usage, "prompt_tokens_details")
    cached = _number(_field(details, "cached_tokens"))
    written = _number(_field(details, "cache_write_tokens"))
    if prompt is None or output is None:
        return None
    rates = json.loads(row.rates)
    if Decimal(rates["write"]) and written is None:
        return None
    if (
        prompt > row.input_bound
        or output > row.output_bound
        or (cached is not None and cached > prompt)
        or (written is not None and written > 4 * row.input_bound)
    ):
        raise ProviderAdmissionError(UNAVAILABLE)
    return (
        price_cost(rates, prompt, output, cached=cached or 0, written=written or 0),
        prompt,
        output,
        cached,
        written,
    )
