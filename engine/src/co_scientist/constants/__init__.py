"""Shared engine defaults, token budgets, pricing and tournament constants."""

import hashlib
import re
from typing import Final

from co_scientist.llm.profile import ModelPrice, priced_routes

# Keyed by exact route name, so this lookup is case-sensitive, unlike a
# profile's capabilities. A model absent from it prices at zero (see
# ``estimate_cost_usd``) rather than raising or guessing -- a new or renamed
# model then degrades to "no cost tracked" instead of breaking telemetry for
# every call site that names it.
MODEL_PRICING: Final[dict[str, ModelPrice]] = priced_routes()


def estimate_cost_usd(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_prompt_tokens: int = 0,
) -> float:
    """Estimates one call's USD cost from its token counts.

    Args:
        model_name: Model name in litellm format.
        prompt_tokens: Prompt (input) tokens billed for the call.
        completion_tokens: Completion (output) tokens billed for the call,
            including any reasoning tokens the provider bills alongside it.
        cached_prompt_tokens: The share of ``prompt_tokens`` served from
            the provider's prompt cache. Priced at the model's cache-read
            rate and the remainder at the full input rate. Ignored for a
            model whose cache rate is unlisted, so an unmeasured model
            keeps costing exactly what it did before.

    Returns:
        The estimated cost in USD, or 0.0 for a model absent from
        ``MODEL_PRICING`` (an offline or unlisted model is zero-cost
        rather than an unpriced guess).
    """
    price = MODEL_PRICING.get(model_name)
    if price is None:
        return 0.0
    cached = 0
    if price.cached_prompt_usd_per_million:
        cached = max(0, min(cached_prompt_tokens, prompt_tokens))
    return (
        (prompt_tokens - cached) / 1_000_000 * price.prompt_usd_per_million
        + cached / 1_000_000 * price.cached_prompt_usd_per_million
        + completion_tokens / 1_000_000 * price.completion_usd_per_million
    )


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

DEEP_HYPOTHESIS_MAX_TOKENS: Final = 12000
"""Answer budget for the hypothesis-writing generation calls (K6).

The generation family's depth guidance asks for full mechanism
specificity, quantitative predictions, and complete experiment detail,
which costs more answer than the generic ``EXTENDED_MAX_TOKENS`` funds.
Sits below ``THINKING_FLOOR_MAX_TOKENS`` by design, the same way the
other answer budgets do: on a thinking model the floor replaces it, and
on a provider without a thinking mode it is the operative ceiling.
"""

RESEARCH_OVERVIEW_MAX_TOKENS: Final = 24000
"""Total budget for the terminal research-overview synthesis (K6).

Deliberately above ``THINKING_FLOOR_MAX_TOKENS``: the overview is the
one output asked to be a multi-paragraph research strategy document
plus an NIH Specific Aims page, so on a thinking model its chain of
thought and its long structured answer must both fit the same
allowance. A floor-sized budget funds the reasoning and leaves the
answer truncated -- the exact failure the thinking-budget gotcha
describes. 24000 matches the largest scaled batch cap already proven
in production. The floor only ever raises, so every other call is
unaffected.
"""

KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS: Final = 6000
"""Answer budget for the knowledge base's outline call (F8).

Replaces ``KNOWLEDGE_BASE_MAX_TOKENS``, a single 42000-token budget sized
from the published exemplar's own measured length (9,702 words, 19,084
cl100k tokens) on the reasoning that a budget covering the thinking floor
plus the answer makes the first attempt the one that answers. It never
did: that call failed in three consecutive production runs -- nine
attempts, no successes, while every 18000- and 24000-token call in the
same runs answered.

The ceiling that dooms it is the wall clock, not a model output limit.
``minimax/minimax-m3:free`` advertises 943,718 completion tokens and no
code clamps a request to any such number, so the request itself was
accepted every time. But ``COSCIENTIST_LLM_TIMEOUT_SECONDS`` bounds one
call at 600s, and the failing attempts measured 27-37 tokens/second
(10,080 tokens in 366s; 20,949 in 563s) -- 42,000 tokens is 1,100-1,500s
of generation at that rate. Both runs ended the retry loop on
``LLMTimeoutError``; the upstream had already dropped the stream itself
(``finish_reason="error"``) at 366-563s on the attempts before it. So the
budget was never the lever: a call this long cannot be served, and
``BUDGET_ESCALATION_MAX_INCREMENT`` would only have made a later attempt
longer still.

The section is therefore outlined once and written one theme at a time
(``agents/meta_review/research_overview_knowledge_base_calls``). This
budget is the outline's: theme titles, subsection headings and the
evidence ids each is drawn from, no prose -- eight themes of eight
headings is well under 2,000 tokens, and the rest is margin for the
json_object downgrade's own verbosity. A base rather than a cap, so
``_apply_thinking_args`` still replaces it with the floor wherever the
model reasons; what keeps this call inside the clock is the bounded chain
of thought its call site asks for, not this number.
"""

