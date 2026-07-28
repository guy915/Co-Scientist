"""Constants and configuration values for Co-Scientist.

Centralizes magic numbers and configuration values for better maintainability.
"""

import hashlib
import logging
from typing import Final

logger = logging.getLogger(__name__)

# Literature review status markers
# Sentinel string stored in place of a synthesis when the literature-review
# node fails outright; downstream generation nodes check for this value to
# skip citation/grounding logic rather than treating the marker as content.
LITERATURE_REVIEW_FAILED: Final = "__LIT_REVIEW_FAILED__"
"""Marker indicating literature review failed and should not be used for
generation.
"""

# Elo rating system parameters
# Seed rating assigned to every newly generated hypothesis (nodes/generation/
# citations.py) before it has played any tournament matches in ranking.py.
INITIAL_ELO_RATING: Final = 1200
"""Initial Elo rating for new hypotheses."""

# Standard chess-style K-factor: how much a single match win/loss moves a
# hypothesis's Elo rating. Consumed by ranking.calculate_elo_update.
ELO_K_FACTOR: Final = 24
"""K-factor for Elo rating updates (higher = more volatile ratings)."""

# Debate depth for a tournament matchup (paper invariant SSR §4, §12): top-
# ranked comparisons use a multi-turn scientific debate, lower-ranked ones a
# single-turn comparison. A matchup is "top-ranked" when at least one
# hypothesis is at or above the pool's median Elo. The depth is a documented
# clone choice (Google specifies "multi-turn" but not the count).
MULTI_TURN_DEBATE_TURNS: Final = 2
"""Number of debate turns for a top-ranked matchup (clone-defined).

Sets the tournament's wall clock outright. Turns are serial -- each re-reads
the transcript so far -- while the matchups of a wave are judged
concurrently, so a wave costs this many call latencies no matter how wide it
is. Ranking is the run's highest-volume LLM stage, which makes this the
single most expensive number in the pipeline.

Lowered from three. Two is the smallest depth that still spends real
test-time compute *and* keeps the position-bias guard intact: the turns
present the pair in opposite A/B orders, so a two-turn agreement is a
verdict both orderings reached independently, which is the property the
depth exists to buy. What the third turn added was a tiebreak; a split now
resolves through the identity-stable balanced fallback in
``_balanced_invalid_fallback`` instead, which alternates across matchups and
so does not bias the tournament in either hypothesis's favour.
"""

SINGLE_TURN_DEBATE_TURNS: Final = 1
"""Number of turns for a lower-ranked (single-turn) matchup."""

ELO_UPSET_MARGIN: Final = 100
"""Pre-match Elo lead by which the loser must have exceeded the winner for a
judged matchup to be classified an "upset" (see ``ranking.match_tier``)."""

TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS: Final = 2
"""Matches every rankable hypothesis is *guaranteed*, budget notwithstanding.

A rating built from one match is a coin flip, not a measurement: from the
flat 1200 seed a single result has exactly two possible outcomes, so every
idea that played once reports one of the same two numbers. Two is the floor
at which an idea has a win-loss record.

This is the number the matchmaker's ``min_coverage`` and the ranking budget's
coverage floor both mean, and they must not drift: they were 2 and 1
respectively, so the budget guaranteed one match while the matchmaker was
trying to buy two. Late-arriving ideas -- everything evolution and the second
generation wave add -- therefore got exactly one match each, and a production
run ended with six ideas tied at 1212 and seven at 1188, presented as a
ranking.
"""

TOURNAMENT_MATCHES_PER_HYPOTHESIS: Final = 3
"""Matches each rankable hypothesis is budgeted over the whole run.

The tournament budget has to scale with the pool, because the pool is not
fixed: evolution keeps adding ideas after the first ranking cycle. Against a
flat per-tier ceiling the per-idea coverage therefore collapsed as a run
progressed -- a production run ended with twelve of its eighteen rankable
ideas having played exactly one match each, which at ``ELO_K_FACTOR`` from a
flat 1200 seed leaves exactly two reachable ratings (1212 and 1188). The
report then showed a dozen ideas tied at two values and presented that as a
ranking.

Three is the smallest count that gives every idea a win-loss *record* rather
than a single coin flip, and it costs about one extra ranking wave per tier
(matchups within a wave are judged concurrently -- see ``RANKING_WAVE_SIZE``),
not one call per extra match.
"""

