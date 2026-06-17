"""Configuration loader for the MCP server."""
# pylint: disable=inconsistent-quotes

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
# looks for .env in mcp_server directory
env_path = Path(__file__).parent / '.env'

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    logger.info("Loaded environment from %s", env_path)
else:
    logger.warning(".env file not found at %s - using system environment only",
                   env_path)

# Logging config
LOG_LEVEL = os.environ.get('COSCIENTIST_MCP_LOG_LEVEL') or os.environ.get(
    'LOG_LEVEL', 'INFO')
LOG_LEVEL = LOG_LEVEL.upper()
