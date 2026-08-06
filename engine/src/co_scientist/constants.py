"""Constants and configuration values for Co-Scientist.

Centralizes magic numbers and configuration values for better maintainability.
"""

import hashlib
from typing import Final

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

# LLM API parameters
# These four token budgets are the base values that scaled_max_tokens() below
# scales up for count-dependent calls (e.g. batch review, evolution); simple
# single-hypothesis calls use them directly.
#
# The first three sit below THINKING_FLOOR_MAX_TOKENS by design: they are
# answer budgets, which the floor replaces outright on a thinking model. Read
# them as what a call's answer costs, not as what the request carries. A
# *cap* below the floor is the case that needs deliberating -- see below.
DEFAULT_MAX_TOKENS: Final = 4000
"""Default max tokens for standard LLM calls."""

EXTENDED_MAX_TOKENS: Final = 8000
"""Max tokens for detailed responses (reviews, evolution)."""

LONG_MAX_TOKENS: Final = 10000
"""Max tokens for complex multi-hypothesis operations."""

THINKING_MAX_TOKENS: Final = 18000
"""Max tokens for extended thinking + long responses.

Also the value of ``THINKING_FLOOR_MAX_TOKENS`` below, by derivation rather
than coincidence: the floor was set to the budget these nodes had already
proven in production. Changing this number therefore moves the floor under
every other thinking call in the engine, so change the two together
deliberately or not at all.
"""

