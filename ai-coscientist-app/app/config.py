"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Configuration
    # model_name: worker model — generate, review, ranking, reflection, evolve, proximity,
    #   literature_review. High-volume, runs many times per iteration. Use a fast/cheap model.
    model_name: str = "gemini/gemini-2.5-flash"
    # supervisor_model_name: strategic model — supervisor (research planning) and meta_review
    #   (final report synthesis). Runs once or twice per iteration. Use a stronger model.
    #   If None, falls back to model_name (single-model mode for testing / cost saving).
    supervisor_model_name: str | None = None
    gemini_api_key: str = ""

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # PubMed/Entrez Configuration (optional)
    entrez_email: str = ""
    entrez_api_key: str = ""

    # MCP Server Configuration (optional, for literature review tools)
    mcp_server_url: str = "http://localhost:8888/mcp"

    # open-coscientist Configuration (van be overriden during runtime/UI)
    max_iterations: int = 3
    initial_hypotheses_count: int = 5
    evolution_max_count: int = 2

    # Literature Review Configuration
    coscientist_lit_review_papers_count: int = 10

    # Cache Configuration
    coscientist_cache_enabled: bool = True
    coscientist_cache_dir: str = "./cache"

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


settings = Settings()

