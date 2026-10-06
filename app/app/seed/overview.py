from __future__ import annotations

import json
from typing import Any, NamedTuple

from app.demo_seed_data import (
    _SCENARIO_KEYS,
    DemoEvidence,
    DemoHypothesis,
    DemoScenario,
    scenario_key,
)
from app.store.records import NewReview

# ruff: noqa: E501


_FULL_REVIEWS: dict[str, tuple[tuple[str, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        (
            "Go — proceed once the biomass/growth-rate control is built into the same experiment, not run as a separate check.",
            "6-8 weeks for the initial pulse-kill-curve comparison across three isolates.",
        ),
        (
            "Go, conditional — advance to the rescue/knockdown arm only if the MazEF signature replicates across at least two independent antibiotic pulses.",
            "10-12 weeks including targeted reporter validation.",
        ),
        (
            "Go, staged — validate the spatial oxygen/metabolic readout in intact biofilms before committing to a matrix-modulation intervention arm.",
            "12-14 weeks; the imaging readout alone is a 4-5 week milestone.",
        ),
        (
            "Go, conditional — requires the abiotic antibiotic-stability control to rule out oxygen altering vancomycin chemistry directly.",
            "8-10 weeks for the oxygenation-by-antibiotic factorial.",
        ),
        (
            "Go, narrow scope — restrict the first pass to one clinical background and require complementation before extending to a second.",
            "14-16 weeks for genetics plus replication across two backgrounds.",
        ),
    ),
    _SCENARIO_KEYS[1]: (
        (
            "Go, conditional — proceed only with the age windows and locomotor/exploratory controls pre-registered before the perturbation cohort begins.",
            "16-20 weeks (adolescent tracking window plus adult behavioral testing).",
        ),
        (
            "Go, staged — needs a cell-type-specific complement manipulation before the tagging result can be treated as more than correlational.",
            "18-22 weeks including the longitudinal engulfment cohort.",
        ),
        (
            "Go, contingent — pilot recording feasibility before committing the full behavioral cohort to the higher-risk imaging pipeline.",
            "20-24 weeks; the imaging pilot is a 6-8 week gate.",
        ),
        (
            "Go, narrow — restrict the first pass to one receptor manipulation (D1 or P2RY12) rather than both, to keep the causal claim interpretable.",
            "16-18 weeks for the imaging-plus-perturbation window.",
        ),
        (
            "Go, conditional — requires a manipulation that changes tagging independent of activity, not colocalization alone.",
            "14-16 weeks across early/mid/late adolescent sampling.",
        ),
    ),
    _SCENARIO_KEYS[2]: (
        (
            "Go — the CPEB1 biomarker and lipid-antioxidant rescue arm are both already specified; confirm ferroptotic, not generic-stress, death before advancing.",
            "10-12 weeks across the PDAC line and organoid panel.",
        ),
        (
            "Go, conditional — dose-ordering and normal-cell toxicity must be characterized before the subgroup result is treated as a translatable combination.",
            "12-14 weeks for the isogenic-perturbation matrix.",
        ),
        (
            "Go, staged — lock the analysis plan and predictor before the independent organoid validation, to avoid overfitting the training panel.",
            "16-18 weeks (training panel plus independent validation).",
        ),
        (
            "Go, conditional — requires an NRF2-rescue arm that isolates the CUL2 branch from its other cellular roles.",
            "12-14 weeks for the knockdown-plus-rescue matrix.",
        ),
        (
            "Go, narrow — restrict the first pass to catalytic-dead USP8 and NRF2-rescue controls, since proteostasis effects are otherwise hard to attribute.",
            "14-16 weeks for the pulse-chase and imaging combination.",
        ),
    ),
}

_SIMULATION_REVIEWS: dict[str, tuple[tuple[tuple[str, ...], str], ...]] = {
    _SCENARIO_KEYS[0]: (
        (
            (
                "A metabolic pulse strong enough to sensitize cells may itself trigger early dispersal, so a lower CFU count could reflect unintended biofilm breakup rather than antibiotic sensitization.",
                "ATP and CFU can move together for reasons unrelated to antibiotic exposure, so a killing effect could be misread as a tolerance shift without an antibiotic-only comparator run in parallel.",
            ),
            "The vehicle-plus-vancomycin and pulse-only arms must show no CFU change relative to baseline before the pulse-plus-vancomycin result is attributed to a tolerance shift.",
        ),
        (
            (
                "An expression signature enriched in survivors could reflect selection of a pre-existing subpopulation rather than an induced state change, which RNA profiling alone cannot distinguish.",
                "Targeted knockdown may lower general stress fitness rather than specifically removing the tolerant state, producing a rescue-shaped result for the wrong reason.",
            ),
            "The knockdown/rescue arm must restore wild-type survival specifically under antibiotic pulse conditions, not under unchallenged growth, before the marker is treated as causal.",
        ),
    ),
    _SCENARIO_KEYS[1]: (
        (
            (
                "A perturbation delivered inside the candidate window could act by changing overall arousal or locomotor state rather than the specific refinement process, producing a window-specific-looking effect for the wrong reason.",
                "Adult set-shifting performance is sensitive to handling and testing order; without counterbalancing, apparent window-specificity could be a scheduling artifact rather than developmental timing.",
            ),
            "The locomotor and exploratory control cohort must show no perturbation-related shift before the set-shifting difference is attributed to the refinement window itself.",
        ),
        (
            (
                "Complement and activity labels may correlate simply because active synapses are larger and more visible, not because complement selectively tags them for removal.",
                "A broad inflammatory response to the labeling procedure itself could increase apparent engulfment independent of any synapse-specific tagging mechanism.",
            ),
            "The cell-type-specific complement perturbation must change engulfment of tagged synapses without altering total microglial activation, before the tagging mechanism is treated as causal.",
        ),
    ),
    _SCENARIO_KEYS[2]: (
        (
            (
                "Combination killing could reflect additive off-target chemotherapy toxicity rather than a ferroptosis-specific interaction, especially at doses that also stress non-ferroptotic pathways.",
                "The lipid-antioxidant rescue could non-specifically protect cells from general oxidative stress, giving a false-positive rescue that does not confirm the CPEB1-NRF2 mechanism.",
            ),
            "The rescue must be reversed by a ferroptosis-specific inhibitor panel, not a general antioxidant alone, before the CPEB1-low result is treated as mechanism-confirming.",
        ),
        (
            (
                "ARID3A perturbation can have transcriptional effects well beyond the PTEN-GPX4 axis, so a sensitization effect may not run through the proposed route.",
                "A benefit seen only as an unselected-panel average could hide a biomarker-negative subgroup that is actually harmed, if per-model variance is not reported alongside the group mean.",
            ),
            "The PTEN-rescue arm must restore resistance in ARID3A-high models before the ARID3A-PTEN-GPX4 route is treated as the operative mechanism.",
        ),
    ),
}


def full_review_row(scenario_key: str, index: int) -> tuple[str, str, str]:
    """Only covered ranks call this reader; full reviews must never return
    an empty critique.
    """
    go_no_go, time_to_verdict = _FULL_REVIEWS[scenario_key][index]
    summary = "Full review verdict: sound"
    critique = f"Justification: {go_no_go}\nTime to verdict: {time_to_verdict}"
    detail = json.dumps({"go_no_go": go_no_go, "time_to_verdict": time_to_verdict})
    return summary, critique, detail


def simulation_review_row(scenario_key: str, index: int) -> tuple[str, str, str]:
    failure_points, decisive_step = _SIMULATION_REVIEWS[scenario_key][index]
    summary = "Simulation review verdict: holds"
    critique = "\n".join(
        [f"Failure point: {point}" for point in failure_points]
        + [f"Decisive step: {decisive_step}"]
    )
    detail = json.dumps({"failure_points": list(failure_points), "decisive_step": decisive_step})
    return summary, critique, detail


def full_review_count(scenario_key: str) -> int:
    return len(_FULL_REVIEWS[scenario_key])


def simulation_review_count(scenario_key: str) -> int:
    return len(_SIMULATION_REVIEWS[scenario_key])


def mature_review_rows(
    run_id: str, hypothesis_id: str, scenario_key: str, index: int
) -> list[NewReview]:
    rows: list[NewReview] = []
    if index < full_review_count(scenario_key):
        summary, critique, detail = full_review_row(scenario_key, index)
        rows.append(
            NewReview(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                reviewer_agent="full_review",
                summary=summary,
                critique=critique,
                detail_json=detail,
            )
        )
    if index < simulation_review_count(scenario_key):
        summary, critique, detail = simulation_review_row(scenario_key, index)
        rows.append(
            NewReview(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                reviewer_agent="simulation_review",
                summary=summary,
                critique=critique,
                detail_json=detail,
            )
        )
    return rows


# ruff: noqa: E501


# Synthesis combines this scenario's top-three ideas, never inventing a fourth
# mechanism outside its curated hypotheses.
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
    return _MAIN_RESEARCH_DIRECTIONS[key]


class _ComparisonTable(NamedTuple):
    """Values follow the top-three hypothesis order; leave existing
    solutions empty where no standard-of-care landscape applies.
    """

    thematic_summary: str
    axes: tuple[str, ...]
    idea_values: tuple[tuple[str, ...], ...]
    existing_summary: str = ""
    existing_axes: tuple[str, ...] = ()
    existing_rows: tuple[tuple[str, tuple[str, ...]], ...] = ()


# Comparison values must align with the top-three hypothesis order, not generic
# scenario filler.
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
                "Whole-biofilm metabolic state, raised transiently before vancomycin exposure.",
                "Standard, immediately deployable assays (CFU, ATP, biomass).",
            ),
            (
                "MazEF toxin-antitoxin transcriptional state in the surviving subpopulation.",
                "Needs new time-resolved RNA profiling and a validated "
                "reporter before causality can be tested.",
            ),
            (
                "Spatial nutrient/oxygen microgradient within an intact biofilm's matrix.",
                "Needs a new spatial mapping readout before any intervention can be tested.",
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
                "Molecular: a complement-associated tag on individual synapses.",
                "Correlative unless paired with a cell-type-specific "
                "manipulation, which the review already flags as needed.",
            ),
            (
                "Circuit: population-level prefrontal synchrony during a rule-shift task.",
                "Indirect -- an intermediate readout that still needs the "
                "imaging/behavior pipeline to establish mediation.",
            ),
        ),
        # Basic developmental mechanisms lack a standard-of-care landscape; do
        # not invent an existing-treatment comparison.
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
                "CPEB1 status (loss-of-function), gating an NRF2 redox-buffering program.",
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
                "Early (2-72h) lipid-peroxidation kinetics, not a static marker.",
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
                    "Unselected -- given regardless of CPEB1, ARID3A, or GPX4 status.",
                ),
            ),
            (
                "FOLFIRINOX",
                (
                    "No -- targets proliferation broadly rather than the "
                    "redox-buffering mechanism these hypotheses target.",
                    "Unselected, and reserved for fitter patients given its toxicity.",
                ),
            ),
        ),
    ),
}