THINKING_FLOOR_MAX_TOKENS: Final = THINKING_MAX_TOKENS
"""Smallest total budget any thinking-enabled call may be sent with.

On the providers this engine uses, ``max_tokens`` bounds reasoning *plus*
answer, not the answer alone -- the chain of thought is billed and counted
against the same allowance even though it is returned in a separate field.
A budget sized for the answer therefore lets a long chain of thought consume
the entire allowance, and the call returns ``finish_reason="length"`` with
empty content: paid for in full, worth nothing, and retried four more times
by ``call_llm_json``.

The floor is set to ``THINKING_MAX_TOKENS`` because that is the budget the
three nodes that were sized for thinking from the start (ranking debate,
meta-review, research overview) already run against in production, so
raising every other thinking call to it introduces no value this deployment
has not already proven. It is a floor rather than a per-call reserve added
on top precisely to avoid pushing the already-generous scaled batch caps
(``REVIEW_BATCH_MAX_TOKENS_CAP`` and friends) into untested territory: a
call whose budget already exceeds the floor is left exactly as its node
sized it.

It applies only where the call actually reasons, which is decided by the
model, not the call site: ``_apply_thinking_args`` returns early for a model
with no thinking mode, and no first-party call site passes
``enable_thinking=False``. So every budget in this module lives in two
regimes at once -- superseded by the floor on the DeepSeek-family models
this engine deploys on, and operative as written on any other provider. That
is why a cap below the floor is not merely inert: it is a ceiling that binds
on one provider and silently does not on another. The caps block at the end
of this module keeps every cap above the floor so each one means the same
thing in both regimes; ``tests/test_token_budget_floor.py`` pins that.
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

# Token-budget scaling for count-dependent LLM calls. Each per-node pair
# below feeds scaled_max_tokens() at exactly one call site; the cap keeps
# large batches from requesting unbounded output budgets.


def scaled_max_tokens(
    base: int, count: int, *, per_item: int, cap: int, free_count: int = 0
) -> int:
    """Scales an LLM output-token budget with the number of items in a call.

    Computes ``min(base + max(0, count - free_count) * per_item, cap)``:
    the base budget covers the first ``free_count`` items, every further
    item adds ``per_item`` tokens, and ``cap`` bounds the total.

    Deliberately ignorant of ``THINKING_FLOOR_MAX_TOKENS``, so a returned
    value can still be below it. Raising the result here, or rejecting a
    ``cap`` beneath the floor, needs the one fact this function does not
    have: whether the call reasons, which is a property of the model.
    Applying the floor blind would raise budgets on providers that never
    reason and have tighter output ceilings of their own (see
    ``VALIDATION_SYNTHESIS_BATCH_SIZE``), and would give the floor a second
    enforcement point that cannot see what the first one sees -- which is
    how two copies of one rule drift apart. The floor keeps its single site
    in ``_apply_thinking_args``; "no cap below the floor" is a static
    property of the constants below, so a test pins it instead.

    Args:
        base: Base token budget for the call.
        count: Number of items (hypotheses, context entries, ...) in the call.
        per_item: Extra tokens granted per item beyond ``free_count``.
        cap: Hard upper limit for the returned budget.
        free_count: Number of items already covered by ``base``.

    Returns:
        The scaled token budget, never exceeding ``cap``.
    """
    return min(base + max(0, count - free_count) * per_item, cap)


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


# Scaled per-node budgets, one group per scaled_max_tokens call site. Every
# *_CAP below is above THINKING_FLOOR_MAX_TOKENS by rule, not by accident: a
# cap under the floor is overwritten wherever the model reasons and enforced
# wherever it does not, i.e. a ceiling the deployed configuration can never
# impose. Above the floor, each cap is the operative ceiling in both regimes.
#
# A cap is a runaway backstop, not a target. Counts come from the run tier's
# initial_hypotheses_count (4/8/12/16, raisable per request), and at all of
# those every scaled value here lands under both its cap and the floor -- so
# on a thinking model these calls go out at the floor. Size a cap for the
# pathological count, never for a plausible one, and keep it above the floor;
# tests/test_token_budget_floor.py enforces the last part.

REVIEW_BATCH_TOKENS_PER_HYPOTHESIS: Final = 1500
"""Extra batch-review output tokens per hypothesis beyond the free count."""

REVIEW_BATCH_FREE_HYPOTHESES: Final = 5
"""Hypotheses already covered by the batch-review base budget."""

REVIEW_BATCH_MAX_TOKENS_CAP: Final = 24000
"""Upper limit for the batch-review output budget."""

EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS: Final = 800
"""Extra evolution output tokens per context hypothesis (max 15 sampled)."""

EVOLVE_MAX_TOKENS_CAP: Final = 20000
"""Upper limit for the evolution output budget."""

DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS: Final = 4000
"""Extra final-debate-turn output tokens per generated hypothesis."""

DEBATE_FINAL_TURN_MAX_TOKENS_CAP: Final = 20000
"""Upper limit for the final-debate-turn output budget."""

DRAFT_TOKENS_PER_HYPOTHESIS: Final = 200
"""Extra draft-phase output tokens per requested hypothesis."""

DRAFT_MAX_TOKENS_CAP: Final = 20000
"""Upper limit for the draft-phase output budget.

Raised from 16000, which was the one cap that sat below
``THINKING_FLOOR_MAX_TOKENS``. The draft agent runs on the tool loop, which
always reasons, so on every deployed model that cap was overwritten by the
floor before the request went out, while on a non-reasoning provider it
stayed enforced -- the same constant meaning two different things depending
on who served the call.

Nothing about the draft call argues for a number below its siblings. A draft
is the cheapest thing this engine generates: ``DRAFT_TOKENS_PER_HYPOTHESIS``
prices one at 200 tokens, so even the largest tier's 16 drafts ask for 11200
against an 8000 base that already dominates the sum. The cap is unreachable
at any count a run tier produces (it takes 60 drafts to reach this value, 40
to reach the old one), which is what makes it a backstop against a caller
raising ``initial_hypotheses_count`` rather than a ceiling any real run
meets. Since no real run is affected either way, the value is chosen to
agree with the other generation-family caps and to clear the floor.
"""

VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS: Final = 2500
"""Extra validation-synthesis output tokens per hypothesis in the batch."""

VALIDATION_SYNTHESIS_MAX_TOKENS_CAP: Final = 20000
"""Upper limit for the validation-synthesis output budget."""
