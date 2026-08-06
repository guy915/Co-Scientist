"""Tests for the verified-wrong-assumption refinement channel (audit K9).

Deep verification already stores per-assumption probes and a verdict on
each hypothesis; these tests pin the derivation that turns "verified
incorrect but non-fundamental" into the avoid-or-rework guidance block
the generation prompts consume.
"""

from co_scientist.agents.generation.assumption_feedback import (
    MAX_FALSIFIED_ASSUMPTION_LINES,
    build_falsified_assumptions_section,
    falsified_nonfundamental_assumptions,
)
from tests._state import make_hypothesis


def _probe(
    question: str = "Does X hold?",
    answer: str = "Evidence shows X does not hold.",
    fundamental: bool = False,
    **extra: object,
) -> dict[str, object]:
    """Build one deep-verification probe dict."""
    probe: dict[str, object] = {
        "question": question,
        "answer": answer,
        "reasoning": "reasoning text",
        "assumption_is_fundamental": fundamental,
        "search_query": "X holds",
    }
    probe.update(extra)
    return probe


def test_weakened_hypothesis_contributes_nonfundamental_probes() -> None:
    """Verdict 'weakened' records non-fundamental gaps; those are admitted.

    'weakened' is the verifier's own statement that non-fundamental
    assumptions failed while the idea survives -- exactly the record K9
    says must steer later generation.
    """
    hyp = make_hypothesis(
        deep_verification_probes=[
            _probe(question="Is acrB essential here?"),
            _probe(question="Is the core mechanism sound?", fundamental=True),
        ],
        deep_verification_verdict="weakened",
    )
    lines = falsified_nonfundamental_assumptions([hyp])
    assert len(lines) == 1
    assert "Is acrB essential here?" in lines[0]
    assert "Evidence shows X does not hold." in lines[0]


def test_holds_verdict_contributes_nothing() -> None:
    """Probes of a hypothesis whose assumptions all survive stay out."""
    hyp = make_hypothesis(
        deep_verification_probes=[_probe()],
        deep_verification_verdict="holds",
    )
    assert falsified_nonfundamental_assumptions([hyp]) == []


def test_undermined_verdict_contributes_nothing() -> None:
    """Fundamental failure kills the idea; it is a different channel."""
    hyp = make_hypothesis(
        deep_verification_probes=[_probe()],
        deep_verification_verdict="undermined",
    )
    assert falsified_nonfundamental_assumptions([hyp]) == []


def test_explicit_assumption_holds_false_is_admitted_alone() -> None:
    """A per-probe falsification record is authoritative when present."""
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(assumption_holds=False)],
        deep_verification_verdict="holds",
    )
    lines = falsified_nonfundamental_assumptions([hyp])
    assert len(lines) == 1


def test_explicit_assumption_holds_true_overrides_weakened() -> None:
    """A probe recorded as holding is excluded even under 'weakened'."""
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(assumption_holds=True)],
        deep_verification_verdict="weakened",
    )
    assert falsified_nonfundamental_assumptions([hyp]) == []


def test_guidance_is_capped() -> None:
    """The block stays prompt-sized no matter how many probes qualify."""
    probes = [_probe(question=f"Q{i}?") for i in range(10)]
    hyp = make_hypothesis(
        deep_verification_probes=probes,
        deep_verification_verdict="weakened",
    )
    lines = falsified_nonfundamental_assumptions([hyp])
    assert len(lines) == MAX_FALSIFIED_ASSUMPTION_LINES


def test_section_empty_until_something_is_falsified() -> None:
    """No verified-wrong assumption means no block in the prompt."""
    assert build_falsified_assumptions_section(None) == ""
    assert build_falsified_assumptions_section([]) == ""
    clean = make_hypothesis(
        deep_verification_probes=[_probe()],
        deep_verification_verdict="holds",
    )
    assert build_falsified_assumptions_section([clean]) == ""


def test_section_carries_the_avoid_or_rework_instruction() -> None:
    """The rendered block tells generation to avoid or rework them."""
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(question="Does efflux matter?")],
        deep_verification_verdict="weakened",
    )
    section = build_falsified_assumptions_section([hyp])
    assert "Verified Incorrect" in section
    assert "avoid" in section.lower()
    assert "rework" in section.lower()
    assert "Does efflux matter?" in section
