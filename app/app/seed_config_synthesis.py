"""Curated Supervisor-synthesized guidance for the three demo scenarios.

``config_synthesis.attributes`` (R12-17, rendered as "Stratification
Attributes") and ``workflow_plan.review_phase.critical_criteria`` (R12-18/
R12-23, rendered as "Evaluation Criteria" and "Review Summary") are fields
a real run's Supervisor synthesizes once, per goal, before any hypothesis
exists. A curated demo has no Supervisor call to draw them from, so this
module hand-authors the same shape -- goal-specific, not the user-authored
setup attributes/criteria ``seed_planning.py`` owns (see
``report/markdown/supervisor.py``'s vocabulary warning: same English words,
two different published sections).

Split out of ``seed_overview``/``seed_scenario`` so each stays within the
line-count cap; content only, keyed by ``scenario_key`` exactly as the
other curated content modules are.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from app.demo_seed_data import _SCENARIO_KEYS

# Up to three named 1-5 scoring axes per scenario (config_synthesis.attributes).
_STRATIFICATION_ATTRIBUTES: dict[str, tuple[dict[str, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        {
            "name": "Mechanistic specificity",
            "rubric": "1 = generic stress or growth-rate explanation; 3 = plausible with an untested confound; 5 = isolated from growth-rate and generic-stress alternatives by a rescue or genetic control",
        },
        {
            "name": "Biofilm relevance",
            "rubric": "1 = planktonic-only evidence; 3 = tested in young or immature biofilms; 5 = tested in mature, clinical-isolate biofilms with matched planktonic controls",
        },
        {
            "name": "Translational caution",
            "rubric": "1 = implies treatment readiness; 3 = notes preclinical status without controls; 5 = explicitly scoped as preclinical and gated on strain-aware replication",
        },
    ),
    _SCENARIO_KEYS[1]: (
        {
            "name": "Temporal precision",
            "rubric": "1 = adolescence treated as one uniform window; 3 = a window is proposed without pre-registration; 5 = a pre-registered window compared against an explicit outside-window control",
        },
        {
            "name": "Circuit-to-behavior linkage",
            "rubric": "1 = circuit and behavior measured separately; 3 = both measured but not mediation-tested; 5 = the same cohort links circuit change to behavior with a pre-specified mediation analysis",
        },
        {
            "name": "Causal perturbation strength",
            "rubric": "1 = correlational only; 3 = a perturbation exists but lacks a rescue; 5 = a targeted perturbation with an independent rescue arm",
        },
    ),
    _SCENARIO_KEYS[2]: (
        {
            "name": "Death-pathway specificity",
            "rubric": "1 = viability-only readout; 3 = lipid peroxidation measured without an orthogonal control; 5 = ferroptosis distinguished from apoptosis or necroptosis by orthogonal rescue",
        },
        {
            "name": "Biomarker stratification",
            "rubric": "1 = unselected panel only; 3 = a candidate biomarker proposed but unvalidated; 5 = response stratified by a biomarker validated across an independent model panel",
        },
        {
            "name": "Combination rationale",
            "rubric": "1 = no mechanistic link to gemcitabine response; 3 = a plausible link without dose ordering; 5 = a mechanistic link with dose ordering and normal-cell toxicity characterized",
        },
    ),
}


def _questions(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    """Build a criterion's reviewer-question list from name/question pairs."""
    return [{"name": name, "question": question} for name, question in pairs]


