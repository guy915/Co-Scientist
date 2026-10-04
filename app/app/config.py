"""Application settings and model request policy."""

import os
from typing import Any, Literal

from co_scientist.constants import (
    THINKING_FLOOR_MAX_TOKENS as THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm import deepseek_thinking_extra_body as _thinking_body
from co_scientist.llm import effective_max_tokens as _effective_max_tokens
from co_scientist.llm import model_reasons as _model_reasons
from co_scientist.llm import reasoning_effort_args as _effort_args
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONVERSATIONAL_REASONING_EFFORT = "medium"
THINKING_FLOOR_TIMEOUT_SECONDS = float(THINKING_FLOOR_MAX_TOKENS) / 75.0


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, Any]:
    """Return the engine-owned request body disabling a model's thinking."""
    result: dict[str, Any] = _thinking_body(model_name, enabled=False)
    return result


def deepseek_thinking_kwargs(
    model_name: str, *, effort: str | None = None
) -> dict[str, Any]:
    """Enable thinking and optionally override the route's reasoning tier."""
    extra_body = _thinking_body(model_name, enabled=True)
    if not extra_body:
        return {}
    kwargs: dict[str, Any] = {
        "extra_body": extra_body,
        **_effort_args(model_name, enabled=True),
    }
    if effort is not None:
        if "reasoning_effort" in kwargs:
            kwargs["reasoning_effort"] = effort
        reasoning = kwargs["extra_body"].get("reasoning")
        if isinstance(reasoning, dict) and "effort" in reasoning:
            reasoning["effort"] = effort
    return kwargs


def thinking_off_kwargs(model_name: str) -> dict[str, Any]:
    """Disable thinking on a retry after a turn returned reasoning only."""
    extra_body = deepseek_non_thinking_extra_body(model_name)
    return {"extra_body": extra_body} if extra_body else {}


def thinking_safe_max_tokens(model_name: str, answer_tokens: int) -> int:
    """Apply the engine's reasoning budget floor to an app completion."""
    result: int = _effective_max_tokens(model_name, answer_tokens, True)
    return result