KNOWLEDGE_BASE_THEME_MAX_TOKENS: Final = 12000
"""Answer budget for writing one theme's subsections (F8).

Sized from the ask rather than from a comparable caller, like the single
budget it replaces: a theme runs at most ``KNOWLEDGE_BASE_MAX_SECTIONS``
subsections, and ``KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS`` tops a
subsection at 500 words, so the largest theme any prompt can ask for is
4,000 words -- about 8,000 tokens of prose, and 12000 leaves the JSON
carrying it room on top.

Deliberately far below the 42,000 that could not be served: at the 27-37
tokens/second those failed attempts measured, this is 320-440s inside a
600s per-call ceiling, and eight of them run concurrently rather than in
sequence. A base, not a cap, for the same reason as the outline budget
above.
"""

RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS: Final = 6000
"""Answer budget for developing one drafted research direction.

Sized from the ask, like the knowledge-base part budgets above. The
published cf-PICI exemplar's five substantive directions run 807-1,015
words each -- a "Why research this area?" argument plus four named
sub-topics, each with its own reasoning, a worked example idea and four
questions -- so about 1,400 tokens of prose, and our own measured
directions ran ~2.0k billed. 6000 leaves the JSON carrying it room on
top and absorbs the json_object downgrade's own verbosity.

The point of the number is the clock, not the ceiling: at the 27-37
tokens/second this deployment measured, a ~2.3k answer is 62-85s inside
the 600s per-call bound, and six of them run concurrently. The single
call they replace would have had to write all six inside one stream --
~13.9k tokens, 376-515s at that rate, and losing every direction rather
than one when it did not land.
"""

RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS: Final = 6000
"""Answer budget for a periodic (non-terminal) research-overview firing.

Unlike the terminal call, an interim firing's schema
(``RESEARCH_OVERVIEW_INTERIM_SCHEMA``) asks for nothing but a handful of
direction titles and open questions -- no summary, no NIH Specific Aims
page, no contacts, no knowledge base -- because
``interim_overview.build_interim_overview`` reads only those two fields
back out. Before that schema existed, every interim firing still paid
``RESEARCH_OVERVIEW_MAX_TOKENS``'s generation cost for the full
ten-section document and discarded eight of the ten sections unread.

A base, not a cap, for the same reason as the knowledge-base outline
budget above: ``_apply_thinking_args`` replaces it with
``THINKING_FLOOR_MAX_TOKENS`` (18000) on a thinking model, so the
deployed chain's effective ceiling only drops from 24000 to 18000, not
to 6000, and the chain of thought below that floor is unbounded exactly
as it is on every other call -- this budget does not shrink or bound
it. What actually shrinks is the *answer*: four titles and five
questions cost a few hundred tokens, an order of magnitude below what
the terminal document's ten sections ask for, so a non-thinking
provider (where 6000 is the operative ceiling) answers well inside it,
and a thinking provider spends the same floor-funded reasoning as
before but writes a far smaller response once it finishes.
"""

THINKING_MAX_TOKENS: Final = 18000
"""Max tokens for extended thinking + long responses.

Also the value of ``THINKING_FLOOR_MAX_TOKENS`` below, by derivation rather
than coincidence: the floor was set to the budget these nodes had already
proven in production. Changing this number therefore moves the floor under
every other thinking call in the engine, so change the two together
deliberately or not at all.
"""

BUDGET_ESCALATION_MAX_TOKENS: Final = 24000
"""Floor a raised-budget retry never sends less than.

The floor below is a floor, not a guarantee: a chain of thought is free to
fill whatever it is given, and in production these calls came back with
``reasoning_tokens`` sitting exactly on ``THINKING_FLOOR_MAX_TOKENS`` and
``content`` empty -- then did it again on all five ``call_llm_json``
attempts, because every attempt re-sent the same budget.
``llm.attempts.escalation.escalated_max_tokens`` answers the second
attempt with a budget raised from the call's own size (see
``BUDGET_ESCALATION_MAX_INCREMENT``), floored here, and the third by
turning thinking off, so the ladder terminates whether or not the
reasoning would ever have finished.

24000 rather than something larger because it is the budget already proven
in production (``RESEARCH_OVERVIEW_MAX_TOKENS`` and the scaled batch caps
run at it); the provider's own output ceiling is far above either. It is a
floor rather than the whole formula because a caller already sized *at*
this number -- ``RESEARCH_OVERVIEW_MAX_TOKENS`` is exactly 24000 -- would
otherwise see ``max(max_tokens, 24000)`` return its own input unchanged: a
retry rung that resends the identical request, silently, for precisely the
callers large enough to need a real increase.
"""

