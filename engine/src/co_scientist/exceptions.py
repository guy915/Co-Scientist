"""Domain-specific exception hierarchy for the co-scientist engine.

All errors raised by engine code inherit from ``CoScientistError`` so callers
can catch the entire family with a single ``except`` clause while still being
able to distinguish individual failure modes.
"""


# Flat hierarchy by design: each subclass below sits directly under this
# base rather than under one another, since they represent independent
# failure domains (config, generation, response parsing) rather than a
# taxonomy of one error specializing another.
class CoScientistError(Exception):
    """Base class for all errors raised by the co-scientist engine."""


# Raised by ToolRegistry and the MCP tool provider (config/registry.py,
# tools/provider.py) when tool configuration is missing or not initialized.
class ConfigError(CoScientistError):
    """The tool registry or configuration is not initialized or invalid."""


# Raised by the debate and review nodes (nodes/generation/debate.py,
# nodes/review.py) once retries are exhausted without usable output.
class GenerationError(CoScientistError):
    """Hypothesis generation or debate failed to produce a result."""


# Raised by the literature-tools draft/validate helpers when an LLM response
# cannot be coerced into the expected structured JSON after repair attempts.
class ResponseParseError(CoScientistError):
    """An LLM response could not be parsed or repaired into expected JSON."""
