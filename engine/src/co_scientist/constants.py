"""Constants and configuration values for Co-Scientist.

Centralizes magic numbers and configuration values for better maintainability.
"""

import hashlib
import re
from typing import Final

# Every ``max_tokens`` budget -- the answer bases, the thinking floor that
# supersedes them, the escalation budget, and the per-node scaling inputs
# and caps -- moved to a sibling module for the same reason: each of them
# only means what it says relative to the floor, so they read as one
# subject and were split as one. Re-exported here so
# ``co_scientist.constants`` stays the single import path; the tournament
# block below explains the redundant ``X as X`` alias form and why the
# longest names cannot fit it in 80 columns.
from co_scientist.constants_tokens import (
    BUDGET_ESCALATION_MAX_INCREMENT as BUDGET_ESCALATION_MAX_INCREMENT,
)
from co_scientist.constants_tokens import (
    BUDGET_ESCALATION_MAX_TOKENS as BUDGET_ESCALATION_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    DEBATE_FINAL_TURN_MAX_TOKENS_CAP as DEBATE_FINAL_TURN_MAX_TOKENS_CAP,
)
from co_scientist.constants_tokens import (
    DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS as DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS,  # noqa: E501
)
from co_scientist.constants_tokens import (
    DEEP_HYPOTHESIS_MAX_TOKENS as DEEP_HYPOTHESIS_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    DEFAULT_MAX_TOKENS as DEFAULT_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    DRAFT_MAX_TOKENS_CAP as DRAFT_MAX_TOKENS_CAP,
)
from co_scientist.constants_tokens import (
    DRAFT_TOKENS_PER_HYPOTHESIS as DRAFT_TOKENS_PER_HYPOTHESIS,
)
from co_scientist.constants_tokens import (
    EVOLVE_MAX_TOKENS_CAP as EVOLVE_MAX_TOKENS_CAP,
)
from co_scientist.constants_tokens import (
    EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS as EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS,  # noqa: E501
)
from co_scientist.constants_tokens import (
    EXTENDED_MAX_TOKENS as EXTENDED_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    KNOWLEDGE_BASE_MAX_TOKENS as KNOWLEDGE_BASE_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    LONG_MAX_TOKENS as LONG_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    MINIMAL_REASONING_MAX_TOKENS as MINIMAL_REASONING_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    RESEARCH_OVERVIEW_MAX_TOKENS as RESEARCH_OVERVIEW_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    REVIEW_BATCH_FREE_HYPOTHESES as REVIEW_BATCH_FREE_HYPOTHESES,
)
from co_scientist.constants_tokens import (
    REVIEW_BATCH_MAX_TOKENS_CAP as REVIEW_BATCH_MAX_TOKENS_CAP,
)
from co_scientist.constants_tokens import (
    REVIEW_BATCH_TOKENS_PER_HYPOTHESIS as REVIEW_BATCH_TOKENS_PER_HYPOTHESIS,
)
from co_scientist.constants_tokens import (
    THINKING_FLOOR_MAX_TOKENS as THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    THINKING_MAX_TOKENS as THINKING_MAX_TOKENS,
)
from co_scientist.constants_tokens import (
    VALIDATION_SYNTHESIS_MAX_TOKENS_CAP as VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
)
from co_scientist.constants_tokens import (
    VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS as VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,  # noqa: E501
)
from co_scientist.constants_tokens import (
    scaled_max_tokens as scaled_max_tokens,
)

# Everything the Elo tournament is shaped by -- seed rating, K-factor, debate
# depth, per-hypothesis match budgets, wave width -- moved to a sibling
# module; each of those values carries its own incident history, and together
# they were the largest single subject in this file. Every name is re-exported
# so ``co_scientist.constants`` stays the one import path for all of them.
# The redundant ``X as X`` is what marks a re-export under mypy's strict
# no-implicit-reexport; the last name below is long enough that the alias form
# cannot fit in 80 columns, and renaming it would break every caller.
from co_scientist.constants_tournament import (
    ELO_K_FACTOR as ELO_K_FACTOR,
)
from co_scientist.constants_tournament import (
    ELO_UPSET_MARGIN as ELO_UPSET_MARGIN,
)
from co_scientist.constants_tournament import (
    INITIAL_ELO_RATING as INITIAL_ELO_RATING,
)
from co_scientist.constants_tournament import (
    RANKING_WAVE_MIN_SIZE as RANKING_WAVE_MIN_SIZE,
)
from co_scientist.constants_tournament import (
    RANKING_WAVE_SIZE as RANKING_WAVE_SIZE,
)
from co_scientist.constants_tournament import (
    SINGLE_TURN_DEBATE_TURNS as SINGLE_TURN_DEBATE_TURNS,
)
from co_scientist.constants_tournament import (
    TOURNAMENT_MATCHES_PER_HYPOTHESIS as TOURNAMENT_MATCHES_PER_HYPOTHESIS,
)
from co_scientist.constants_tournament import (
    TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS as TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS,  # noqa: E501
)