BUDGET_ESCALATION_MAX_INCREMENT: Final = BUDGET_ESCALATION_MAX_TOKENS
"""Most a single escalation may add on top of the call's own budget.

Derived from ``BUDGET_ESCALATION_MAX_TOKENS`` rather than tuned
separately, the same way ``THINKING_FLOOR_MAX_TOKENS`` derives from
``THINKING_MAX_TOKENS``: one proven budget's worth of extra room is
already known to be safe to ask a provider for, so the increment reuses
it instead of introducing a second number to justify.

``escalated_max_tokens`` adds ``min(max_tokens // 2, this)`` to the
call's own budget -- half again as much room, on the reasoning that a
chain of thought which was close to finishing plausibly needs some more,
not double, and enough of a step to matter for the small callers this
constant used to handle alone. Bounding the *increment* rather than the
result is what keeps the retry a retry: a cap on the final number would
have to either cut down a caller already sized past it (the exact bug
this constant fixes) or let an unbounded caller through unchecked, and a
formula cannot do both. Bounding what gets *added* instead means a
60000-token caller still escalates, to 84000, four times what a
24000-token caller adds, but never to something disconnected from what
it already asked for.
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
with no thinking mode. A call site asking ``enable_thinking=False`` still
lands in this regime when the model forces reasoning back on regardless (with
its chain of thought bounded by ``MINIMAL_REASONING_MAX_TOKENS`` below, not by
a budget of its own) -- so every budget in this module lives in two regimes at
once -- superseded by the floor on the DeepSeek-family models this engine
deploys on, and operative as written on any other provider. That is why a cap
below the floor is not merely inert: it is a ceiling that binds on one
provider and silently does not on another. The caps block at the end of this
module keeps every cap above the floor so each one means the same thing in
both regimes; ``tests/test_token_budget_floor.py`` pins that.
"""

MINIMAL_REASONING_MAX_TOKENS: Final = 2048
"""Reasoning tokens a call that asked *not* to reason may be given.

Not a ``max_tokens`` budget: the gateway's own ``reasoning`` object takes
a bound on the chain of thought alone
(``llm.request.gateway_body._minimal_reasoning_knob``), which is the only
lever that answers this failure. A call site sizes its ``max_tokens`` around
``enable_thinking=False``, but a declared gateway model with
``reasoning_can_disable=False`` (``ModelProfile``) never goes out
disabled -- and the tier name it was redirected to bounds nothing.
Production measured exactly that, twice, at two different budgets:
~20-21k reasoning tokens against the 18000-token
``THINKING_FLOOR_MAX_TOKENS`` (run 323ff72c, 2026-09-06), then 24547 and
25424 against a 24000-token floor introduced to fix it (run 6760ce63).
The chain of thought simply fills whatever it is given, so no budget is
large enough and the request has to carry the bound.

2048 because the callers are classification judges -- entailment, a
label -- not tasks a long chain of thought earns its keep on, and
because the bound is spent before a single answer token is written: it
must fit well inside the smallest such caller's own budget
(``app.claims.verifier`` sizes its per-claim call at 6000) so the answer
still has room on a host that applies no floor at all. Above 1024
because Anthropic-style upstreams reject a smaller reasoning budget
outright.

The bound replaces a premium floor rather than joining it: with the
reasoning capped, a forced call is funded at the ordinary
``THINKING_FLOOR_MAX_TOKENS`` like any other thinking call. That also
restores the escalation ladder, which the premium floor had flattened --
a 12000-token caller floored to 24000 sent the identical request on all
three rungs, since ``escalated_max_tokens`` floors at that same 24000.
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


# Elo rating system parameters
# Seed rating assigned to every newly generated hypothesis (agents/generation/
# citations.py) before it has played any tournament matches in ranking.py.
INITIAL_ELO_RATING: Final = 1200
"""Initial Elo rating for new hypotheses."""

# Standard chess-style K-factor: how much a single match win/loss moves a
# hypothesis's Elo rating. Consumed by ranking.calculate_elo_update.
ELO_K_FACTOR: Final = 24
"""K-factor for Elo rating updates (higher = more volatile ratings)."""

# --- K-factor annealing and margin scaling (local reconstruction choices) --
# The paper specifies neither a K-factor nor any schedule for it (SSR §12);
# the reference corpus (TE §3) documents a phase-annealed schedule (K=32 for
# a hypothesis's first 30 matches, 16 for the next 470, 10 thereafter) and a
# margin-of-victory scaling as clone-defined options. These knobs reconstruct
# both behaviors. Both default to OFF so every rating a run produces today is
# unchanged; enabling them is a labeled, documented departure, never a silent
# one.

ELO_K_ANNEALING_HALF_LIFE: Final = 0
"""Matches played before a hypothesis's effective K halves (0 = no annealing).