# LLM API parameters
# These four token budgets are the base values that scaled_max_tokens() below
# scales up for count-dependent calls (e.g. batch review, evolution); simple
# single-hypothesis calls use them directly.
DEFAULT_MAX_TOKENS: Final = 4000
"""Default max tokens for standard LLM calls."""

EXTENDED_MAX_TOKENS: Final = 8000
"""Max tokens for detailed responses (reviews, evolution)."""

LONG_MAX_TOKENS: Final = 10000
"""Max tokens for complex multi-hypothesis operations."""

THINKING_MAX_TOKENS: Final = 18000
"""Max tokens for extended thinking + long responses."""

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

RANKING_WAVE_SIZE: Final = 12
"""Matchups one durable ranking task judges concurrently.

Ranking gets its own bound rather than sharing MAX_CONCURRENT_LLM_CALLS
because its fan-out is the tournament's whole shape, not an incidental
batch. A wave is judged inside a single durable task, so widening it adds
no task leases and no SQLite writes -- it only decides how many matchups
share one Elo snapshot.

Sized so a standard tier's 12-match pass fits in one wave and an ultra
tier's 32 fits in three. The cost is adaptation: every pairing in a wave
is drawn from the same snapshot, so ratings re-adapt at wave boundaries
rather than after each match. That trade is why this is not simply
unbounded.
"""

RANKING_WAVE_MIN_SIZE: Final = 3
"""Width ranking falls back to once the provider starts throttling.

A wave wider than the provider will serve does not run faster; the extra
calls spend their time asleep in backoff, and the burst is what provoked
the throttling in the first place.
"""

# Workflow defaults
DEFAULT_MAX_ITERATIONS: Final = 1
"""Default number of refinement iterations."""

# Debate generation parameters
DEBATE_MAX_TURNS: Final = 3
"""Ceiling on debate turns; a converged panel stops before reaching it.

The prompt asks the panel to declare convergence by writing "HYPOTHESIS",
and ``debate._debate_converged`` reads that signal, so this bounds a debate
that never agrees rather than sizing every debate.

This is the deepest serial chain in a run and therefore sets the generation
stage's wall clock outright. Turns cannot overlap -- each one is handed the
previous turn's reply as its transcript -- so the stage costs this many
call latencies however many debates run at once, and however many workers
the cohort has. Widening concurrency cannot touch it; only the ceiling can.

Lowered from five. The non-final turns are undifferentiated: they share one
prompt and one instruction set, so a turn is another round of the same
argument rather than a distinct stage, and the prompt's own termination
condition puts convergence at "typically 3-5 conversational turns". Two
rounds of discussion followed by the schema-constrained synthesis keeps the
panel's disagreement and drops the tail it spends restating agreement.
"""

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
# Values are not strictly monotonic across a run: the graph runs
# deep-verification (81-84) between ranking and proximity (75-85), so
# reported progress steps back from 84 to 75 when proximity starts.
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
PROGRESS_META_REVIEW_START: Final = 45
PROGRESS_META_REVIEW_COMPLETE: Final = 50
PROGRESS_EVOLVE_START: Final = 55
PROGRESS_EVOLVE_COMPLETE: Final = 60
PROGRESS_DEEP_VERIFICATION_START: Final = 81
PROGRESS_DEEP_VERIFICATION_COMPLETE: Final = 84
PROGRESS_PROXIMITY_START: Final = 75
PROGRESS_PROXIMITY_COMPLETE: Final = 85
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

# Selected in nodes/literature_review.py based on the COSCIENTIST_DEV_MODE
# env var; dev mode ignores any per-run override and always uses the
# smaller _DEV budget for faster iteration.
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
# in nodes/generation/literature_tools/. Each LLM tool call, whether it reads
# a paper or emits a draft, counts as one iteration.


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

DRAFT_MAX_TOKENS_CAP: Final = 16000
"""Upper limit for the draft-phase output budget."""

VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS: Final = 2500
"""Extra validation-synthesis output tokens per hypothesis in the batch."""

VALIDATION_SYNTHESIS_MAX_TOKENS_CAP: Final = 20000
"""Upper limit for the validation-synthesis output budget."""
