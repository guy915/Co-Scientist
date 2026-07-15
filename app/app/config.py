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
    port: int = 8000
    debug: bool = False  # also raises app/co_scientist loggers to DEBUG

    # MCP Server Configuration (optional, for literature review tools)
    # Bridged into the MCP_SERVER_URL env var in main.py; the engine's MCP
    # client reads it from the environment, not from this Settings object.
    mcp_server_url: str = "http://localhost:8888/mcp"

    # Cache Configuration
    coscientist_cache_enabled: bool = True  # bridged to env for the engine
    coscientist_cache_dir: str = "./cache"

    # Elo tournament tuning. Defaults mirror the engine's constants.py so the
    # mock and real tournament behave identically (test_elo_engine_parity).
    elo_initial: int = 1200
    elo_k_factor: int = 24
    elo_upset_margin: int = 100

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

    # Claim-grounding entailment assessor for the real-engine path:
    # "deterministic" (offline lexical + negation, no provider) or "llm" (the
    # NLI assessor in claim_verifier.py, using claim_verifier_model). The mock
    # path and offline tests explicitly select deterministic mode; production
    # real-engine runs default to semantic claim assessment.
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


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, object]:
    """Return an ``extra_body`` that disables DeepSeek V4 thinking mode.

    DeepSeek V4 (pro/flash) default to thinking mode: the chain of thought is
    returned as ``reasoning_content`` and the final answer as ``content`` only
    after the reasoning budget is spent. Under the app's tight per-call token
    budgets (safety classification, titling, the four-field interview) that can
    leave ``content`` empty and break structured parsing, so app LLM calls
    disable thinking for deterministic output — the non-thinking mode of the
    deprecated ``deepseek-chat``. Non-DeepSeek models get an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``{"thinking": {"type": "disabled"}}`` for DeepSeek models, else ``{}``.
    """
    return (
        {"thinking": {"type": "disabled"}}
        if "deepseek" in model_name.lower()
        else {}
    )
