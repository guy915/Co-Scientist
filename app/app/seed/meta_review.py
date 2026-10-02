"""Build a curated demo's comparisons and meta-review synthesis.

The payload mirrors the engine meta-review schema, including the main
research directions grounded in each scenario's own top hypotheses.
"""

# Curated scientific prose stays intact for auditability.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any, NamedTuple

from app.demo_seed_data import (
    _SCENARIO_KEYS,
    DemoHypothesis,
    DemoScenario,
    scenario_key,
)

# Each entry weaves together that scenario's own top-3 hypotheses
# (demo_seed_data/scenarios.py, in Elo-descending order -- the same
# ``hypotheses[:3]`` slice ``_curated_meta_review`` passes to
# ``_candidate_comparison``), never a fourth mechanism the scenario does
# not carry. Two paragraphs, bolded direction names inline, closing on an
# unanticipated cross-direction observation -- the published exemplar's
# own shape (top-ranking-hypotheses.md:24-28).
_MAIN_RESEARCH_DIRECTIONS: dict[str, str] = {
    _SCENARIO_KEYS[0]: (
        "Research into S. aureus biofilm tolerance is shifting from bulk "
        "susceptibility testing toward mechanisms that explain why "
        "genetically susceptible cells survive antibiotic exposure. One "
        "central direction treats **Metabolic State as an Intervention "
        "Point**: a short, non-growth-promoting pulse that raises "
        "metabolic activity before vancomycin exposure is proposed to "
        "expose antibiotic targets in an otherwise dormant population "
        "without dispersing the protective matrix itself. This matters "
        "because tolerance in a mature biofilm has repeatedly resisted "
        "explanation as a straightforward MIC problem, so an intervention "
        "timed to the population's own physiology is one of the few "
        "levers that does not require a new antibiotic target.\n\n"
        "A second direction is **MazEF Transcriptional State as a "
        "Survivor Biomarker**, which reframes the toxin-antitoxin system "
        "less as a therapeutic target in its own right and more as a "
        "signature that could flag which cells will persist through a "
        "bactericidal pulse before they are tested. Complementing both is "
        "**Spatial Nutrient-Gradient Mapping**, which locates a "
        "reversible low-energy niche within the biofilm's own oxygen and "
        "nutrient microgradients rather than treating tolerance as a "
        "uniform, population-wide property. Unexpectedly, the three lines "
        "converge on a shared question: if the metabolic pulse, the MazEF "
        "signature, and the spatial nutrient niche are reading out the "
        "same underlying dormancy program from three different angles, a "
        "single real-time readout -- rather than three separate assays -- "
        "could eventually time the intervention, flag the responsible "
        "cells, and localize them within the biofilm all at once."
    ),
    _SCENARIO_KEYS[1]: (
        "Work on adolescent prefrontal circuit refinement is shifting "
        "from documenting that pruning occurs toward pinning down when, "
        "and on which synapses, it acts. The central direction is "
        "**Temporally Restricted Microglial Engagement**, which treats "
        "adolescent refinement as calibrated by a narrow developmental "
        "window rather than a chronic process -- a distinction that "
        "matters because a timing-specific effect predicts that "
        "perturbing microglia outside the candidate window should leave "
        "adult rule-shifting untouched, a sharp, falsifiable prediction a "
        "chronic-effect model cannot make.\n\n"
        "A complementary direction is **Complement-Tagged Synapse "
        "Identity**, which asks whether synapse-level tagging, not raw "
        "synapse count, determines which connections microglia engulf -- "
        "separating a specific molecular selection mechanism from a "
        "generic inflammatory or volume effect. **Prefrontal Synchrony as "
        "an Intermediate Readout** extends this further, treating "
        "circuit-level synchrony as the variable linking structural "
        "remodeling to the rule-shifting task itself. Unexpectedly, this "
        "framing raises a reversed-causality possibility: if synchrony is "
        "not merely a downstream consequence of pruning but instead helps "
        "determine which tagged synapses actually get removed, the "
        "calibration window's own boundaries could be set by activity "
        "dynamics the current design treats as an outcome rather than an "
        "upstream signal."
    ),
    _SCENARIO_KEYS[2]: (
        "Research into ferroptosis sensitization in pancreatic cancer is "
        "converging on the idea that resistance is not uniform across "
        "tumors but instead tracks specific, measurable molecular states. "
        "The leading direction is **CPEB1-Loss-Driven NRF2 Buffering**, "
        "which proposes that CPEB1 loss stabilizes an anti-ferroptotic "
        "program through the p62/KEAP1/NRF2 axis -- a mechanistic account "
        "that matters because it supplies both a biomarker (CPEB1 status) "
        "and a rescue experiment in the same proposal, rather than only a "
        "correlation.\n\n"
        "A second direction, **ARID3A-PTEN-GPX4 Subgroup Selection**, "
        "tests a parallel transcriptional route by which ARID3A "
        "suppresses PTEN-induced ferroptosis, predicting that combination "
        "benefit concentrates in a biomarker-defined subgroup rather than "
        "an unselected population. **Early Lipid-Peroxidation Kinetics as "
        "a De-Risking Assay** complements both by asking whether a "
        "proximal redox readout, collected within hours rather than "
        "after full treatment courses, can distinguish transient stress "
        "from a durable response before either mechanistic hypothesis is "
        "fully validated. Unexpectedly, this points to a shared "
        "redox-buffering-capacity view: if CPEB1 and ARID3A-PTEN converge "
        "on overlapping NRF2/GPX4-linked buffering rather than acting "
        "through fully independent circuits, the two biomarkers may be "
        "measuring ends of one underlying spectrum that a combined -- not "
        "either-or -- panel would resolve most accurately."
    ),
}


def curated_main_research_directions(key: str) -> str:
    """Return one scenario's synthesized main-research-directions narrative."""
    return _MAIN_RESEARCH_DIRECTIONS[key]


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


# Grounded in each scenario's own top-3 hypotheses (demo_seed_data/scenarios.py)
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


# Generic across all three scenarios -- the demo's boilerplate synthesis
# framing, not a scenario-specific finding, so unlike the comparison
# tables and directions narrative above these are not keyed by
# scenario_key. Module-level so _curated_meta_review stays under the
# 40-code-line function ceiling.
_COMMON_STRENGTHS = [
    "The highest-ranked ideas name a specific mediator, perturbation, readout, and falsification criterion.",
    "The program preserves multiple causal explanations instead of collapsing to one generic mechanism.",
]
_COMMON_WEAKNESSES = [
    "The cited literature is contextual support, not direct proof of each proposed causal chain.",
    "Model-system effects and generic stress responses must be separated from the nominated mechanism.",
    "Every promising result needs an independent replication set before it is used for prioritization.",
]
_EMERGING_THEMES = [
    "Time-resolved state measurements are more discriminating than a single terminal viability readout.",
    "Biomarker or state stratification can prevent an average effect from being mistaken for a universal mechanism.",
]
_STRATEGIC_RECOMMENDATIONS = [
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
]


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
        # R14-27: the report's "Main Research Directions" narrative -- see
        # the scenario-specific narratives above.
        "main_research_directions": curated_main_research_directions(
            scenario_key(scenario)
        ),
        "common_strengths": _COMMON_STRENGTHS,
        "common_weaknesses": _COMMON_WEAKNESSES,
        "emerging_themes": _EMERGING_THEMES,
        "strategic_recommendations": _STRATEGIC_RECOMMENDATIONS,
        **comparison_fields,
    }
