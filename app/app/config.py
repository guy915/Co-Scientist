"""Application configuration using pydantic-settings."""

import os
from typing import Any

from co_scientist.llm_request import (
    deepseek_thinking_extra_body as _thinking_body,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Configuration
    # model_name: worker model — generate, review, ranking, reflection, evolve,
    # proximity, literature_review, claim verification. High-volume, runs many
    # times per iteration. DeepSeek V4 Flash: the fast, cheap thinking tier.
    model_name: str = "deepseek/deepseek-v4-flash"
    # supervisor_model_name: strategic model — supervisor (research planning),
    # meta_review and research_overview (final report synthesis). Runs once or
    # twice per iteration. DeepSeek V4 Pro: the stronger thinking model. Falls
    # back to model_name only if explicitly cleared.
    supervisor_model_name: str | None = "deepseek/deepseek-v4-pro"
    # chat_model_name: model for all user-facing communication — the research
    # interview, Chat-tab Q&A, and session titling. DeepSeek V4 Pro, matching
    # the supervisor tier. Falls back to model_name only if explicitly cleared.
    chat_model_name: str | None = "deepseek/deepseek-v4-pro"
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
    # the engine's constants.py (app/elo.py's INITIAL_ELO), which is the
    # actual owner of the tournament math; this stays app-owned so per-
    # deployment tuning does not require an engine change
    # (test_elo_engine_parity guards it against engine drift).
    elo_k_factor: int = 24

    # Safety filter aggressiveness: "standard" or "strict". safety.py coerces
    # this into its SafetyMode enum, defaulting to standard on any other value.
    safety_mode: str = "standard"
    # Contextual safety assessment is used for real-provider runs when the
    # configured model's provider credential is present. Deterministic hard
    # blocks always run first and cannot be overridden by the model.
    semantic_safety_enabled: bool = True
    # Kept on the worker tier (V4 Flash) rather than falling back to the
    # supervisor model, so safety screening stays on the "everything else" tier.
    semantic_safety_model: str | None = "deepseek/deepseek-v4-flash"

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
    # Grants the app-wide log view to non-loopback callers (ops/CLI in
    # Docker or against a remote deployment). Empty means loopback only.
    logs_admin_token: str = ""
    # Per-client ceiling on POST /api/logs, which is open by necessity
    # (browsers must be able to report their own errors).
    logs_ingest_per_minute: int = 120

    # How many runs one researcher may have in flight at once. Scoped per
    # client, so one researcher's runs never consume another's allowance --
    # concurrent users do not contend for this. One ceiling covers every
    # tier together (see store.reserve_run_capacity): counting each tier
    # separately let one caller hold this many express runs *and* this many
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
    auth_mode: str = "compatibility"
    auth_secret: str = ""
    # JSON object mapping researcher ids to invite/access codes.
    researcher_access_codes: str = "{}"
    auth_session_hours: int = 12

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

    # Tools Configuration (optional)
    # Path to a YAML tools config file, or an HTTP(S) URL.
    # Relative paths resolve from the server working directory.
    tools_config: str | None = None

    # Claim-grounding entailment assessor for the engine path:
    # "deterministic" (offline lexical + negation, no provider) or "llm" (the
    # NLI assessor in claim_verifier.py, using claim_verifier_model). Offline
    # tests explicitly select deterministic mode; production runs default to
    # semantic claim assessment.
    claim_assessor: str = "llm"
    # Model for the "llm" claim assessor; falls back to model_name when unset.
    claim_verifier_model: str | None = None

    # Evidence-identity availability check for the engine drain: "live"
    # dereferences each article's DOI/PMID against the real web
    # (app/citation_resolver.py); anything else falls back to the offline
    # metadata heuristic (a non-empty identifier and no retraction flag).
    # Offline tests explicitly select the fallback; production runs default
    # to a live dereference.
    evidence_resolver: str = "live"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

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
    "openrouter": "openrouter/deepseek/deepseek-v4-flash",
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


def _is_deepseek(model_name: str) -> bool:
    """Whether ``model_name`` targets a DeepSeek model (thinking-capable)."""
    return "deepseek" in model_name.lower()


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, Any]:
    """Return an ``extra_body`` that disables DeepSeek V4 thinking mode.

    Used by one call site: title generation, a 3-6 word extraction whose
    ``max_tokens=24`` a reasoning spend would consume entirely, returning an
    empty completion and leaving the run untitled. That coupling runs both
    ways -- a non-thinking call spends its whole budget on the answer, so
    opting any call site in or out of thinking means revisiting its
    ``max_tokens`` in the same edit. Every other app call uses the thinking
    variant below. Non-DeepSeek models get an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        The disable knob this model's route understands, or ``{}`` for a
        model with no thinking mode. The engine picks the shape: a gateway
        normalizes reasoning into its own parameter, and DeepSeek's native
        one sent through OpenRouter enables thinking instead of disabling.
    """
    # Annotated because this project's mypy treats engine symbols as Any.
    knob: dict[str, Any] = _thinking_body(model_name, enabled=False)
    return knob


