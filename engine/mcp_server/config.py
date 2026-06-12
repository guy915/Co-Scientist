# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# load environment variables from .env file
# looks for .env in mcp_server directory
env_path = Path(__file__).parent / '.env'

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    logger.info(f"Loaded environment from {env_path}")
else:
    logger.warning(f".env file not found at {env_path} - using system environment only")

# logging config
LOG_LEVEL = os.environ.get('COSCIENTIST_MCP_LOG_LEVEL') or os.environ.get('LOG_LEVEL', 'INFO')
LOG_LEVEL = LOG_LEVEL.upper()
