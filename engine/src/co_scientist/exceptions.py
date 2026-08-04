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


# Raised by the debate and review nodes (agents/generation/debate.py,
# agents/reflection/review.py) once retries are exhausted without usable
# output.
class GenerationError(CoScientistError):
    """Hypothesis generation or debate failed to produce a result."""


# Raised by the literature-tools draft/validate helpers when an LLM response
# cannot be coerced into the expected structured JSON after repair attempts.
class ResponseParseError(CoScientistError):
    """An LLM response could not be parsed or repaired into expected JSON."""


# Raised by call_llm when a provider accepts a request and then never
# answers. Distinct from a generic call failure because it is deliberately
# not retried: the JSON retry loop re-raises it immediately (see
# llm_json_retry._run_json_attempt), since a provider that has stopped
# responding will not answer a second identical request any sooner, and
# retrying multiplies one stalled call by the attempt count.
class LLMTimeoutError(CoScientistError):
    """An LLM call exceeded its wall-clock budget without responding."""


# Raised when an MCP tool accepts a call and never returns. The LLM timeout
# covers litellm.acompletion only, which left tool invocations unbounded: a
# server whose stream broke mid-call parked the awaiting run forever, with no
# error, no retry and nothing in the log after the request went out. Callers
# that can degrade (per-source literature search, the availability probe)
# catch this and carry on without that source.
class MCPToolTimeoutError(CoScientistError):
    """An MCP tool call exceeded its wall-clock budget without responding."""
