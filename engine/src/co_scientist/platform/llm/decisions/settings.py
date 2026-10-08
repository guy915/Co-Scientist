from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class DecisionUnavailableError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        rate_limits: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.rate_limits = rate_limits or {}


def calibrated_threshold(site: str) -> float | None:
    try:
        value = float(os.getenv(f"DECISION_{site}_THRESHOLD", ""))
    except ValueError:
        return None
    return value if math.isfinite(value) and 0 < value <= 1 else None


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise DecisionUnavailableError("invalid decision enable setting")
    return value in {"true", "1"}


@dataclass(frozen=True)
class DecisionSettings:
    api_key: str = field(default="", repr=False)
    enabled: bool = False
    model: str = "d1:free"
    base_url: str = "https://api.liquid.ai/decisions/v1"
    timeout_seconds: float = 15
    max_calls_per_day: int = 256
    max_tokens_per_day: int = 4_000_000
    max_input_bytes: int = 131_072
    max_questions: int = 32
    context_tokens: int = 32_768

    @classmethod
    def from_env(cls) -> DecisionSettings:
        return cls(
            api_key=os.getenv("LIQUID_API_KEY", "").strip(),
            enabled=_flag("DECISION_ENABLED") and _flag("LLM_ENABLED", True),
            model=os.getenv("DECISION_MODEL_NAME", "d1:free"),
            base_url=os.getenv("DECISION_BASE_URL", cls.base_url),
            timeout_seconds=float(os.getenv("DECISION_TIMEOUT_SECONDS", "15")),
            max_calls_per_day=int(os.getenv("DECISION_MAX_CALLS_PER_DAY", "256")),
            max_tokens_per_day=int(os.getenv("DECISION_MAX_TOKENS_PER_DAY", "4000000")),
            max_input_bytes=int(os.getenv("DECISION_MAX_INPUT_BYTES", "131072")),
            max_questions=int(os.getenv("DECISION_MAX_QUESTIONS", "32")),
        )

    def validate(self) -> None:
        url = urlsplit(self.base_url)
        if (
            self.model != "d1:free"
            or url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise DecisionUnavailableError(
                "only the explicitly configured free decision route is allowed"
            )
        if not 0 < self.timeout_seconds <= 60 or not 1 <= self.max_questions <= 32:
            raise DecisionUnavailableError("invalid decision timeout or question limit")
        if any(
            type(value) is not int or value < 1
            for value in (
                self.max_calls_per_day,
                self.max_tokens_per_day,
                self.max_input_bytes,
                self.max_questions,
                self.context_tokens,
            )
        ):
            raise DecisionUnavailableError("invalid decision admission limit")
        if not 1 <= self.context_tokens <= 32_768:
            raise DecisionUnavailableError("invalid decision context limit")

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)
