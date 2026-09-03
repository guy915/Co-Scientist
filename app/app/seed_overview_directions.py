"""Curated ``unexpected_research_directions`` for the three demo scenarios.

Task B (R12-23's "Research directions" half): the published MASH exemplar's
own "Unexpected Research Directions" block -- three bolded-name-plus-prose
bullets naming a genuinely novel strategic direction, distinct from a
scenario's main research directions (``_curated_research_overview``'s own
``research_directions``, restated from the top-3 hypotheses) and from a
pattern merely observed across them. A real run's terminal synthesis call
produces these; a curated demo has no such call, so this module hand-authors
the same shape -- one direction per bullet, each genuinely unanticipated by
the scenario's own top-3 hypotheses rather than a restatement of one.

Split out of ``seed_overview`` so that module stays within the line-count
cap; keyed by ``scenario_key`` exactly as the other curated content modules
(``seed_config_synthesis``, ``seed_evidence``) are.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from app.demo_seed_data import _SCENARIO_KEYS

# Grounded in each scenario's own top-3 hypotheses
# (demo_seed_data_scenarios.py) -- every entry connects two of those
# hypotheses in a way neither states on its own, or reframes one of their
# shared assumptions, rather than describing a specific published finding.
# Order matches ``_curated_research_overview``'s own ``top = hypotheses[:3]``
# only loosely: these are cross-cutting, not indexed to one hypothesis.
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
    """Return one scenario's synthesized unexpected research directions."""
    return [dict(item) for item in _UNEXPECTED_DIRECTIONS[key]]
