"""Terminal synthesis payloads for a curated demo run.

Split out of ``app.seed``: this module builds the research-overview and
meta-review objects a completed run carries, in the same shape a real run's
synthesis produces, so the demo exercises the whole report surface.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# source-backed statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from app.demo_seed_data import DemoEvidence, DemoHypothesis, DemoScenario


def _overview_directions(
    top: tuple[DemoHypothesis, ...],
) -> list[dict[str, Any]]:
    """Return the research directions the overview recommends."""
    return [
        {
            "title": item.title,
            "importance": item.mechanism,
            "suggested_experiments": [
                item.experiment,
                "Repeat the discriminating condition in an independent model set with a prespecified rescue criterion.",
            ],
        }
        for item in top
    ]


def _overview_aims(top: tuple[DemoHypothesis, ...]) -> list[dict[str, Any]]:
    """Return the grant-style specific aims derived from the top ideas."""
    return [
        {
            "overarching_goal": f"Aim {index}: Test {item.title}",
            "hypothesis": item.statement,
            "reasoning": item.experiment,
        }
        for index, item in enumerate(top, start=1)
    ]


def _overview_knowledge_base(
    evidence: tuple[DemoEvidence, ...],
    hypotheses: tuple[DemoHypothesis, ...],
) -> list[dict[str, Any]]:
    """Return the knowledge-base topics, each citing two curated sources."""
    return [
        {
            "title": item.title,
            "summary": item.mechanism,
            "detail": item.experiment,
            "uncertainty": item.review,
            "references": [
                {"title": evidence[item.evidence_index].title},
                {
                    "title": evidence[
                        (item.evidence_index + 1) % len(evidence)
                    ].title
                },
            ],
        }
        for item in hypotheses[:6]
    ]


def _overview_contacts(
    evidence: tuple[DemoEvidence, ...],
) -> list[dict[str, Any]]:
    """Return the authorship-derived contact suggestions for the overview."""
    return [
        {
            "candidate_id": f"demo-contact-{index + 1}",
            "name": evidence_item.authors[0].replace(" et al.", ""),
            "expertise": (
                "Author of a source analyzed in this demonstration; their paper "
                "is relevant to the experimental and mechanistic question."
            ),
            "justification": (
                "This suggestion is derived only from the authorship metadata of "
                "a source in the run and is not a recommendation or contact claim."
            ),
            "source_id": f"demo-evidence-{index + 1}",
            "source_title": evidence_item.title,
            "source_url": evidence_item.url,
            "source": "pubmed",
        }
        for index, evidence_item in enumerate(evidence[:3])
    ]


def _curated_research_overview(
    scenario: DemoScenario,
    evidence: tuple[DemoEvidence, ...],
    hypotheses: tuple[DemoHypothesis, ...],
) -> dict[str, Any]:
    """Build the complete terminal synthesis shape used by real runs."""
    top = hypotheses[:3]
    return {
        "overview": {
            "summary": (
                f"{scenario.meta_review} The ranked program deliberately keeps "
                "competing mechanisms separate, then uses perturbation, rescue, "
                "and independent-model replication to decide which should advance."
            ),
            "research_directions": _overview_directions(top),
        },
        "nih_specific_aims": {
            "disease_description": (
                "This curated demonstration models a grant-style synthesis of a "
                "condition whose broad phenomenon is established but whose "
                "driving mechanism is not."
            ),
            "unmet_need": (
                "The central gap is not whether the broad phenomenon exists, but "
                "which specific causal mechanism is both measurable and "
                "falsifiable."
            ),
            "proposed_solution": (
                "Separate the competing mechanisms and decide between them with "
                "perturbation, rescue, and independent-model replication."
            ),
            "aims": _overview_aims(top),
            "pilot_evaluation": (
                "The intended output is a reproducible decision framework for "
                "prioritizing a preclinical mechanism. It is illustrative only and "
                "does not establish a clinical intervention."
            ),
        },
        "research_contacts": _overview_contacts(evidence),
        "knowledge_base": _overview_knowledge_base(evidence, hypotheses),
    }


def _curated_meta_review(scenario: DemoScenario) -> dict[str, Any]:
    """Create a full meta-review payload rather than a one-line summary."""
    return {
        "summary": scenario.meta_review,
        "common_strengths": [
            "The highest-ranked ideas name a specific mediator, perturbation, readout, and falsification criterion.",
            "The program preserves multiple causal explanations instead of collapsing to one generic mechanism.",
        ],
        "common_weaknesses": [
            "The cited literature is contextual support, not direct proof of each proposed causal chain.",
            "Model-system effects and generic stress responses must be separated from the nominated mechanism.",
            "Every promising result needs an independent replication set before it is used for prioritization.",
        ],
        "emerging_themes": [
            "Time-resolved state measurements are more discriminating than a single terminal viability readout.",
            "Biomarker or state stratification can prevent an average effect from being mistaken for a universal mechanism.",
        ],
        "strategic_recommendations": [
            {
                "focus_area": "Causal inference",
                "recommendation": "Pair each perturbation with a rescue and an orthogonal assay before advancing it in the ranking.",
                "justification": "A correlated marker or single readout cannot establish the proposed mechanism.",
            },
            {
                "focus_area": "Replication",
                "recommendation": "Reserve an independent model set for a locked confirmatory experiment.",
                "justification": "The demo intentionally mirrors a real run's need to test generalizability.",
            },
        ],
    }