def thinking_safe_timeout(model_name: str, answer_seconds: float) -> float:
    """Fund the same reasoning token floor at a conservative 75 tokens/s.

    Apply this generous clock to live streams or background work; streams
    also have their own silence timeout to detect a stalled provider.
    """
    if not _model_reasons(model_name):
        return answer_seconds
    return max(answer_seconds, THINKING_FLOOR_TIMEOUT_SECONDS)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Configuration
    #
    # The system default for worker, supervisor, chat, and semantic safety
    # is the zero-priced Space Bunny route. Its gateway declaration pins
    # calls to Stealth, disables provider fallback, and has no model-level
    # fallback. The current listing is checked before calls and the request
    # keeps a zero-price ceiling. Explicit environment/BYOK model choices
    # remain supported.
    #
    # Each interview/chat/title/probe operation has its own physical-call cap.
    # Retries and Q&A tool rounds share it; research-run budgets stay separate.
    app_llm_max_calls: int = Field(default=4, ge=1)

    # Production overrides all four settings below via explicit Railway
    # env vars (see ``docs/DEPLOYMENT.md``); changing prod is an env
    # change, not a deploy of this file.
    #
    # model_name: worker model -- generate, review, ranking, reflection,
    # evolve, proximity, literature_review, claim verification. High-volume,
    # runs many times per iteration.
    model_name: str = "openrouter/stealth/space-bunny-alpha"
    # supervisor_model_name: strategic model -- supervisor (research
    # planning), meta_review and research_overview (final report synthesis).
    # Runs once or twice per iteration. The same model as the worker tier.
    # Falls back to model_name only if explicitly cleared.
    supervisor_model_name: str | None = "openrouter/stealth/space-bunny-alpha"
    # chat_model_name: model for all user-facing communication -- the
    # research interview, Chat-tab Q&A, and session titling. Falls back to
    # model_name only if explicitly cleared.
    chat_model_name: str | None = "openrouter/stealth/space-bunny-alpha"
    # Bridged into the GEMINI_API_KEY env var at import time in main.py, since
    # LiteLLM and the engine read provider keys from the environment directly.
    gemini_api_key: str = ""

    # Server Configuration
    host: str = "0.0.0.0"  # bind address; 0.0.0.0 for container/dev use
    # Only consumed by the `python -m app.main` entry point below; `make dev`,
    # Docker, and the e2e harness all pass --port explicitly. 8008 matches the
    # port everything else in the repo uses (make start, docker-compose).
    port: int = 8008
    # also raises app/co_scientist loggers to DEBUG
    coscientist_debug: bool = False

    # MCP Server Configuration (optional, for literature review tools)
    # Bridged into the MCP_SERVER_URL env var in main.py; the engine's MCP
    # client reads it from the environment, not from this Settings object.
    mcp_server_url: str = "http://localhost:8888/mcp"

    # Cache Configuration
    coscientist_cache_enabled: bool = True  # bridged to env for the engine
    coscientist_cache_dir: str = "./cache"

    # Elo tournament K-factor. The initial rating itself is re-exported from
    # the engine's constants package (app/elo.py's INITIAL_ELO), which is the
    # actual owner of the tournament math; this stays app-owned so per-
    # deployment tuning does not require an engine change
    # (test_elo_engine_parity guards it against engine drift).
    elo_k_factor: int = 24

    # Safety filter aggressiveness: "standard" or "strict". app.safety coerces
    # this into its SafetyMode enum, defaulting to standard on any other value.
    safety_mode: str = "standard"
    # Contextual safety assessment is used for real-provider runs when the
    # configured model's provider credential is present. Deterministic hard
    # blocks always run first and cannot be overridden by the model.
    semantic_safety_enabled: bool = True
    # Kept on the worker tier rather than falling back to the supervisor
    # model, so safety screening stays on the "everything else" tier.
    semantic_safety_model: str | None = "openrouter/stealth/space-bunny-alpha"

    # Log record format: "text" (human-readable, default) or "json"
    # (one structured object per line). Both go to stdout; see
    # app/logging_setup.py. Any other value falls back to text.
    log_format: str = "text"

    # Persistent log capture: mirror every record that reaches the root
    # logger into the app_logs table (served by /api/logs and the UI Logs
    # panel). Level names follow the stdlib; unknown values fall back to
    # INFO. The row cap bounds the table via periodic pruning.
    log_capture_enabled: bool = True
    log_capture_level: str = "INFO"
    log_capture_max_rows: int = 20000
    # Remote operators need this token; an empty token permits only loopback.
    logs_admin_token: str = ""
    # Per-client ceiling on POST /api/logs, which is open by necessity
    # (browsers must be able to report their own errors).
    logs_ingest_per_minute: int = 120

    # How many runs one researcher may have in flight at once. Scoped per
    # client, so one researcher's runs never consume another's allowance --
    # concurrent users do not contend for this. One ceiling covers every
    # tier together (store.reserve_run_capacity_in_transaction). Counting
    # tiers separately let one caller hold this many express runs and as many
    # ultra ones. It is a runaway guard, not a fairness mechanism: per-run
    # spend is already bounded by the tier's max_llm_calls budget, so this
    # only needs to stop one client from queueing an unbounded number of
    # runs at once.
    max_concurrent_runs: int = 10

    # How many durable tasks one run executes at once. A run's fan-out
    # phases -- per-hypothesis reviews, verifications, generation strategies
    # -- are independent tasks, so this is purely how much of that queue
    # overlaps and never changes what any task produces.
    #
    # The provider is not what bounds this. Measured on the production
    # model, twenty-four concurrent completions return in the same wall
    # clock as four, with latency flat and throughput scaling linearly.
    # SQLite is: every task boundary commits a checkpoint and there is only
    # one writer, so past some width the workers queue on the write lock
    # instead of the provider -- at twelve (times several concurrent runs)
    # the lock stayed saturated and ordinary API writes failed outright.
    # Eight buys most of the available overlap while leaving the writer
    # headroom to serve requests. Tunable without a code change.
    worker_pool_size: int = 8

    # Whether this process drains the durable task queue itself. True (the
    # default) runs a run's worker cohort inside the API process, which is
    # what local development and the single-service deployment rely on. A
    # deployment that runs ``python -m app.task_worker`` as its own service
    # sets COSCIENTIST_EMBEDDED_WORKER=0 on the API so the two never lease the
    # same task. Read through Settings rather than os.getenv at each launch
    # site: three sites restated the "1" default independently and compared it
    # inconsistently, so a typo'd value meant something different depending on
    # which of them read it.
    coscientist_embedded_worker: bool = True

    # /status availability probes: per-probe network timeout and how long
    # a probe pair's result is reused before re-probing the MCP server.
    status_probe_timeout_seconds: float = 3.0
    status_probe_cache_ttl_seconds: float = 30.0

    # /health durable-queue and disk checks. Both are local (a SQLite
    # aggregate and a stat on the database's directory), not network calls,
    # but /health is what a deploy platform polls continuously, so the same
    # bound-and-cache shape as the /status probes applies: reuse a snapshot
    # for a short TTL rather than paying for one on every poll.
    health_check_cache_ttl_seconds: float = 5.0
    # Free-disk floor (bytes) on the database's volume below which /health
    # reports degraded, not unhealthy -- killing the container does not
    # free space, and the process can still serve reads off a full disk.
    health_check_min_free_disk_bytes: int = 100 * 1024 * 1024

    # /metrics: how long a rendered Prometheus exposition-text snapshot is
    # reused before the next scrape re-queries the store. Same bound-and-
    # cache shape as /health and /status above -- Prometheus's default
    # scrape interval is 15s, so a few seconds keeps a scrape storm cheap
    # without staling the numbers meaningfully between real scrapes.
    metrics_cache_ttl_seconds: float = 5.0

    # Optional SMTP transport for scientist-requested completion notices.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    public_app_url: str = "http://localhost:5173"
    # Where the Logs panel's Report button sends a diagnostic export. The
    # recipient is fixed server-side and never taken from the request, so
    # the endpoint cannot be pointed at a third party.
    log_report_email: str = "guybarel2006@gmail.com"

    # Researcher access. ``required`` rejects unauthenticated private API
    # requests; ``compatibility`` retains browser-local IDs for local demos.
    auth_mode: Literal["compatibility", "required"] = "compatibility"
    auth_secret: str = ""
    # JSON object mapping researcher ids to invite/access codes.
    researcher_access_codes: str = "{}"
    # Verified bearer subjects assigned to the server-funded campaign.
    # Compatibility X-Client-ID values never qualify (see execution_policy).
    campaign_researcher_ids: set[str] = Field(default_factory=set)
    auth_session_hours: int = Field(default=12, gt=0)
    auth_exchange_per_minute: int = Field(default=20, gt=0)

    # Bring-your-own-key (BYOK) support. A scientist may send a provider
    # API key on run creation (X-LLM-API-Key / X-LLM-Provider headers);
    # the key is validated live, then persisted encrypted for the run's
    # lifetime (see app/credentials.py). This setting is the encryption
    # secret. Deliberately NOT ``auth_secret``: that one signs researcher
    # sessions, may legitimately stay empty in compatibility mode, and
    # rotating one purpose should not rotate the other. Empty means BYOK
    # is disabled on this deployment and key-carrying requests are
    # rejected with a clear 503 at creation time.
    byok_encryption_key: str = ""
    # Free usage: a run with no BYOK key runs on the deployment's free
    # models, so it is limited to the express tier and to this many runs
    # per client identity per UTC day (see app/free_usage.py). Zero or
    # less removes the daily cap; the express-only rule still holds.
    free_runs_per_day: int = 3

    # Tools Configuration (optional)
    # Path to a YAML tools config file, or an HTTP(S) URL.
    # Relative paths resolve from the server working directory.
    tools_config: str | None = None

    # Claim-grounding entailment assessor for the engine path:
    # "deterministic" (offline lexical + negation, no provider) or "llm" (the
    # NLI assessor in claims/verifier.py, using claim_verifier_model). Offline
    # tests explicitly select deterministic mode; production runs default to
    # semantic claim assessment.
    claim_assessor: str = "llm"
    # Model for the "llm" claim assessor; falls back to model_name when unset.
    claim_verifier_model: str | None = None

    # Evidence-identity availability check for the engine drain: "live"
    # dereferences each article's DOI/PMID against the real web
    # (app/citations/resolver.py); anything else falls back to the offline
    # metadata heuristic (a non-empty identifier and no retraction flag).
    # Offline tests explicitly select the fallback; production runs default
    # to a live dereference.
    evidence_resolver: str = "live"

    model_config = SettingsConfigDict(
        env_file=(
            None if os.getenv("PYTHON_DOTENV_DISABLED") == "1" else ".env"
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("campaign_researcher_ids")
    @classmethod
    def _validate_campaign_researcher_ids(cls, value: set[str]) -> set[str]:
        """Reject empty identities and normalize harmless whitespace."""
        cleaned = {subject.strip() for subject in value}
        if "" in cleaned:
            raise ValueError("campaign researcher ids must be non-empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_auth_configuration(self) -> "Settings":
        """Refuse required authentication without a signing secret."""
        if self.auth_mode == "required" and not self.auth_secret.strip():
            raise ValueError("AUTH_SECRET is required for AUTH_MODE=required")
        return self

    @property
    def effective_chat_model(self) -> str:
        """Model for Q&A and titling: the chat model, else the worker default.

        ``chat_model_name`` is optional (typically a fast/cheap model); when
        unset, callers fall back to the app-wide ``model_name``.
        """
        return self.chat_model_name or self.model_name

    @property
    def effective_supervisor_model(self) -> str:
        """Strategic model: the supervisor model, else the worker default.

        Mirrors the engine generator's own fallback, so ``/status`` reports the
        model the generator will actually use for planning/meta-review.
        """
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
"""Env vars that credential each LiteLLM provider prefix.

Not a Settings field: LiteLLM and the engine read these from the process
environment directly, so "can this provider be called" is an env question.
It is one map because the answer has to be the same wherever it is asked.
Two hand-maintained copies drifted in opposite directions and each gap
failed silently rather than loudly:

- The offline-mode probe knew ``AZURE_API_KEY`` but not ``GOOGLE_API_KEY``,
  so a deployment credentialed only through ``GOOGLE_API_KEY`` looked
  keyless and ran every run on the deterministic offline backend.
- The semantic safety screen knew ``GOOGLE_API_KEY`` but not
  ``AZURE_API_KEY``, so ``SEMANTIC_SAFETY_MODEL=azure/...`` resolved to no
  credential at all and every contextual screen returned the deterministic
  baseline instead.

Adding a provider here is one edit, and both questions learn it at once.
"""


def provider_credential_names(model_name: str) -> tuple[str, ...]:
    """Return the env vars that credential ``model_name``'s provider.

    Args:
        model_name: Model name in litellm format (``provider/model``). A
            name with no prefix, or an unknown prefix, has no known
            credential.

    Returns:
        The provider's credential env var names, empty when unknown.
    """
    provider = model_name.split("/", 1)[0].lower()
    return PROVIDER_CREDENTIAL_ENV.get(provider, ())


def has_provider_credential(model_name: str) -> bool:
    """Return whether ``model_name``'s own provider has a usable credential.

    Args:
        model_name: Model name in litellm format (``provider/model``).

    Returns:
        True when at least one of that provider's credential env vars is set
        to a non-empty value.
    """
    return any(
        os.getenv(name) for name in provider_credential_names(model_name)
    )


def any_provider_credential() -> bool:
    """Return whether any known provider credential is present.

    Used to decide whether this process can attempt a real LLM call at all.
    Which model is actually used is a separate question, settled by
    ``settings.model_name`` and friends.

    Returns:
        True when at least one credential env var in
        ``PROVIDER_CREDENTIAL_ENV`` is set to a non-empty value.
    """
    return any(
        os.getenv(name)
        for names in PROVIDER_CREDENTIAL_ENV.values()
        for name in names
    )


BYOK_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "anthropic/claude-sonnet-4-5",
    # Azure additionally needs deployment routing (api_base/api_version)
    # that BYOK does not carry, so its validation call fails until the
    # deployment configures that; it stays listed because
    # PROVIDER_CREDENTIAL_ENV knows it.
    "azure": "azure/gpt-4o",
    # Mirrors the app's own worker default: a DeepSeek key pointed at the
    # model this deployment was built around.
    "deepseek": "deepseek/deepseek-v4-flash",
    "gemini": "gemini/gemini-2.5-flash",
    # A non-reasoning model on purpose: reasoning models bill their chain
    # of thought against max_tokens, and this table cannot revisit every
    # call site's budget the way switching thinking on for one requires.
    "openai": "openai/gpt-4o",
    # One key that reaches every model, including the ones this
    # deployment already runs. A scientist bringing an OpenRouter key
    # gets the same DeepSeek weights the deployment defaults to, so a
    # BYOK run is comparable to a house run rather than a different
    # experiment.
    "openrouter": "openrouter/z-ai/glm-5.3-flash",
}
"""Default model each BYOK provider runs, in litellm format.

A LOCAL CHOICE, not provider gospel: one entry per provider in
``PROVIDER_CREDENTIAL_ENV`` (the closed set the Settings UI offers), each
a mainstream model litellm routes for that provider. A bring-your-own-key
run uses its provider's entry for EVERY tier -- worker, supervisor, and
chat alike -- because the deployment cannot know what else the scientist's
account may call, so one model per key keeps the run on ground the key is
known to cover. Changing an entry changes what new BYOK runs for that
provider use; runs already created keep the model recorded with their
stored credential.
"""


def byok_default_model(provider: str) -> str | None:
    """Return the default BYOK model for ``provider``, or None if unknown.

    Args:
        provider: Provider name as sent on the X-LLM-Provider header.

    Returns:
        The provider's default model in litellm format, or None when the
        provider is not one ``BYOK_PROVIDER_DEFAULT_MODELS`` knows.
    """
    return BYOK_PROVIDER_DEFAULT_MODELS.get(provider)


def byok_enabled() -> bool:
    """Return whether this deployment can accept bring-your-own-key runs.

    BYOK needs the encryption secret that protects stored keys; without
    it, key-carrying requests are refused at creation time rather than
    stored unprotected.

    Returns:
        True when ``byok_encryption_key`` is configured.
    """
    return bool(settings.byok_encryption_key)