# Literature review status markers
# Sentinel string stored in place of a synthesis when the literature-review
# node fails outright; downstream generation nodes check for this value to
# skip citation/grounding logic rather than treating the marker as content.
LITERATURE_REVIEW_FAILED: Final = "__LIT_REVIEW_FAILED__"
"""Marker indicating literature review failed and should not be used for
generation.
"""

LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS: Final = 8000
"""Cap on the deterministic roll-up ``_phase4_synthesize`` builds when the
synthesis LLM call fails but per-paper analyses exist (see
``agents/generation/literature_review/synthesis.py``). Comparable to what
the real synthesis call's own ``EXTENDED_MAX_TOKENS`` output budget
typically produces, so a large paper pool cannot make the fallback blow a
downstream prompt's token budget the way an unbounded concatenation would.
"""


# Temperature settings
LOW_TEMPERATURE: Final = 0.3
"""Low temperature for consistent, deterministic responses (ranking)."""

MEDIUM_TEMPERATURE: Final = 0.5
"""Medium temperature for balanced creativity and consistency."""

HIGH_TEMPERATURE: Final = 0.7
"""Higher temperature for diverse, creative responses (generation, evolution,
review).
"""

# Review strategy threshold
# review.py picks its strategy from this: at or below the threshold, all
# hypotheses are reviewed together in one comparative call (cheaper, and
# lets the model contrast them); above it, each hypothesis is reviewed
# independently and in parallel to keep any single call's output bounded.
COMPARATIVE_BATCH_THRESHOLD: Final = 5
"""Maximum hypotheses for comparative batch review. Above this, use parallel
individual reviews.
"""

# Initial review gate bands.
# These mirror the 1-10 rubric the review prompts hand the model
# (prompts/templates/review.md, review_batch.md) rather than setting a
# separate policy, so the gate and the scores it reads mean the same thing:
#   1-2   fundamentally flawed, not viable
#   3-4   major deficiencies, needs substantial rework
#   5-6   moderate quality, significant room for improvement
#   7-10  good to outstanding
# Only the first band blocks. The batch prompt also *requires* the model to
# spread scores across the pool ("they should receive DIFFERENT scores"), so
# a relative low scorer is manufactured on every run whatever the absolute
# quality -- which is exactly why the blocking band has to be the one the
# rubric calls non-viable, not merely the bottom of the distribution.
NOT_VIABLE_SCORE: Final = 2
"""At or below this, an idea is barred from the tournament entirely."""

NEEDS_REVISION_SCORE: Final = 4
"""At or below this (but above NOT_VIABLE_SCORE), an idea still ranks and
publishes; it is only held back from the deep-review cascade.
"""

_NEUTRAL_SCORE: Final = 5
"""Stand-in for a score the review omitted, at the bottom of "moderate".

Deliberately not 0: a missing key is a defect in the review, and reading it
as the worst possible score silently disqualified the idea.
"""

# Concurrency limits
# Shared semaphore bound for ranking, deep-verification, and generation
# coordinator fan-out so parallel LLM calls do not trip provider rate limits.
MAX_CONCURRENT_LLM_CALLS: Final = 5
"""Maximum concurrent LLM API calls to avoid rate limits."""

# Workflow defaults
DEFAULT_MAX_ITERATIONS: Final = 1
"""Default number of refinement iterations."""

DEFAULT_INITIAL_HYPOTHESES_COUNT: Final = 5
"""Default number of initial hypotheses to generate."""

DEFAULT_EVOLUTION_MAX_COUNT: Final = 3
"""Default number of top hypotheses to evolve and keep."""

# Deep-verification review (probing questions on the most promising hypotheses).
# deep_verification.py ranks hypotheses by Elo and only probes the leaders,
# since the LLM-driven questioning is expensive relative to review/ranking.
DEEP_VERIFICATION_TOP_K: Final = 3
"""Number of top-Elo hypotheses to subject to deep verification."""

# Research overview synthesizes the strongest hypotheses into a roadmap.
RESEARCH_OVERVIEW_TOP_K: Final = 10
"""Number of top-Elo hypotheses to synthesize into the research overview."""

# Similarity thresholds
# Used by evolve.py's dedup check: hypotheses whose similarity to an existing
# one exceeds this are treated as redundant rather than a genuine variant.
DUPLICATE_SIMILARITY_THRESHOLD: Final = 0.95
"""Similarity threshold above which hypotheses are considered duplicates (0-1).
"""

