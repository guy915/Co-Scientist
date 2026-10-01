"""Cache-tier constants, split out of ``constants/__init__.py`` (size cap).

Re-exported from ``co_scientist.constants``, the same pattern
``constants.tournament`` uses for the Elo-tournament constants -- one
import path for every constant, regardless of which module actually
defines it.
"""

from typing import Final

# Overridable via COSCIENTIST_CACHE_TTL_SECONDS. Without an expiry, a
# too-aggressive cache silently replays stale output forever instead of
# exploring -- the defect caching-on-by-default risks per AGENTS.md -- so
# entries age out even when nothing about the key changed. A value of zero
# (or unset/negative) disables expiry, matching the "0 disables" convention
# every other wall-clock ceiling in this codebase uses (see
# llm.request.completion.LLM_TIMEOUT_ENV). Checked against the cache file's own
# mtime, not a value stored in the entry, so no cache-format migration is
# needed.
DEFAULT_CACHE_TTL_SECONDS: Final = 7 * 24 * 60 * 60
"""Default age, in seconds, after which a cached entry is treated as a miss."""

# Bump this when a change to call_llm/call_llm_json/call_llm_with_tools
# alters how a cached response should be interpreted without changing the
# prompt text itself (e.g. a parsing/interpretation fix) -- mirrors
# agents/generation/literature_review/node.py's
# _LITERATURE_CACHE_SCHEMA_VERSION, the node-cache tier's version of the
# same escape hatch. Every LLMCacheRequest carries it by default, so bumping
# it invalidates the whole LLM response cache without any call site change.
LLM_CACHE_SCHEMA_VERSION: Final = 1
"""Schema version folded into every LLM response cache key."""
