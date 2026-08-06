"""Elo and tournament parameters for Co-Scientist.

The shape of the pairwise tournament lives here: the seed rating and
K-factor that turn a judged matchup into a rating change, the debate depth
each matchup is argued at, the per-hypothesis match budgets that decide how
much of the pool actually gets measured, and the wave width that bounds the
fan-out.

A value belongs in this module when changing it changes what the tournament
costs or what its ratings mean. Everything else stays in ``constants``,
which re-exports every name defined here so ``co_scientist.constants``
remains the single import path for all of them.
"""

from typing import Final

# Elo rating system parameters
# Seed rating assigned to every newly generated hypothesis (agents/generation/
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