# Progress tracking
# Percent-complete checkpoints (0-100) each node emits as progress events.
# Numbered for the order the durable path actually executes, so a run's
# first pass never reports a smaller value after a larger one (pinned by
# tests/test_progress_order.py); the orchestrator decision and proximity
# share one flat value, and loop re-entries re-emit smaller values by
# design because the values name phases, not a completion fraction.
PROGRESS_SUPERVISOR_START: Final = 5
PROGRESS_SUPERVISOR_COMPLETE: Final = 10
PROGRESS_GENERATE_START: Final = 15
PROGRESS_GENERATE_COMPLETE: Final = 20
PROGRESS_REFLECTION_START: Final = 21
PROGRESS_REFLECTION_COMPLETE: Final = 24
PROGRESS_REVIEW_START: Final = 25
PROGRESS_REVIEW_COMPLETE: Final = 40
PROGRESS_SAFETY_SCREEN_START: Final = 41
PROGRESS_SAFETY_SCREEN_COMPLETE: Final = 42
PROGRESS_TOURNAMENT_START: Final = 55
PROGRESS_TOURNAMENT_COMPLETE: Final = 70
# Deep verification probes the post-tournament leaders, so its band sits
# between the tournament and the post-tournament decision (audit E9).
PROGRESS_DEEP_VERIFICATION_START: Final = 71
PROGRESS_DEEP_VERIFICATION_COMPLETE: Final = 72
# The post-tournament band; the shared value is explained above.
PROGRESS_ORCHESTRATOR_DECISION: Final = 75
PROGRESS_PROXIMITY_START: Final = 75
PROGRESS_PROXIMITY_COMPLETE: Final = 75
# Evolve enters after the post-tournament band, so its checkpoints sit
# above it even though the task re-enters the review pipeline.
PROGRESS_META_REVIEW_START: Final = 80
PROGRESS_META_REVIEW_COMPLETE: Final = 82
PROGRESS_EVOLVE_START: Final = 85
PROGRESS_EVOLVE_COMPLETE: Final = 87
PROGRESS_RESEARCH_OVERVIEW_START: Final = 95
PROGRESS_RESEARCH_OVERVIEW_COMPLETE: Final = 99

# Cache defaults
# Overridable via COSCIENTIST_CACHE_DIR / COSCIENTIST_CACHE_ENABLED (see
# cache.py); caching covers both raw LLM responses and node-level results.
DEFAULT_CACHE_DIR: Final = ".coscientist_cache"
"""Default directory for LLM response caching."""

DEFAULT_CACHE_ENABLED: Final = True
"""Whether caching is enabled by default (controls both LLM and node-level
caching).
"""

# Selected in agents/generation/literature_review/run_config.py from the
# run's dev_mode state (resolved at the generator boundary from opts or
# COSCIENTIST_DEV_MODE); dev mode ignores any per-run override and always
# uses the smaller _DEV budget for faster iteration.
LITERATURE_REVIEW_PAPERS_COUNT: Final = 10
"""default number of papers to collect from MCP servers/tools when a run does
not specify a per-run count."""

LITERATURE_REVIEW_PAPERS_COUNT_DEV: Final = 4
"""number of papers in dev mode for faster iteration"""

LITERATURE_REVIEW_RECENCY_YEARS: Final = 7
"""filter papers to last N years for better relevance (0 = no filter)"""

LITERATURE_REVIEW_MAX_QUERIES: Final = 3
"""Maximum search queries per literature pass.

Shared by the literature-review node's Phase 1 query cap and comprehensive
reflection's per-hypothesis query cap so both fan-outs stay bounded
identically.
"""

# Generate node literature tool usage parameters
# The next two functions size the tool-calling agent's iteration budget for
# the two-phase (draft, then validate) generation-with-literature-tools flow
# in agents/generation/literature_tools/. Each LLM tool call, whether it
# reads a paper or emits a draft, counts as one iteration.


def get_draft_max_iterations(hypotheses_count: int) -> int:
    """Calculate draft iterations based on hypotheses count.

    formula: base iterations (for reading papers) + per-hypothesis budget
    - need to read papers: 5 base iterations
    - need to draft each hypothesis: ~2 iterations per hypothesis
    - cap at 30 to prevent runaway

    Examples:
    - 3 hypotheses: 5 + 6 = 11 iterations
    - 10 hypotheses: 5 + 20 = 25 iterations
    - 50 hypotheses: 5 + 100 = 30 (capped)
    """
    return min(5 + (hypotheses_count * 2), 30)


