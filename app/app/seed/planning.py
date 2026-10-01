"""Goal-detail planning lists for the three curated demo runs.

Content only: ``app.seed`` copies these into a demo run's setup block, where
they surface as the run's requirements, attributes, and criteria.

The lists are keyed by ``scenario_key`` exactly as the curated evidence and
proposal bundles are. Selecting them by substring-matching the display title
meant that renaming a demo, or adding one matching no substring, silently
handed the run another scenario's lists instead of failing.

Attributes use the structured 1-5-scale-plus-categorical shape
(``run_modes/attributes.py``, R12-5) rather than free prose: each scenario
supplies four scaled axes, goal-specific but mirroring
``DEFAULT_ATTRIBUTES``'s anchored-rubric shape, plus one categorical axis
whose value set is genuinely goal-derived (drawn from that scenario's own
competing-mechanism buckets), matching the published block's own Target
Area axis. Criteria are left unset so ``setup_config`` supplies
``DEFAULT_CRITERIA`` (R12-4) -- the published plan's three criteria are
goal-agnostic by design, so there is nothing scenario-specific to author.
"""

# The lists are reader-facing prose; keeping each statement intact makes the
# fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

from app.demo_seed_data import _SCENARIO_KEYS, DemoScenario, scenario_key
from app.run_modes import PlanningLists

_PLANNING_LISTS: dict[str, PlanningLists] = {
    _SCENARIO_KEYS[0]: PlanningLists(
        requirements=[
            "Separate phenotypic antibiotic tolerance from stable resistance.",
            "Use mature biofilms, clinical-isolate replication, and matched planktonic controls.",
            "Advance only mechanisms with a measurable perturbation, rescue, and kill-curve readout.",
            "Measure matrix permeability and cellular physiology in the same intact-biofilm experiment.",
            "Distinguish transient persister recovery from stable small-colony or resistance lineages.",
            "Do not infer clinical treatment benefit from the preclinical demonstration.",
        ],
        attributes=[
            {
                "name": "Mechanistic discrimination",
                "scale": {
                    "1": "No distinction from a generic growth-rate or stress-response confound",
                    "3": "Plausible mechanism with an untested confound",
                    "5": "Isolated from a growth-rate or stress-response confound by a rescue or genetic control",
                },
            },
            {
                "name": "Strain generalizability",
                "scale": {
                    "1": "Single-isolate observation only",
                    "3": "Reproduced in a second clinical isolate",
                    "5": "Reproduced across three or more clinical isolates spanning distinct genetic backgrounds",
                },
            },
            {
                "name": "Spatial resolution",
                "scale": {
                    "1": "Bulk, well-level readout only",
                    "3": "Coarse spatial readout (e.g. biofilm layer)",
                    "5": "Micro-region or single-cell resolved readout within an intact biofilm",
                },
            },
            {
                "name": "Replication readiness",
                "scale": {
                    "1": "No defined rescue or control arm",
                    "3": "A rescue arm is proposed but not yet validated",
                    "5": "A validated rescue or knockdown arm with a pre-specified kill-curve endpoint",
                },
            },
            {
                "name": "Primary tolerance mechanism",
                "values": [
                    "Metabolic state",
                    "Matrix or spatial niche",
                    "Genetic regulatory network",
                ],
            },
        ],
    ),
    _SCENARIO_KEYS[1]: PlanningLists(
        requirements=[
            "Resolve developmental timing rather than treating adolescence as a single window.",
            "Measure circuit, cellular, and behavioral outcomes in the same experimental framework.",
            "Include sex, subregion, locomotor, and stress controls before assigning a flexibility phenotype.",
            "Separate total synapse number from selective refinement of activity-defined synapses.",
            "Use temporally restricted perturbations and an age-matched adult control condition.",
            "Treat the model as developmental neuroscience, not a clinical disease mechanism.",
        ],
        attributes=[
            {
                "name": "Temporal specificity",
                "scale": {
                    "1": "No defined developmental window",
                    "3": "A candidate window is proposed but not pre-registered",
                    "5": "A pre-registered window compared against an explicit outside-window control",
                },
            },
            {
                "name": "Cell-type specificity",
                "scale": {
                    "1": "Bulk tissue manipulation only",
                    "3": "Cell-type enrichment without a targeted perturbation",
                    "5": "A targeted, cell-type-specific perturbation with an independent rescue",
                },
            },
            {
                "name": "Circuit-to-behavior linkage",
                "scale": {
                    "1": "No behavioral readout",
                    "3": "A behavioral readout is collected but not linked mechanistically",
                    "5": "Circuit and behavioral readouts in the same cohort with a pre-specified mediation test",
                },
            },
            {
                "name": "Multimodal integration",
                "scale": {
                    "1": "A single modality (e.g. histology only)",
                    "3": "Two modalities collected but not co-registered",
                    "5": "Circuit, cellular, and behavioral modalities co-registered in one longitudinal cohort",
                },
            },
            {
                "name": "Primary refinement mechanism",
                "values": [
                    "Microglial engulfment",
                    "Complement tagging",
                    "Circuit synchrony",
                ],
            },
        ],
    ),
    _SCENARIO_KEYS[2]: PlanningLists(
        requirements=[
            "Treat every proposed combination as a preclinical, biomarker-stratified hypothesis.",
            "Distinguish ferroptosis from apoptosis and other death pathways with orthogonal rescue controls.",
            "Validate a locked prediction in independent cell-line and organoid models before translation.",
            "Measure lipid peroxidation, redox state, and clonogenic survival on a time-resolved schedule.",
            "Test target engagement and a genetic rescue before interpreting a drug combination as pathway-specific.",
            "Do not infer patient benefit or recommend treatment from the demonstration data.",
        ],
        attributes=[
            {
                "name": "Death-pathway resolution",
                "scale": {
                    "1": "Viability endpoint only, death pathway unresolved",
                    "3": "Lipid peroxidation measured without an orthogonal death-pathway control",
                    "5": "Ferroptosis distinguished from apoptosis or necroptosis by orthogonal rescue",
                },
            },
            {
                "name": "Biomarker specificity",
                "scale": {
                    "1": "No biomarker stratification",
                    "3": "A candidate biomarker is proposed but not validated across models",
                    "5": "Response stratified by a biomarker validated across an independent model panel",
                },
            },
            {
                "name": "Experimental readiness",
                "scale": {
                    "1": "No defined perturbation-rescue pair",
                    "3": "A perturbation is proposed without a matched rescue",
                    "5": "A perturbation-rescue pair with a pre-specified clonogenic or lipid-peroxidation endpoint",
                },
            },
            {
                "name": "Translational caution",
                "scale": {
                    "1": "Findings framed as directly clinically actionable",
                    "3": "Framed cautiously but without an explicit preclinical-only statement",
                    "5": "Explicitly scoped as preclinical, gated on independent patient-derived organoid validation",
                },
            },
            {
                "name": "Primary resistance axis",
                "values": [
                    "NRF2/KEAP1 buffering",
                    "GPX4/lipid-peroxidation control",
                    "Redox-kinetic biomarker",
                ],
            },
        ],
    ),
}


def _scenario_planning_lists(scenario: DemoScenario | None) -> PlanningLists:
    """Return the goal detail fields shown for a curated demo run."""
    if scenario is None:
        return PlanningLists()
    return _PLANNING_LISTS[scenario_key(scenario)]
