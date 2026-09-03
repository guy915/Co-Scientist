"""Terminal synthesis payloads for a curated demo run.

Split out of ``app.seed``: this module builds the research-overview and
meta-review objects a completed run carries, in the same shape a real run's
synthesis produces, so the demo exercises the whole report surface.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# source-backed statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any, NamedTuple

from app.demo_seed_data import (
    _SCENARIO_KEYS,
    DemoEvidence,
    DemoHypothesis,
    DemoScenario,
    scenario_key,
)


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


# R14-6: which of a scenario's three top research directions each of its
# first three evidence sources (the ``evidence[:3]`` a contact is drawn
# from) most directly speaks to, plus the group's "why they are best for
# this direction" rationale -- grounded in what that specific source
# actually reports, not a generic template. Order matches
# ``_overview_contacts``'s own ``evidence[:3]`` iteration.
_CONTACT_DIRECTIONS: dict[str, tuple[tuple[int, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        (
            1,
            "Ma et al. is the primary source connecting the MazEF toxin-antitoxin system to S. aureus biofilm antibiotic tolerance, the state marker this direction proposes to track.",
        ),
        (
            2,
            "Tuon et al.'s review explains why intact-biofilm physiology, not just planktonic susceptibility, governs antibiotic response — the premise behind treating the matrix as a spatial niche.",
        ),
        (
            0,
            "Kim et al. link small-molecule activation of respiration to reduced biofilm formation and higher aminoglycoside sensitivity — the same 'raise metabolic activity before antibiotic exposure' logic this direction tests.",
        ),
    ),
    _SCENARIO_KEYS[1]: (
        (
            0,
            "Mallya et al. is the primary source reporting a transient, adolescence-restricted rise in microglial synaptic engulfment in the prefrontal cortex — the timing window this direction proposes to calibrate.",
        ),
        (
            2,
            "Kätzel et al. tie adolescent prefrontal circuit reorganization directly to later cognitive maturation, the circuit-to-behavior link this direction tests.",
        ),
        (
            1,
            "Koss et al. describe subregion-specific adolescent spine refinement and shifts in cytoskeletal regulatory factors, consistent with selective rather than bulk synapse turnover.",
        ),
    ),
    _SCENARIO_KEYS[2]: (
        (
            0,
            "Liu et al. is the primary source connecting CPEB1 loss to p62/KEAP1/NRF2 signaling and reduced ferroptosis susceptibility, the exact axis this direction proposes.",
        ),
        (
            1,
            "Mao et al. is the primary source linking ARID3A, PTEN, and GPX4 to gemcitabine response through ferroptosis, the pathway this direction stratifies on.",
        ),
        (
            2,
            "Hsu et al.'s NRF2-ADSL ferroptosis-escape work motivates using an early redox/lipid-peroxidation signal, rather than a static marker, to detect that escape.",
        ),
    ),
}


def _overview_contacts(
    evidence: tuple[DemoEvidence, ...],
    top: tuple[DemoHypothesis, ...],
    directions: tuple[tuple[int, str], ...],
) -> list[dict[str, Any]]:
    """Return the authorship-derived contacts, each tagged to a direction."""
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
            "research_direction": top[directions[index][0]].title,
        }
        for index, evidence_item in enumerate(evidence[:3])
    ]


def _overview_contact_groups(
    top: tuple[DemoHypothesis, ...],
    directions: tuple[tuple[int, str], ...],
    hypothesis_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return one contact group per direction (R14-6), example ids included."""
    return [
        {
            "research_direction": top[direction_index].title,
            "rationale": rationale,
            "example_hypothesis_ids": [hypothesis_ids[direction_index]],
        }
        for direction_index, rationale in directions
    ]


def _overview_nih_aims(top: tuple[DemoHypothesis, ...]) -> dict[str, Any]:
    """Return the grant-style NIH Specific Aims sub-document."""
    return {
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
    }


