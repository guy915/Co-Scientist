"""Curated, clearly illustrative scenarios for the default demo runs.

The startup demos are product examples, not generated scientific findings.
They use real, linked publications as context but keep every proposed
mechanism and experiment explicitly exploratory.  The data is intentionally
small enough to browse while still exercising the complete run surface.

The curated content itself lives in sibling modules -- scenarios in
``demo_seed_data_scenarios``, extra sources in ``demo_seed_data_evidence``,
generation-wave seeds in ``demo_seed_data_proposals``, and the record types
in ``demo_seed_data_types`` -- so this module holds only the functions that
derive one run's artifacts from them. Every moved name is re-exported here,
so ``app.demo_seed_data`` remains the stable import surface.
"""

# The reader-facing prose these functions compose is kept intact;
# wrapping individual literals would make the demo content hard to audit.
# ruff: noqa: E501

from __future__ import annotations

from app.demo_seed_data_evidence import (
    _EXTRA_EVIDENCE as _EXTRA_EVIDENCE,
)
from app.demo_seed_data_proposals import (
    _PROPOSALS as _PROPOSALS,
)
from app.demo_seed_data_scenarios import (
    _SCENARIO_KEYS as _SCENARIO_KEYS,
)
from app.demo_seed_data_scenarios import (
    DEMO_SCENARIOS as DEMO_SCENARIOS,
)
from app.demo_seed_data_types import (
    DemoEvidence as DemoEvidence,
)
from app.demo_seed_data_types import (
    DemoHypothesis as DemoHypothesis,
)
from app.demo_seed_data_types import (
    DemoProposal as DemoProposal,
)
from app.demo_seed_data_types import (
    DemoScenario as DemoScenario,
)

# Versions the whole curated bundle, sibling content modules included: a
# deployed instance replaces its stored demo artifacts when this changes.
DEMO_SEED_VERSION = 11


def scenario_evidence(scenario: DemoScenario) -> tuple[DemoEvidence, ...]:
    """Return the curated six-source evidence bundle for one demo scenario."""
    return scenario.evidence + _EXTRA_EVIDENCE[scenario_key(scenario)]


def scenario_key(scenario: DemoScenario) -> str:
    """Resolve a scenario's stable key from its object identity."""
    for key, candidate in DEMO_SCENARIOS.items():
        if candidate is scenario:
            return key
    raise ValueError("Unknown curated demo scenario")


def _proposal_hypothesis(proposal: DemoProposal) -> DemoHypothesis:
    """Expand a concise generation seed into the full hypothesis record."""
    return DemoHypothesis(
        title=proposal.title,
        statement=proposal.premise,
        mechanism=(
            f"{proposal.premise} The experiment is designed to distinguish the "
            "nominated mediator from correlated changes in the surrounding model "
            "system rather than treating an association as causal evidence."
        ),
        expected_effect=(
            "If the mechanism is correct, the pre-specified perturbation will "
            "shift the primary readout and that shift will be reversed by the "
            "named rescue or orthogonal control."
        ),
        experiment=proposal.experiment,
        review=proposal.limitation,
        elo=1200,
        evidence_index=proposal.evidence_index,
    )


def _evolved_hypothesis(source: DemoHypothesis) -> DemoHypothesis:
    """Create a distinct second-generation version with stronger falsification."""
    return DemoHypothesis(
        title=f"Refined: {source.title}",
        statement=(
            f"{source.statement} This evolved version adds a preregistered "
            "stratification rule, an orthogonal readout, and a rescue criterion "
            "so that a negative result can distinguish a failed mechanism from "
            "an uninformative assay."
        ),
        mechanism=(
            f"{source.mechanism} The refinement explicitly tests whether the "
            "candidate mediator is necessary and sufficient, rather than relying "
            "on a single association or endpoint."
        ),
        expected_effect=(
            f"{source.expected_effect} Concordance across the primary assay, "
            "orthogonal assay, and rescue arm is required before advancing it."
        ),
        experiment=(
            f"{source.experiment} Repeat the highest-value condition in an "
            "independent model set and prospectively define the effect size that "
            "would justify a follow-up study."
        ),
        review=(
            f"{source.review} The evolved version reduces this risk, but the "
            "claim remains exploratory until the independent replication agrees."
        ),
        elo=1200,
        evidence_index=source.evidence_index,
    )


def _second_pass_hypothesis(source: DemoHypothesis) -> DemoHypothesis:
    """Create a validation-focused iteration for only the strongest ideas."""
    source_title = source.title.removeprefix("Refined: ")
    return DemoHypothesis(
        title=f"Validation-ready: {source_title}",
        statement=(
            f"{source.statement} This second-pass variant narrows the claim to "
            "a prespecified population or state and advances only if the effect "
            "replicates under blinded analysis in an independent model set."
        ),
        mechanism=(
            f"{source.mechanism} The additional pass prioritizes a decisive "
            "necessity-and-rescue test over another broad exploratory screen."
        ),
        expected_effect=(
            f"{source.expected_effect} The result is considered actionable only "
            "when the predeclared replication and rescue thresholds are met."
        ),
        experiment=(
            f"{source.experiment} Lock the analysis plan, randomize the "
            "validation cohort, and report the result alongside the original "
            "discovery cohort rather than pooling them."
        ),
        review=(
            f"{source.review} This pass deliberately trades breadth for a more "
            "credible validation decision."
        ),
        elo=1200,
        evidence_index=source.evidence_index,
    )


def scenario_hypotheses(scenario: DemoScenario) -> tuple[DemoHypothesis, ...]:
    """Return a scenario-specific multi-generation hypothesis set."""
    first_wave = scenario.hypotheses + tuple(
        _proposal_hypothesis(item)
        for item in _PROPOSALS[scenario_key(scenario)]
    )
    evolved = tuple(
        _evolved_hypothesis(item)
        for item in first_wave[: scenario.evolution_count]
    )
    second_pass = tuple(
        _second_pass_hypothesis(item)
        for item in evolved[: scenario.second_pass_count]
    )
    return first_wave + evolved + second_pass