Local reconstruction choice (paper-unspecified; see the module comment).
When positive, a hypothesis's effective K halves once per this many career
matches it has played before the match, so early matches calibrate a fresh
idea quickly while later matches only refine a settled rating. The decay is
applied per side of a matchup from that side's own match count
(ranking_elo.annealed_k_factor), mirroring the reference corpus's
per-hypothesis phase schedule. 0 keeps the fixed ``ELO_K_FACTOR`` for every
match -- the historical behavior.
"""

ELO_K_ANNEALED_MINIMUM: Final = 6
"""Floor on an annealed K-factor, so a rating never fully freezes.

Local reconstruction choice (paper-unspecified). The reference corpus's
schedule stops decaying at 10 of its base 32; a quarter of this repo's base
24 is the equivalent resting point. Only consulted when annealing is on.
"""

ELO_MARGIN_VICTORY_SCALE: Final = 0.0
"""Margin-of-victory scaling applied to K per judged verdict (0.0 = off).

Local reconstruction choice (paper-unspecified; the reference corpus scales
K by the score margin between the sides). This tournament's judge reports a
verdict plus a confidence level rather than scores, so the reconstruction
maps confidence to margin: High counts as a full margin, Medium as half,
anything else as none, and the effective K grows by
``scale * margin`` times the annealed K (ranking_elo.margin_scaled_k_factor).
0.0 disables the scaling -- the historical behavior.
"""

ELO_MARGIN_MULTIPLIER_CAP: Final = 5.0
"""Upper bound on the margin multiplier applied to K.

Local reconstruction choice: the reference corpus caps its margin-scaled K
at five times the base (effective K in [32, 160]); the same cap bounds this
reconstruction so a decisive verdict cannot move a rating by more than five
times the configured K.
"""

# Debate depth for a tournament matchup (paper invariant SSR §4, §12): top-
# ranked comparisons use a multi-turn scientific debate, lower-ranked ones a
# single-turn comparison. A matchup is "top-ranked" when at least one
# hypothesis is at or above the pool's median Elo. The multi-turn envelope
# itself (3-5 typical, 10 max, early stop on consensus) lives with the loop
# that enforces it: agents/ranking/ranking_debate_turns.py.
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

# Every ``max_tokens`` budget -- the answer bases, the thinking floor that
# supersedes them, the escalation budget, and the per-node scaling inputs
# and caps -- moved to a sibling module for the same reason: each of them
# only means what it says relative to the floor, so they read as one
# subject and were split as one. Re-exported here so
# ``co_scientist.constants`` stays the single import path; the tournament
# block below explains the redundant ``X as X`` alias form and why the
# longest names cannot fit it in 80 columns.

# Everything the Elo tournament is shaped by -- seed rating, K-factor, debate
# depth, per-hypothesis match budgets, wave width -- moved to a sibling
# module; each of those values carries its own incident history, and together
# they were the largest single subject in this file. Every name is re-exported
# so ``co_scientist.constants`` stays the one import path for all of them.
# The redundant ``X as X`` is what marks a re-export under mypy's strict
# no-implicit-reexport; the last name below is long enough that the alias form
# cannot fit in 80 columns, and renaming it would break every caller.

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
# Deep verification precedes tournament entry (``03-reflection.md``), so
# its band sits between the safety screen and the tournament.
PROGRESS_DEEP_VERIFICATION_START: Final = 43
PROGRESS_DEEP_VERIFICATION_COMPLETE: Final = 44
PROGRESS_TOURNAMENT_START: Final = 55
PROGRESS_TOURNAMENT_COMPLETE: Final = 70
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
# the cache package); caching covers both raw LLM responses and node-level
# results.
DEFAULT_CACHE_DIR: Final = ".coscientist_cache"
"""Default directory for LLM response caching."""

DEFAULT_CACHE_ENABLED: Final = True
"""Whether caching is enabled by default (controls both LLM and node-level
caching).
"""

# Selected in evidence/search_support.py from the
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