def deepseek_thinking_kwargs(model_name: str) -> dict[str, Any]:
    """Build litellm kwargs enabling DeepSeek V4 thinking at low effort.

    DeepSeek V4 (pro/flash) return chain-of-thought separately as
    ``reasoning_content`` and never fold it into ``content``, so structured
    parsing survives as long as ``max_tokens`` leaves room for the answer
    after the reasoning spend. Call sites do not size for that themselves --
    the interview and claim-verifier budgets were answer-sized and had to be
    lifted -- so pass the budget through ``thinking_safe_max_tokens`` below
    wherever these kwargs are spread. ``reasoning_effort='high'`` is the
    *floor*, not a high setting:
    DeepSeek implements only ``high`` and ``max`` and accepts OpenAI's lower
    names as aliases onto ``high``, so there is no cheaper tier than this
    short of switching thinking off. It is also DeepSeek's own default once
    thinking is enabled, which makes the field belt-and-braces rather than
    load-bearing -- litellm 1.80.x drops ``reasoning_effort`` from the
    request body entirely (BerriAI/litellm#27439), and because the value
    matches the provider default that bug changes nothing here. Sending it
    anyway means the intent is recorded and the call is already correct when
    the fix lands. Spread into a completion call
    (``**deepseek_thinking_kwargs``). Used by every app call except titling:
    interview, Q&A, safety, and claim verification. Non-DeepSeek models get
    an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``extra_body`` in the shape this model's route understands, plus
        the reasoning tier; ``{}`` for a model with no thinking mode.
    """
    extra_body = _thinking_body(model_name, enabled=True)
    if not extra_body:
        return {}
    return {"extra_body": extra_body, "reasoning_effort": "high"}


THINKING_FLOOR_MAX_TOKENS = 18_000
"""Smallest total budget an app-side thinking call may be sent with.

The provider counts reasoning against ``max_tokens`` alongside the answer,
so a budget sized for the answer alone lets a long chain of thought consume
the whole allowance: the call returns ``finish_reason="length"`` with empty
content, is billed in full, and is retried. The engine hit exactly this on
every node whose budget predated thinking being switched on
(``co_scientist.constants.THINKING_FLOOR_MAX_TOKENS``, which this mirrors);
the app's calls bypass that layer by invoking ``litellm.acompletion``
directly, so they need the floor applied at their own call sites.

A ceiling is not a spend -- raising it costs nothing on calls that answer
briefly, and only removes the failure mode on the ones that reason at
length.
"""


def thinking_safe_max_tokens(model_name: str, answer_tokens: int) -> int:
    """Return a ``max_tokens`` that leaves room to reason and then answer.

    Args:
        model_name: Model name in litellm format.
        answer_tokens: Budget the call site wants for the answer itself.

    Returns:
        ``answer_tokens`` for models without a thinking mode, else at least
        ``THINKING_FLOOR_MAX_TOKENS``. Only ever raises, so a call site that
        already asked for more keeps its own number.
    """
    if not _is_deepseek(model_name):
        return answer_tokens
    return max(answer_tokens, THINKING_FLOOR_MAX_TOKENS)


THINKING_FLOOR_TIMEOUT_SECONDS = 240.0
"""Smallest wall clock an app-side thinking call may be given.

The token budget and the clock are one setting in two places: funding a
chain of thought without extending the deadline just moves the failure from
a truncated answer to an abandoned one, and both land in the same silent
fallback. ``THINKING_FLOOR_MAX_TOKENS`` admits 18k tokens, so the clock has
to admit 18k tokens arriving -- 240s is that budget at a deliberately
pessimistic 75 tok/s, well under what the provider sustains in practice.

A long deadline is only acceptable where nobody is watching a blank screen
for the length of it. The safety and claim-verifier calls are background
durable tasks, and the interview relays its chain of thought to the
scientist as it arrives. Q&A is the weak case: it streams, so a stalled
provider is still caught quickly, but it forwards only answer deltas, so a
long reasoning pass does read as a quiet chat. Before applying this floor
to another call site, check which of those three it is -- a blocking
request that shows the caller nothing until it returns needs a different
answer than a bigger number here.
"""


def thinking_safe_timeout(model_name: str, answer_seconds: float) -> float:
    """Return a timeout that lets a funded chain of thought finish arriving.

    Args:
        model_name: Model name in litellm format.
        answer_seconds: Deadline the call site wants for the answer itself.

    Returns:
        ``answer_seconds`` for models without a thinking mode, else at least
        ``THINKING_FLOOR_TIMEOUT_SECONDS``. Only ever raises, so a call site
        that already allowed more keeps its own number.
    """
    if not _is_deepseek(model_name):
        return answer_seconds
    return max(answer_seconds, THINKING_FLOOR_TIMEOUT_SECONDS)