def _curated_research_overview(
    scenario: DemoScenario,
    evidence: tuple[DemoEvidence, ...],
    hypotheses: tuple[DemoHypothesis, ...],
    hypothesis_ids: list[str],
) -> dict[str, Any]:
    """Build the complete terminal synthesis shape used by real runs."""
    top = hypotheses[:3]
    directions = _CONTACT_DIRECTIONS[scenario_key(scenario)]
    ids = tuple(hypothesis_ids[:3])
    return {
        "overview": {
            "summary": (
                f"{scenario.meta_review} The ranked program deliberately keeps "
                "competing mechanisms separate, then uses perturbation, rescue, "
                "and independent-model replication to decide which should advance."
            ),
            "research_directions": _overview_directions(top),
        },
        "nih_specific_aims": _overview_nih_aims(top),
        "research_contacts": _overview_contacts(evidence, top, directions),
        "research_contact_groups": _overview_contact_groups(
            top, directions, ids
        ),
        "knowledge_base": _overview_knowledge_base(evidence, hypotheses),
    }


class _ComparisonTable(NamedTuple):
    """One demo's Idea Comparison Table content (R14-3 domain-aware axes).

    ``idea_values`` carries one values tuple per top-3 hypothesis, in the
    same order ``_curated_research_overview``'s own ``top = hypotheses[:3]``
    uses -- so a comparison row always describes the idea it is zipped
    against. ``existing_axes``/``existing_rows`` are left empty for a
    scenario with no standard-of-care landscape to compare against (the
    schema's own instruction to the model); the renderer already omits the
    whole section when the source dict carries neither a summary nor rows.
    """

    thematic_summary: str
    axes: tuple[str, ...]
    idea_values: tuple[tuple[str, ...], ...]
    existing_summary: str = ""
    existing_axes: tuple[str, ...] = ()
    existing_rows: tuple[tuple[str, tuple[str, ...]], ...] = ()


# Grounded in each scenario's own top-3 hypotheses (demo_seed_data_scenarios.py)
# -- every value below restates a real mechanism or review note from that
# hypothesis, not generic filler. Order matches _curated_research_overview's
# ``top = hypotheses[:3]``.
_COMPARISON_TABLES: dict[str, _ComparisonTable] = {
    _SCENARIO_KEYS[0]: _ComparisonTable(
        thematic_summary=(
            "The three ideas target tolerance at different scales -- "
            "whole-biofilm metabolic state, a specific transcriptional "
            "marker, and the matrix's own spatial structure -- so they are "
            "complementary angles on the same phenomenon, not competing "
            "explanations of it."
        ),
        axes=("Perturbation target", "Assay readiness"),
        idea_values=(
            (
                "Whole-biofilm metabolic state, raised transiently before "
                "vancomycin exposure.",
                "Standard, immediately deployable assays (CFU, ATP, biomass).",
            ),
            (
                "MazEF toxin-antitoxin transcriptional state in the "
                "surviving subpopulation.",
                "Needs new time-resolved RNA profiling and a validated "
                "reporter before causality can be tested.",
            ),
            (
                "Spatial nutrient/oxygen microgradient within an intact "
                "biofilm's matrix.",
                "Needs a new spatial mapping readout before any "
                "intervention can be tested.",
            ),
        ),
        existing_summary=(
            "Current practice targets bacterial killing directly rather "
            "than the tolerance state that lets a mature biofilm survive "
            "it, which is the gap all three ideas address."
        ),
        existing_axes=(
            "Targets the tolerance mechanism directly?",
            "Resistance-selection risk",
        ),
        existing_rows=(
            (
                "High-dose vancomycin monotherapy",
                (
                    "No -- relies on prolonged exposure, not on reducing "
                    "the tolerant state itself.",
                    "Selects for reduced susceptibility over repeated courses.",
                ),
            ),
            (
                "Mechanical or enzymatic matrix disruption",
                (
                    "Partially -- lowers the physical barrier but leaves "
                    "the underlying metabolic/state tolerance untouched.",
                    "Low direct resistance pressure, but risks "
                    "recolonization from surviving cells.",
                ),
            ),
        ),
    ),
    _SCENARIO_KEYS[1]: _ComparisonTable(
        thematic_summary=(
            "The three ideas sit at successively higher levels of the same "
            "causal chain -- cellular engagement, molecular tagging, and "
            "circuit-level readout -- so ranking them is partly a question "
            "of which level a reader trusts most as evidence, not which "
            "mechanism is correct."
        ),
        axes=("Level of measurement", "Causal evidence needed"),
        idea_values=(
            (
                "Cellular: microglia-synapse engagement, restricted to a "
                "candidate developmental window.",
                "Direct -- a predefined perturbation window paired with an "
                "adult behavioral readout.",
            ),
            (
                "Molecular: a complement-associated tag on individual "
                "synapses.",
                "Correlative unless paired with a cell-type-specific "
                "manipulation, which the review already flags as needed.",
            ),
            (
                "Circuit: population-level prefrontal synchrony during a "
                "rule-shift task.",
                "Indirect -- an intermediate readout that still needs the "
                "imaging/behavior pipeline to establish mediation.",
            ),
        ),
        # No existing_summary/axes/rows: this is a basic developmental
        # mechanism question, not one with a standard-of-care or
        # existing-treatment landscape to compare against.
    ),
    _SCENARIO_KEYS[2]: _ComparisonTable(
        thematic_summary=(
            "All three converge on ferroptosis resistance as the shared "
            "target, but at different points along the same pipeline -- a "
            "static biomarker, a transcriptional subgroup, and a kinetic "
            "predictor -- which is why the review treats them as "
            "complementary rather than as rival lead candidates."
        ),
        axes=("Biomarker for stratification", "Translational readiness"),
        idea_values=(
            (
                "CPEB1 status (loss-of-function), gating an NRF2 redox-"
                "buffering program.",
                "A rescue arm is already designed in; still needs "
                "confirmation the observed killing is ferroptotic, not a "
                "generic stress response.",
            ),
            (
                "ARID3A-high / PTEN-suppressed transcriptional subgroup.",
                "Isogenic dose-ordering and normal-cell toxicity remain to "
                "be tested before this reads as a clean subgroup effect.",
            ),
            (
                "Early (2-72h) lipid-peroxidation kinetics, not a static "
                "marker.",
                "A de-risking predictive assay meant to pair with the "
                "other two, not itself a therapeutic target.",
            ),
        ),
        existing_summary=(
            "Standard first-line chemotherapy is not selected on any of "
            "these biomarkers and does not address the anti-ferroptotic "
            "buffering program the candidate ideas target."
        ),
        existing_axes=(
            "Addresses ferroptosis resistance?",
            "Patient selection",
        ),
        existing_rows=(
            (
                "Gemcitabine +/- nab-paclitaxel (standard first-line)",
                (
                    "No -- efficacy is limited by an unaddressed anti-"
                    "ferroptotic buffering program.",
                    "Unselected -- given regardless of CPEB1, ARID3A, or "
                    "GPX4 status.",
                ),
            ),
            (
                "FOLFIRINOX",
                (
                    "No -- targets proliferation broadly rather than the "
                    "redox-buffering mechanism these hypotheses target.",
                    "Unselected, and reserved for fitter patients given "
                    "its toxicity.",
                ),
            ),
        ),
    ),
}