def get_validate_max_iterations(hypotheses_count: int) -> int:
    """Calculate validate iterations based on hypotheses count.

    formula: per-hypothesis budget for search + read + refine
    - each hypothesis needs: search (2) + read papers (3-5) + refine (2-3)
    - allow extra for internal iteration (Option B - agent iterates within
    single call)
    - ~10 iterations per hypothesis
    - cap at 50 to prevent runaway

    Examples:
    - 3 hypotheses: 30 iterations
    - 10 hypotheses: 50 (capped)
    - 50 hypotheses: 50 (capped)
    """
    return min(hypotheses_count * 10, 50)


GENERATE_LIT_TOOL_MAX_PAPERS: Final = 3
"""max papers to examine in draft/validate phase.."""

VALIDATION_SYNTHESIS_BATCH_SIZE: Final = 3
"""Hypotheses per validation synthesis call.

Smaller = less output per call, more reliable for models with tight output
token budgets (e.g. gemini-3-pro). Trade-off: more parallel API calls.
"""


def truncate(text: str, limit: int = 200, suffix: str = "...") -> str:
    """Truncates text to ``limit`` characters, appending ``suffix`` if cut.

    Args:
        text: The text to truncate.
        limit: Maximum length of the returned text before the suffix.
        suffix: Marker appended when the text is longer than ``limit``.

    Returns:
        The original text if within ``limit``, else its first ``limit``
        characters followed by ``suffix``.
    """
    return text[:limit] + suffix if len(text) > limit else text


PROMPT_PAPER_MAX_CHARS: Final = 200_000
"""Per-paper character budget for prompts that embed a whole paper."""

_PROMPT_TRUNCATION_MARKER: Final = "\n\n[... truncated for length ...]"
"""Marker appended when a paper is cut to the per-prompt budget."""


def truncate_for_prompt(
    text: str, max_chars: int = PROMPT_PAPER_MAX_CHARS
) -> str:
    """Truncates a paper's text to the per-prompt character budget.

    Bounds a prompt that embeds one whole paper -- the literature review's
    per-paper analysis and the tool-based path's per-paper novelty analysis
    -- regardless of how long the source fulltext is. Both cut at the same
    point and leave the same marker, so both live here.

    Args:
        text: Paper text (fulltext or abstract) destined for a prompt.
        max_chars: Maximum characters kept before the truncation marker.

    Returns:
        The text unchanged if within budget, else its first ``max_chars``
        characters followed by the truncation marker.
    """
    return truncate(text, max_chars, _PROMPT_TRUNCATION_MARKER)


# Author-year shapes copied verbatim from paper-qa's strip_citations
# (Apache-2.0; src/paperqa/utils.py), which is also the source of the
# leftover-double-space behavior pinned in the tests. The bracket
# alternative is this codebase's own addition, for the numeric markers
# ("[12]", "[3,4]") that PubMed/Europe PMC abstracts use and paper-qa's
# regex does not cover. Requiring every bracket character to be a digit,
# comma, dash or space is what keeps it from ever matching our own
# "[C<n>]" reference keys -- a letter anywhere inside disqualifies the
# whole bracket.
_CITATION_MARKER_RE = re.compile(
    r"\b[\w\-]+\set\sal\.\s\([0-9]{4}\)"
    r"|\((?:[^)]*?[a-zA-Z][^)]*?[0-9]{4}[^)]*?)\)"
    r"|\[[0-9]+(?:\s*[,\u2013-]\s*[0-9]+)*\]",
    re.MULTILINE,
)


def strip_citation_markers(text: str) -> str:
    """Removes a retrieved paper's own inline citation markers.

    Retrieved abstracts and fulltext carry the *source* paper's own
    citations inline -- "(Smith et al. 2019)", "[12]" -- and a model
    drafting from that text can copy one into its own prose: a
    real-looking reference attached to a claim the cited source never
    made. This strips those markers before the text enters a prompt.

    Never call this on text before it is stored (an ``Article``, the
    database): a reader following a citation into the source needs the
    source as published, and citation classification compares claims
    against the real abstract. Only the prompt-bound copy is stripped.

    Args:
        text: Paper text (fulltext or abstract) destined for a prompt.

    Returns:
        The text with author-year and numeric-bracket citation markers
        removed. Our own ``[C<n>]`` reference keys are never matched.
    """
    return _CITATION_MARKER_RE.sub("", text)


def corpus_slug(research_goal: str) -> str:
    """Derives the on-disk corpus slug for a research goal.

    The literature-review and tool-based generation nodes share a warm PubMed
    corpus keyed by this slug, so every caller must derive it identically or
    the warm-start cache silently misses and papers are re-downloaded.

    Args:
        research_goal: The run's research goal text.

    Returns:
        A stable ``research_<hash>`` slug for the goal.
    """
    return "research_" + hashlib.md5(research_goal.encode()).hexdigest()[:8]
