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
