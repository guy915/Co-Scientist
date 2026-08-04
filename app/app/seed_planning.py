"""Goal-detail planning lists for the three curated demo runs.

Content only: ``app.seed`` copies these into a demo run's setup block, where
they surface as the run's requirements, attributes, and criteria.

The lists are keyed by ``scenario_key`` exactly as the curated evidence and
proposal bundles are. Selecting them by substring-matching the display title
meant that renaming a demo, or adding one matching no substring, silently
handed the run another scenario's lists instead of failing.
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
            "Spatially resolved",
            "Mechanistically discriminating",
            "Preclinical and falsifiable",
            "Strain-aware",
            "Replication-ready",
        ],
        criteria=[
            "Causal specificity",
            "Biofilm relevance",
            "Experimental tractability",
            "Safety",
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
            "Longitudinal",
            "Cell-type specific",
            "Behaviorally anchored",
            "Window-specific",
            "Multimodal",
        ],
        criteria=[
            "Temporal specificity",
            "Circuit-to-behavior link",
            "Causal perturbation",
            "Replicability",
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
            "Mechanistically explicit",
            "Biomarker-guided",
            "Experiment-ready",
            "Death-pathway resolved",
            "Preclinical only",
        ],
        criteria=[
            "Pathway specificity",
            "Model generalizability",
            "Combination rationale",
            "Safety",
        ],
    ),
}


def _scenario_planning_lists(scenario: DemoScenario | None) -> PlanningLists:
    """Return the goal detail fields shown for a curated demo run."""
    if scenario is None:
        return PlanningLists()
    return _PLANNING_LISTS[scenario_key(scenario)]
