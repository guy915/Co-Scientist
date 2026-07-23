"""Diversity and final-turn budget helpers for debate generation.

Non-LLM helpers for the debate strategy in debate.py: the parallel-debate
diversity angles, preference augmentation, the final turn's token budget,
and its prompt-metadata payload. The debate LLM seams (call_llm and
call_llm_json) stay in debate.py so tests can monkeypatch them there.
"""

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