def _candidate_comparison(
    table: _ComparisonTable, top: tuple[DemoHypothesis, ...]
) -> dict[str, Any]:
    """Build the Idea Comparison Table dict for the run's top-3 hypotheses."""
    return {
        "thematic_summary": table.thematic_summary,
        "axes": list(table.axes),
        "ideas": [
            {
                "idea": f"Hypothesis {index}: {item.title}",
                "values": list(values),
            }
            for index, (item, values) in enumerate(
                zip(top, table.idea_values, strict=True), start=1
            )
        ],
    }


def _existing_solutions_comparison(table: _ComparisonTable) -> dict[str, Any]:
    """Build the existing-solutions comparison dict, or {} when not applicable."""
    if not table.existing_rows:
        return {}
    return {
        "summary": table.existing_summary,
        "axes": list(table.existing_axes),
        "rows": [
            {"method": method, "values": list(values)}
            for method, values in table.existing_rows
        ],
    }


def _curated_meta_review(
    scenario: DemoScenario, hypotheses: tuple[DemoHypothesis, ...]
) -> dict[str, Any]:
    """Create a full meta-review payload rather than a one-line summary."""
    table = _COMPARISON_TABLES[scenario_key(scenario)]
    top = hypotheses[:3]
    comparison_fields: dict[str, Any] = {
        "candidate_comparison": _candidate_comparison(table, top),
    }
    existing = _existing_solutions_comparison(table)
    if existing:
        comparison_fields["existing_solutions_comparison"] = existing
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
        **comparison_fields,
    }
