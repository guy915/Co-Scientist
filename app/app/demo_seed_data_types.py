"""Record types for the curated demo scenarios.

These dataclasses sit in their own module so the curated content modules can
import them without depending on the ``demo_seed_data`` facade that imports
that content back.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoEvidence:
    """One source used to ground an illustrative demo scenario."""

    title: str
    authors: tuple[str, ...]
    year: int
    url: str
    abstract: str


@dataclass(frozen=True)
class DemoHypothesis:
    """One ranked, testable proposal in an illustrative demo scenario."""

    title: str
    statement: str
    mechanism: str
    expected_effect: str
    experiment: str
    review: str
    elo: int
    evidence_index: int


@dataclass(frozen=True)
class DemoScenario:
    """The curated content needed to populate one complete demo run."""

    title: str
    summary: str
    meta_review: str
    direction: str
    # The Top Ranking Hypotheses document's own "Goal:" line (R14-3):
    # authored here, like every other curated field, rather than produced
    # by ``report_goal_synthesis`` -- see ``seed_scenario._scenario_report_
    # request``, which threads this straight into the report request
    # instead of letting the build path call the synthesizer.
    goal_restatement: str
    duration_seconds: float
    elo_ceiling: int
    elo_step: int
    evolution_count: int
    second_pass_count: int
    evidence: tuple[DemoEvidence, ...]
    hypotheses: tuple[DemoHypothesis, ...]


@dataclass(frozen=True)
class DemoProposal:
    """One additional generation-wave proposal for a curated demo."""

    title: str
    premise: str
    experiment: str
    limitation: str
    evidence_index: int