# Four goal-specific critical criteria per scenario, each with a prose
# description (R12-23b) and three named reviewer questions (R12-23).
_CRITICAL_CRITERIA: dict[str, tuple[dict[str, Any], ...]] = {
    _SCENARIO_KEYS[0]: (
        {
            "name": "Causal specificity",
            "description": "Whether the proposal isolates its mechanism from generic growth-rate or stress-response confounds.",
            "questions": _questions(
                (
                    "Confound control",
                    "Does the design include a control that rules out a generic growth-rate or stress-response explanation?",
                ),
                (
                    "Rescue evidence",
                    "Is a rescue or knockdown/knockout arm specified that would restore the untreated phenotype?",
                ),
                (
                    "Causal chain",
                    "Does the proposal state which perturbation, readout, and expected direction would falsify the mechanism?",
                ),
            ),
        },
        {
            "name": "Biofilm relevance",
            "description": "Whether the evidence comes from mature, clinical-isolate biofilms rather than planktonic or immature-biofilm surrogates.",
            "questions": _questions(
                (
                    "Biofilm maturity",
                    "Are the biofilms mature (typically 48 hours or more) rather than early-attachment surrogates?",
                ),
                (
                    "Isolate diversity",
                    "Does the design include more than one clinical isolate or genetic background?",
                ),
                (
                    "Planktonic control",
                    "Is a matched planktonic control included to separate biofilm-specific effects from general antibiotic response?",
                ),
            ),
        },
        {
            "name": "Experimental tractability",
            "description": "Whether the proposed measurements and interventions are achievable with standard biofilm and microbiology methods.",
            "questions": _questions(
                (
                    "Readout feasibility",
                    "Can the primary readout (e.g. CFU, ATP, kill-curve) be measured reliably in an intact biofilm?",
                ),
                (
                    "Timeline realism",
                    "Is the proposed timeline consistent with standard biofilm growth and antibiotic-exposure protocols?",
                ),
                (
                    "Technical risk",
                    "Are technically demanding steps (e.g. spatial imaging, epistasis strains) sequenced after simpler validation steps?",
                ),
            ),
        },
        {
            "name": "Safety",
            "description": "Whether the proposal avoids implying clinical treatment guidance from preclinical biofilm data.",
            "questions": _questions(
                (
                    "Scope statement",
                    "Does the proposal explicitly frame its findings as preclinical rather than treatment guidance?",
                ),
                (
                    "Dose framing",
                    "Are antibiotic or metabolic-stimulus doses framed as experimental conditions, not therapeutic recommendations?",
                ),
                (
                    "Overclaim check",
                    "Does the proposal avoid asserting that an in-vitro mechanism is already established in patients?",
                ),
            ),
        },
    ),
    _SCENARIO_KEYS[1]: (
        {
            "name": "Temporal specificity",
            "description": "Whether the proposal targets a defined adolescent window rather than treating adolescence as one uniform period.",
            "questions": _questions(
                (
                    "Window definition",
                    "Is the candidate developmental window defined and pre-registered before data collection?",
                ),
                (
                    "Outside-window control",
                    "Does the design include an age-matched control perturbed outside the candidate window?",
                ),
                (
                    "Timing confound",
                    "Does the design rule out that an observed effect reflects total exposure duration rather than window timing?",
                ),
            ),
        },
        {
            "name": "Circuit-to-behavior link",
            "description": "Whether circuit-level and behavioral measures are collected in the same animals with a stated link between them.",
            "questions": _questions(
                (
                    "Same-subject design",
                    "Are circuit and behavioral measures collected in the same animals rather than separate cohorts?",
                ),
                (
                    "Mediation test",
                    "Is a mediation or equivalent analysis specified linking the circuit measure to the behavioral outcome?",
                ),
                (
                    "Readout specificity",
                    "Is the behavioral task specific to cognitive flexibility rather than general locomotor or exploratory activity?",
                ),
            ),
        },
        {
            "name": "Causal perturbation",
            "description": "Whether the proposal manipulates the candidate mechanism directly rather than relying on observational correlation.",
            "questions": _questions(
                (
                    "Targeted manipulation",
                    "Does the proposal specify a targeted, not systemic, perturbation of the candidate mechanism?",
                ),
                (
                    "Rescue arm",
                    "Is a rescue or reversal condition included to support a causal, not merely correlational, claim?",
                ),
                (
                    "Cell-type specificity",
                    "Is the perturbation restricted to the implicated cell type rather than a broad inflammatory or systemic manipulation?",
                ),
            ),
        },
        {
            "name": "Replicability",
            "description": "Whether the design anticipates and controls for known confounds in developmental behavioral neuroscience.",
            "questions": _questions(
                (
                    "Sex as a variable",
                    "Does the design include, or explicitly justify excluding, sex as a biological variable?",
                ),
                (
                    "Locomotor control",
                    "Are locomotor and exploratory controls included to rule out non-specific behavioral effects?",
                ),
                (
                    "Cohort power",
                    "Is the cohort size, or a pilot-then-confirm plan, specified to support the proposed interaction tests?",
                ),
            ),
        },
    ),
    _SCENARIO_KEYS[2]: (
        {
            "name": "Pathway specificity",
            "description": "Whether the proposal distinguishes ferroptosis from other death pathways rather than treating cell death as a single endpoint.",
            "questions": _questions(
                (
                    "Death-pathway control",
                    "Does the design include an orthogonal death-pathway control (e.g. an apoptosis or necroptosis inhibitor) alongside the ferroptosis readout?",
                ),
                (
                    "Lipid peroxidation evidence",
                    "Is lipid peroxidation measured directly rather than inferred solely from viability loss?",
                ),
                (
                    "Rescue specificity",
                    "Does a proposed rescue restore viability specifically through the ferroptosis-linked mechanism rather than general antioxidant protection?",
                ),
            ),
        },
        {
            "name": "Model generalizability",
            "description": "Whether the finding is tested beyond a single cell line or model system.",
            "questions": _questions(
                (
                    "Model diversity",
                    "Does the design include both cell-line and organoid or patient-derived models?",
                ),
                (
                    "Independent validation",
                    "Is an independent validation set reserved and not used during model or predictor development?",
                ),
                (
                    "Biomarker range",
                    "Is the candidate biomarker tested across a range of expression rather than only extreme high/low models?",
                ),
            ),
        },
        {
            "name": "Combination rationale",
            "description": "Whether the proposed drug combination has a specified mechanistic link rather than an empirical pairing.",
            "questions": _questions(
                (
                    "Mechanistic link",
                    "Does the proposal state the specific molecular link between the perturbation and gemcitabine sensitization?",
                ),
                (
                    "Dose ordering",
                    "Is the order and timing of combination dosing specified and justified?",
                ),
                (
                    "Synergy evidence",
                    "Is a synergy or potentiation analysis specified beyond a simple additive-effect comparison?",
                ),
            ),
        },
        {
            "name": "Safety",
            "description": "Whether the proposal accounts for normal-tissue toxicity and avoids treatment claims from preclinical data.",
            "questions": _questions(
                (
                    "Normal-cell toxicity",
                    "Does the design include a normal or non-tumor cell control for combination toxicity?",
                ),
                (
                    "Scope statement",
                    "Does the proposal explicitly frame its findings as preclinical and not patient-care guidance?",
                ),
                (
                    "Therapeutic index",
                    "Is a therapeutic index or comparable safety margin considered before combination doses are proposed?",
                ),
            ),
        },
    ),
}


def curated_stratification_attributes(key: str) -> list[dict[str, str]]:
    """Return one scenario's Supervisor-synthesized stratification axes."""
    return [dict(item) for item in _STRATIFICATION_ATTRIBUTES[key]]


def curated_critical_criteria(key: str) -> list[dict[str, Any]]:
    """Return one scenario's Supervisor-synthesized evaluation criteria."""
    return [
        {**item, "questions": [dict(q) for q in item["questions"]]}
        for item in _CRITICAL_CRITERIA[key]
    ]