def _candidate_comparison(
    table: _ComparisonTable, top: tuple[DemoHypothesis, ...]
) -> dict[str, Any]:
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
    if not table.existing_rows:
        return {}
    return {
        "summary": table.existing_summary,
        "axes": list(table.existing_axes),
        "rows": [
            {"method": method, "values": list(values)} for method, values in table.existing_rows
        ],
    }


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
        "main_research_directions": curated_main_research_directions(scenario_key(scenario)),
        "common_strengths": _COMMON_STRENGTHS,
        "common_weaknesses": _COMMON_WEAKNESSES,
        "emerging_themes": _EMERGING_THEMES,
        "strategic_recommendations": _STRATEGIC_RECOMMENDATIONS,
        **comparison_fields,
    }


# ruff: noqa: E501


# Unexpected directions combine or reframe existing ideas; they are not
# assertions of specific published findings.
_UNEXPECTED_DIRECTIONS: dict[str, tuple[dict[str, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        {
            "title": "Persister-State Convergence",
            "description": (
                "If the metabolic-wake-up pulse and the MazEF transcriptional "
                "state are tracking the same underlying dormancy program "
                "rather than two independent mechanisms, a real-time MazEF "
                "reporter could time the pulse itself -- closing the loop "
                "between biomarker and intervention instead of treating them "
                "as a validation pair and a separate therapeutic lead."
            ),
        },
        {
            "title": "The Matrix as a Drug-Delivery Barrier, Not Only a Metabolic One",
            "description": (
                "The spatial-microgradient hypothesis frames nutrient and "
                "oxygen limitation as what creates tolerance, but the same "
                "matrix structure could equally be limiting antibiotic "
                "penetration to those cells -- a confound that would make a "
                "single-drug rescue experiment unable to distinguish "
                "metabolic tolerance from simple diffusion failure."
            ),
        },
        {
            "title": "Inter-Isolate MazEF Stoichiometry as a Generalizability Risk",
            "description": (
                "Because the MazEF hypothesis already needs a rescue "
                "experiment across strains, an unanticipated risk is that "
                "the toxin-to-antitoxin ratio -- not merely MazEF's presence "
                "-- varies enough between clinical isolates that a single "
                "transcriptional signature never generalizes past the "
                "isolates it was defined in."
            ),
        },
    ),
    _SCENARIO_KEYS[1]: (
        {
            "title": "Complement Tagging as the Window's Molecular Clock",
            "description": (
                "Complement-associated tagging is proposed as a marker of "
                "which synapses get pruned, but it could instead set the "
                "calibration window's own onset and offset -- meaning a "
                "perturbation of the tagging machinery directly would shift "
                "when refinement happens, not only which synapses it "
                "touches."
            ),
        },
        {
            "title": "Pubertal-Stage-Indexed Window Timing",
            "description": (
                "The narrow refinement window is framed against a fixed "
                "postnatal-day range, but its true anchor may be individual "
                "pubertal-stage milestones rather than chronological age -- "
                "so indexing the window to a physiological marker of "
                "puberty, not age alone, could resolve animals the current "
                "design would otherwise misclassify as outside it."
            ),
        },
        {
            "title": "Circuit Synchrony as an Upstream Signal, Not Only a Downstream Readout",
            "description": (
                "Prefrontal synchrony is treated as mediating between "
                "synapse remodeling and behavior, but activity-dependent "
                "synchrony could instead partly precede structural pruning "
                "-- an upstream signal that guides which synapses get "
                "tagged, reversing the assumed causal order rather than "
                "only relaying it."
            ),
        },
    ),
    _SCENARIO_KEYS[2]: (
        {
            "title": "A Shared PTEN-NRF2 Buffering Spectrum",
            "description": (
                "CPEB1-low tumors and the ARID3A-high/PTEN-suppressed "
                "subgroup are treated as two independent stratification "
                "biomarkers, but PTEN and NRF2-pathway regulation intersect "
                "in redox control broadly -- raising the possibility that "
                "they are overlapping ends of a single buffering-capacity "
                "spectrum a combined, not either-or, biomarker panel could "
                "resolve."
            ),
        },
        {
            "title": "Using the Kinetic Predictor to Re-Bin the Static Biomarkers",
            "description": (
                "The early lipid-peroxidation kinetics assay is proposed as "
                "a standalone de-risking readout, but it could instead "
                "reclassify tumors ambiguous on the CPEB1 and ARID3A status "
                "markers -- resolving cases where the two genetic biomarkers "
                "disagree, rather than only validating models already "
                "stratified by them."
            ),
        },
        {
            "title": "Ferroptosis Resistance as a Chemotherapy-Induced State, Not Only a Baseline Trait",
            "description": (
                "All three proposals treat ferroptosis susceptibility as a "
                "pre-existing property to measure before treatment, but "
                "gemcitabine exposure itself could dynamically shift "
                "NRF2/GPX4 buffering capacity over the treatment course -- so "
                "a single pre-treatment biomarker read might miss resistance "
                "that only develops after the first dosing cycle."
            ),
        },
    ),
}


def curated_unexpected_directions(key: str) -> list[dict[str, Any]]:
    return [dict(item) for item in _UNEXPECTED_DIRECTIONS[key]]


def _overview_directions(
    top: tuple[DemoHypothesis, ...],
) -> list[dict[str, Any]]:
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
    return [
        {
            "title": item.title,
            "summary": item.mechanism,
            "detail": item.experiment,
            "uncertainty": item.review,
            "references": [
                {"title": evidence[item.evidence_index].title},
                {"title": evidence[(item.evidence_index + 1) % len(evidence)].title},
            ],
        }
        for item in hypotheses[:6]
    ]


# Contact rationales follow the first three real sources and explain their
# relevance to a specific research direction.
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
    return [
        {
            "research_direction": top[direction_index].title,
            "rationale": rationale,
            "example_hypothesis_ids": [hypothesis_ids[direction_index]],
        }
        for direction_index, rationale in directions
    ]


def _overview_nih_aims(top: tuple[DemoHypothesis, ...]) -> dict[str, Any]:
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
        "research_contact_groups": _overview_contact_groups(top, directions, ids),
        "knowledge_base": _overview_knowledge_base(evidence, hypotheses),
        "unexpected_research_directions": curated_unexpected_directions(scenario_key(scenario)),
    }


__all__ = ["_curated_meta_review"]
