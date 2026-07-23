"""Application configuration using pydantic-settings."""

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
    debug: bool = False  # also raises app/co_scientist loggers to DEBUG

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
    # concurrent users do not contend for this. It is a runaway guard, not a
    # fairness mechanism: per-run spend is already bounded by the tier's
    # max_llm_calls budget, so this only needs to stop one client from
    # queueing an unbounded number of runs at once.
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

    # /status availability probes: per-probe network timeout and how long
    # a probe pair's result is reused before re-probing the MCP server.
    status_probe_timeout_seconds: float = 3.0
    status_probe_cache_ttl_seconds: float = 30.0

    # Optional SMTP transport for scientist-requested completion notices.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    public_app_url: str = "http://localhost:5173"

    # Researcher access. ``required`` rejects unauthenticated private API
    # requests; ``compatibility`` retains browser-local IDs for local demos.
    auth_mode: str = "compatibility"
    auth_secret: str = ""
    # JSON object mapping researcher ids to invite/access codes.
    researcher_access_codes: str = "{}"
    auth_session_hours: int = 12

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


def _is_deepseek(model_name: str) -> bool:
    """Whether ``model_name`` targets a DeepSeek model (thinking-capable)."""
    return "deepseek" in model_name.lower()


def _is_dashscope(model_name: str) -> bool:
    """Whether ``model_name`` routes through Alibaba Cloud DashScope.

    DashScope serves the same DeepSeek V4 tiers behind its OpenAI-compatible
    endpoint but controls thinking with ``enable_thinking`` (bool, default
    off) instead of DeepSeek's native ``thinking`` object, and does not
    support ``reasoning_effort``.
    """
    return model_name.lower().startswith("dashscope/")


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, object]:
    """Return an ``extra_body`` that disables DeepSeek V4 thinking mode.

    Reserved for the two call sites where reasoning does not earn its cost:

    - Title generation, a three-word extraction with ``max_tokens=24`` that a
      reasoning spend would leave empty.
    - Claim verification (``claim_verifier.py``), which runs once per claim per
      hypothesis; it is the app-side high-frequency counterpart to the engine's
      ranking tournament, and its verdict is a lookup against supplied passages
      rather than an open-ended judgment.

    Every other app call uses the thinking variant below. Non-DeepSeek models
    get an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``{"thinking": {"type": "disabled"}}`` for DeepSeek models,
        ``{"enable_thinking": False}`` for DeepSeek-on-DashScope, else ``{}``.
    """
    if not _is_deepseek(model_name):
        return {}
    if _is_dashscope(model_name):
        return {"enable_thinking": False}
    return {"thinking": {"type": "disabled"}}


def deepseek_thinking_kwargs(model_name: str) -> dict[str, object]:
    """Build litellm kwargs enabling DeepSeek V4 thinking at low effort.

    DeepSeek V4 (pro/flash) return chain-of-thought separately as
    ``reasoning_content`` and never fold it into ``content``, so structured
    parsing survives as long as ``max_tokens`` leaves room for the answer after
    the reasoning spend (the interview and claim-verifier budgets are sized for
    that). ``reasoning_effort='low'`` is the lightest reasoning tier that still
    thinks, chosen to bound the added latency and token cost of reasoning on
    every call. Spread into a completion call (``**deepseek_thinking_kwargs``).
    Used by every substantive app call (interview, Q&A, safety); titling and
    claim verification keep the non-thinking variant above. Non-DeepSeek models
    get an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``{"extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort":
        "low"}`` for DeepSeek models, ``{"extra_body": {"enable_thinking":
        True}}`` for DeepSeek-on-DashScope (which has no reasoning_effort
        tiers), else ``{}``.
    """
    if not _is_deepseek(model_name):
        return {}
    if _is_dashscope(model_name):
        return {"extra_body": {"enable_thinking": True}}
    return {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "low",
    }
