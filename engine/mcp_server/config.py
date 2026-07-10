"""Configuration loader for the MCP server."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
# looks for .env in mcp_server directory
# Co-located .env (not the engine's) so this server can run standalone,
# e.g. via `uvicorn mcp_server.server:app`, without the engine's own env.
env_path = Path(__file__).parent / ".env"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    logger.info("Loaded environment from %s", env_path)
else:
    # Not fatal: deployments (e.g. Docker/Railway) may inject env vars
    # directly instead of shipping a .env file.
    logger.warning(
        ".env file not found at %s - using system environment only", env_path
    )

# Logging config
# COSCIENTIST_MCP_LOG_LEVEL takes precedence over the generic LOG_LEVEL so
# this server's verbosity can be tuned independently of other components
# sharing the same environment; defaults to INFO if neither is set.
LOG_LEVEL = os.environ.get("COSCIENTIST_MCP_LOG_LEVEL") or os.environ.get(
    "LOG_LEVEL", "INFO"
)
LOG_LEVEL = LOG_LEVEL.upper()
