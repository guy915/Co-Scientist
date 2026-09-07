"""Token budgets for Co-Scientist's LLM calls.

Every number that sizes an LLM call's ``max_tokens`` lives here: the base
answer budgets, the thinking floor that supersedes them wherever the model
reasons, the escalation budget a retry climbs to, and the per-node scaling
inputs and caps that ``scaled_max_tokens`` combines. They are one subject
-- each of the budgets below only means what it says relative to the floor,
and the "no cap below the floor" rule is a property of this module read as
a whole -- so they were split out of ``constants.py`` together (size cap;
see ``constants_cache.py`` for the same pattern). ``co_scientist.constants``
re-exports every name, so it stays the one import path for all of them.
"""

from typing import Final

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

KNOWLEDGE_BASE_MAX_TOKENS: Final = 42000
"""Total budget for the deep knowledge-base synthesis call (F8).

The one call in the engine sized from a *measured* published answer
rather than from a comparable caller. Google's MASH Knowledge Base is
9,702 words over 43 named subject headings, which tokenizes (cl100k) to
19,084 tokens of prose -- around 20,000 once it is carried as JSON. That
answer cannot be bought inside the research-overview call: that draft
already spends ~15.9k of its own 24000, and asking for the depth there
produces exactly the ``finish_reason="length"`` walk the thinking-budget
gotcha describes.

42000 is ``THINKING_FLOOR_MAX_TOKENS`` (18000) plus
``BUDGET_ESCALATION_MAX_TOKENS`` (24000), both defined below: the floor
is what a chain of thought is free to spend on any thinking call, and
one already-proven escalation budget's worth of room on top is what the
measured answer needs. Written as a literal rather than as the sum only
because both live further down this module; changing either without
revisiting this number leaves the first attempt answer-starved. Sizing
it at the sum rather than at the answer alone is deliberate: a budget
that funds the floor and the answer makes the *first* attempt the one
that answers, instead of paying for a doomed attempt before the
escalation ladder raises the request to the same place.
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
``llm_json_escalation.escalated_max_tokens`` answers the second attempt
with a budget raised from the call's own size (see
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
a bound on the chain of thought alone (``llm_gateway_body
._minimal_reasoning_knob``), which is the only lever that answers this
failure. A call site sizes its ``max_tokens`` around
``enable_thinking=False``, but a declared gateway model with
``reasoning_can_disable=False`` (``GatewayModel``) never goes out
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
(``app.claim_verifier`` sizes its per-claim call at 6000) so the answer
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
