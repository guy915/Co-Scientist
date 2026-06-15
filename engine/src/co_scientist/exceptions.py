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
"""Domain-specific exception hierarchy for the co-scientist engine.

All errors raised by engine code inherit from ``CoScientistError`` so callers
can catch the entire family with a single ``except`` clause while still being
able to distinguish individual failure modes.
"""


class CoScientistError(Exception):
    """Base class for all errors raised by the co-scientist engine."""


class ConfigError(CoScientistError):
    """The tool registry or configuration is not initialized or invalid."""


class GenerationError(CoScientistError):
    """Hypothesis generation or debate failed to produce a result."""


class ResponseParseError(CoScientistError):
    """An LLM response could not be parsed or repaired into expected JSON."""


class ToolError(CoScientistError):
    """A tool provider or tool execution failed (MCP or Python tools)."""


class LiteratureReviewError(CoScientistError):
    """A literature-review or MCP query failed."""


class LLMError(CoScientistError):
    """An LLM call failed."""
