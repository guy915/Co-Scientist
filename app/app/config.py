import os
from typing import Any, Literal

from co_scientist.constants import (
    THINKING_FLOOR_MAX_TOKENS as THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm import deepseek_thinking_extra_body as _thinking_body
from co_scientist.llm import effective_max_tokens as _effective_max_tokens
from co_scientist.llm import model_profile as _model_profile
from co_scientist.llm import model_reasons as _model_reasons
from co_scientist.llm import reasoning_effort_args as _effort_args
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONVERSATIONAL_REASONING_EFFORT = "medium"
DEFAULT_MODEL = "openrouter/inclusionai/ling-3.1-flash"
THINKING_FLOOR_TIMEOUT_SECONDS = float(THINKING_FLOOR_MAX_TOKENS) / 75.0


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, Any]:
    result: dict[str, Any] = _thinking_body(model_name, enabled=False)
    return result


def deepseek_thinking_kwargs(model_name: str, *, effort: str | None = None) -> dict[str, Any]:
    extra_body = _thinking_body(model_name, enabled=True)
    if not extra_body:
        return {}
    kwargs: dict[str, Any] = {
        "extra_body": extra_body,
        **_effort_args(model_name, enabled=True),
    }
    if effort is not None and not _model_profile(model_name).pinned_effort:
        if "reasoning_effort" in kwargs:
            kwargs["reasoning_effort"] = effort
        reasoning = kwargs["extra_body"].get("reasoning")
        if isinstance(reasoning, dict) and "effort" in reasoning:
            reasoning["effort"] = effort
    return kwargs


def thinking_off_kwargs(model_name: str) -> dict[str, Any]:
    extra_body = deepseek_non_thinking_extra_body(model_name)
    return {"extra_body": extra_body} if extra_body else {}


def thinking_safe_max_tokens(model_name: str, answer_tokens: int) -> int:
    result: int = _effective_max_tokens(model_name, answer_tokens, True)
    return result


def thinking_safe_timeout(model_name: str, answer_seconds: float) -> float:
    """The conservative 75-token/s clock funds reasoning floors; streaming
    silence is bounded separately.
    """
    if not _model_reasons(model_name):
        return answer_seconds
    return max(answer_seconds, THINKING_FLOOR_TIMEOUT_SECONDS)


