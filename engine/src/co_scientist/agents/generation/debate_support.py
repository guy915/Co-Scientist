"""Diversity and final-turn budget helpers for debate generation.

Non-LLM helpers for the debate strategy in debate.py: the parallel-debate
diversity angles, preference augmentation, the final turn's token budget,
and its prompt-metadata payload. The debate LLM seams (call_llm and
call_llm_json) stay in debate.py so tests can monkeypatch them there.
"""

import re
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.generation.citations import ReferenceIndex
from co_scientist.constants import (
    DEBATE_FINAL_TURN_MAX_TOKENS_CAP,
    DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS,
    EXTENDED_MAX_TOKENS,
    scaled_max_tokens,
)

# Angles cycled through parallel debates (via debate_id modulo the list
# length in _debate_diversity_instruction) so concurrent debates on the
# same research goal explore different facets instead of converging on
# the same obvious hypothesis.
_DEBATE_DIVERSITY_ANGLES = [
    "a direct causal molecular or mechanistic intervention",
    "an upstream regulatory or control-system mechanism",
    "a downstream measurable phenotype or functional assay",
    "a cross-pathway interaction that could explain an unexpected effect",
    "a temporal or state-dependent mechanism that changes across conditions",
    "a translational experiment or intervention with practical constraints",
    "a falsification-focused hypothesis with a discriminating negative control",
    "a high-novelty mechanism that challenges the dominant explanation",
]


def _debate_diversity_instruction(
    debate_id: int | None, total_debates: int
) -> str | None:
    """Return a debate-specific angle for parallel hypothesis diversity."""
    # A single, non-parallel debate has no sibling to diverge from, so no
    # diversity nudge is needed.
    if debate_id is None or total_debates <= 1:
        return None
    angle = _DEBATE_DIVERSITY_ANGLES[debate_id % len(_DEBATE_DIVERSITY_ANGLES)]
    return (
        f"Parallel debate {debate_id + 1} of {total_debates}: focus this "
        f"debate on {angle}. Produce a final hypothesis that is meaningfully "
        "different from what other parallel debates would generate; do not "
        "collapse to the most generic or obvious mechanism unless it uniquely "
        "fits this assigned angle."
    )


def _append_diversity_instruction(
    preferences: str | None, instruction: str | None
) -> str | None:
    """Append the parallel-debate diversity instruction to preferences."""
    # Augments, rather than replaces, any user-supplied preferences so both
    # constraints are honored together in the generation prompt.
    if not instruction:
        return preferences
    if preferences:
        return f"{preferences}\n\n{instruction}"
    return instruction


def _debate_final_turn_max_tokens(count: int) -> int:
    """Compute the final debate turn's token budget for count hypotheses.

    count is always 1 here (one hypothesis per debate), so this evaluates to
    a fixed budget (base + one per_item increment) rather than truly scaling
    with batch size, unlike other scaled_max_tokens call sites that pass a
    variable count.
    """
    return scaled_max_tokens(
        EXTENDED_MAX_TOKENS,
        count,
        per_item=DEBATE_FINAL_TURN_TOKENS_PER_HYPOTHESIS,
        cap=DEBATE_FINAL_TURN_MAX_TOKENS_CAP,
    )


def _final_turn_prompt_metadata(
    debate_id: int | None,
    turn: int,
    articles_with_reasoning: str | None,
    ref_idx: ReferenceIndex,
    prompt: str,
) -> dict[str, Any]:
    """Build the prompt_metadata payload for a debate's final-turn LLM call."""
    return {
        "debate_id": debate_id,
        "turn": turn,
        "has_literature": articles_with_reasoning is not None,
        "reference_keys": list(ref_idx.sources.keys()),
        "prompt_length_chars": len(prompt),
    }


# The debate prompt's stated termination condition (paper SSR note 9.1):
# a panel that has resolved its disagreement concludes by writing
# "HYPOTHESIS" before the finalized idea. Two accepted shapes:
#
# - The canonical sentinel: the all-caps token the prompt reserves for the
#   conclusion, followed by a sentence break (colon, period, dash). The
#   punctuation requirement keeps a turn that merely QUOTES the
#   instruction ('we will write "HYPOTHESIS" once we agree') from ending
#   the debate.
# - A line-leading marker variant: panels that slip on the all-caps
#   instruction still put the marker on its own line ("Hypothesis:",
#   "**HYPOTHESIS**"), so a case-insensitive line anchor accepts the
#   marker followed by a colon or standing alone -- but never a list
#   enumerator like "Hypothesis 1:", which is ordinary turn content.
_DEBATE_TERMINATOR = re.compile(r"\bHYPOTHESIS\b\s*[:.;\u2013\u2014-]")
_DEBATE_TERMINATOR_VARIANT = re.compile(
    r"(?im)^[ \t>*#\-]*HYPOTHESIS[ \t*]*(?::.*)?$"
)


def _debate_converged(response_text: str) -> bool:
    """True when a free-form turn declared the debate concluded.

    Debate turns are strictly serial and generation is the deepest serial
    chain in a run, so a panel that has genuinely converged stops paying
    for the remaining discussion turns: the loop honours this signal and
    moves straight to the schema-constrained synthesis turn.

    False positives end a debate early; false negatives spend one more
    turn, so the match is deliberately conservative -- ordinary talk
    about "the hypothesis" (the content of every turn) must not end the
    debate. See the pattern comments above for the accepted shapes.
    """
    if _DEBATE_TERMINATOR.search(response_text):
        return True
    return bool(_DEBATE_TERMINATOR_VARIANT.search(response_text))


@dataclass(frozen=True)
class DebateBatchPosition:
    """Where one ``generate_with_debate`` call sits in its parallel batch.

    The durable path runs each debate as its own task; carrying the task's
    position and the batch's whole size restores the diversity angles a
    single in-process batch gets for free (finding E14). Angles are
    assigned by debate id modulo the angle list, so the id and the batch
    total together decide it -- a per-debate task that only knew its own
    count of 1 could never diverge from its siblings.

    Attributes:
        debate_index: Index of this call's first debate within the batch.
        total_debates: Size of the whole parallel batch.
    """

    debate_index: int
    total_debates: int
