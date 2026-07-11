"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Configuration
    # model_name: worker model — generate, review, ranking, reflection, evolve,
    # proximity, literature_review. High-volume, runs many times per iteration.
    # Use a fast/cheap model.
    model_name: str = "gemini/gemini-2.5-flash"
    # supervisor_model_name: strategic model — supervisor (research planning)
    # and meta_review (final report synthesis). Runs once or twice per
    # iteration. Use a stronger model. If None, falls back to model_name
    # (single-model mode for testing / cost saving).
    supervisor_model_name: str | None = None
    # chat_model_name: model used for Q&A responses in the Chat tab.
    # Defaults to model_name if not set. Use a cheaper/faster model for
    # snappy answers.
    chat_model_name: str | None = None
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

    # Log record format: "text" (human-readable, default) or "json"
    # (one structured object per line). Both go to stdout; see
    # app/logging_setup.py. Any other value falls back to text.
    log_format: str = "text"

    # /status availability probes: per-probe network timeout and how long
    # a probe pair's result is reused before re-probing the MCP server.
    status_probe_timeout_seconds: float = 3.0
    status_probe_cache_ttl_seconds: float = 30.0

    # Tools Configuration (optional)
    # Path to a YAML tools config file, or an HTTP(S) URL.
    # Relative paths resolve from the server working directory.
    tools_config: str | None = None

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