class Settings(BaseSettings):
    # App-operation physical-call caps remain separate from research budgets.
    app_llm_max_calls: int = Field(default=4, ge=1)

    # Production model choices are explicit hosting overrides; changing these
    # defaults alone does not change production.
    model_name: str = DEFAULT_MODEL
    supervisor_model_name: str | None = DEFAULT_MODEL
    chat_model_name: str | None = DEFAULT_MODEL
    # LiteLLM and the engine consume provider environment variables, not this
    # Settings object.
    gemini_api_key: str = ""

    # The module entrypoint uses this port; Makefile, Docker and browser
    # harnesses pass their own explicit ports.
    host: str = "0.0.0.0"  # bind address; 0.0.0.0 for container/dev use
    port: int = 8008
    coscientist_debug: bool = False

    # The engine MCP client reads MCP_SERVER_URL from the environment rather
    # than Settings.
    mcp_server_url: str = "http://localhost:8888/mcp"

    coscientist_cache_enabled: bool = True  # bridged to env for the engine
    coscientist_cache_dir: str = "./cache"

    # K-factor stays deployment-tunable while the engine owns tournament math
    # and initial ratings.
    elo_k_factor: int = 24

    # Deterministic safety hard blocks run first and cannot be overridden by
    # semantic assessment.
    semantic_safety_enabled: bool = True
    # Safety stays on the worker tier rather than the strategic supervisor tier.
    semantic_safety_model: str | None = DEFAULT_MODEL

    log_format: str = "text"

    log_capture_enabled: bool = True
    log_capture_level: str = "INFO"
    log_capture_max_rows: int = 20000
    # Without an operator token, only direct loopback callers qualify.
    logs_admin_token: str = ""
    # Browsers need open ingestion to report their own failures, so bound it per
    # client.
    logs_ingest_per_minute: int = 120

    # One concurrent-run ceiling spans all tiers per researcher; provider spend
    # is bounded separately.
    max_concurrent_runs: int = 10

    # SQLite's single writer, not provider concurrency, limits cohort width;
    # leave writer headroom for ordinary API requests.
    worker_pool_size: int = 8

    # Disable embedded cohorts when a separate durable worker service consumes
    # the same queue.
    coscientist_embedded_worker: bool = True

    status_probe_timeout_seconds: float = 3.0
    status_probe_cache_ttl_seconds: float = 30.0

    # Continuously polled local health snapshots use a short TTL to bound
    # aggregate queries.
    health_check_cache_ttl_seconds: float = 5.0
    # Low disk degrades rather than fails liveness: killing the container frees
    # no space.
    health_check_min_free_disk_bytes: int = 100 * 1024 * 1024

    # Cache exposition briefly so scrape storms do not multiply store query
    # passes.
    metrics_cache_ttl_seconds: float = 5.0

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    public_app_url: str = "http://localhost:5173"
    # The diagnostic-report recipient is fixed server-side, never chosen by the
    # requester.
    log_report_email: str = "guybarel2006@gmail.com"

    auth_mode: Literal["compatibility", "required"] = "compatibility"
    auth_secret: str = ""
    researcher_access_codes: str = "{}"
    # Only verified bearer subjects qualify for campaign funding, never
    # compatibility IDs.
    campaign_researcher_ids: set[str] = Field(default_factory=set)
    auth_session_hours: int = Field(default=12, gt=0)
    auth_exchange_per_minute: int = Field(default=20, gt=0)

    # Encryption and session-signing secrets are separate purposes; rotating one
    # must not silently rotate the other.
    byok_encryption_key: str = ""
    # Removing the daily cap does not remove the free express-only envelope.
    free_runs_per_day: int = 3

    tools_config: str | None = None

    # Hermetic tests select deterministic entailment; production defaults to
    # semantic assessment.
    claim_assessor: str = "llm"
    claim_verifier_model: str | None = None

    # Hermetic tests select metadata resolution; production defaults to live
    # identifier checks.
    evidence_resolver: str = "live"

    model_config = SettingsConfigDict(
        env_file=(None if os.getenv("PYTHON_DOTENV_DISABLED") == "1" else ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("campaign_researcher_ids")
    @classmethod
    def _validate_campaign_researcher_ids(cls, value: set[str]) -> set[str]:
        cleaned = {subject.strip() for subject in value}
        if "" in cleaned:
            raise ValueError("campaign researcher ids must be non-empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_auth_configuration(self) -> "Settings":
        if self.auth_mode == "required" and not self.auth_secret.strip():
            raise ValueError("AUTH_SECRET is required for AUTH_MODE=required")
        return self

    @property
    def effective_chat_model(self) -> str:
        return self.chat_model_name or self.model_name

    @property
    def effective_supervisor_model(self) -> str:
        """Diagnostics mirror the generator's actual supervisor fallback."""
        return self.supervisor_model_name or self.model_name


settings = Settings()


PROVIDER_CREDENTIAL_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "azure": ("AZURE_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
}
# LiteLLM reads process credentials; one map keeps offline and safety admission
# in agreement.


def provider_credential_names(model_name: str) -> tuple[str, ...]:
    provider = model_name.split("/", 1)[0].lower()
    return PROVIDER_CREDENTIAL_ENV.get(provider, ())


def has_provider_credential(model_name: str) -> bool:
    return any(os.getenv(name) for name in provider_credential_names(model_name))


def any_provider_credential() -> bool:
    return any(os.getenv(name) for names in PROVIDER_CREDENTIAL_ENV.values() for name in names)


BYOK_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "anthropic/claude-sonnet-5-5",
    "deepseek": "deepseek/deepseek-flash",
    "gemini": "gemini/gemini-3.8-flash",
    "openai": "openai/gpt-6.1-sol",
    "openrouter": "openrouter/z-ai/glm-5.3-flash",
}
# A local default per provider avoids guessing which other models a key covers.
# It seeds every role; existing runs retain their stored model selections.


def byok_default_model(provider: str) -> str | None:
    return BYOK_PROVIDER_DEFAULT_MODELS.get(provider)


def byok_enabled() -> bool:
    """Key-bearing requests require encryption support and must never be
    accepted for unprotected storage.
    """
    return bool(settings.byok_encryption_key)
