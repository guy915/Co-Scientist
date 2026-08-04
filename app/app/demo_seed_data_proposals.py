"""Extra generation-wave proposals for each curated demo scenario.

Content only: ``demo_seed_data`` expands these seeds into full hypothesis
records and derives the evolved and second-pass generations from them.
"""

# Curated publication titles and reader-facing prose are intentionally kept
# intact here; wrapping individual literals would make this data hard to audit.
# ruff: noqa: E501, RUF001

from __future__ import annotations

from app.demo_seed_data_scenarios import _SCENARIO_KEYS
from app.demo_seed_data_types import DemoProposal

_PROPOSALS: dict[str, tuple[DemoProposal, ...]] = {
    _SCENARIO_KEYS[0]: (
        DemoProposal(
            "Oxygen-gradient collapse reveals an antibiotic-sensitive sublayer",
            "In mature S. aureus biofilms, a spatially restricted oxygen deficit may create a low-energy survivor compartment; restoring oxygen availability immediately before antibiotic challenge should shrink that compartment without requiring biofilm dispersal.",
            "Use oxygen microsensors, redox imaging, and spatial CFU recovery in 48-hour clinical-isolate biofilms. Compare controlled oxygenation, sham handling, and matrix-disruption controls before a fixed vancomycin pulse; pre-specify a spatial kill-gradient as the primary endpoint.",
            "Oxygen manipulation can alter antibiotic chemistry and growth independently of a tolerant state, so the design needs matched planktonic and abiotic antibiotic-stability controls.",
            3,
        ),
        DemoProposal(
            "MazEF–ica epistasis partitions biomass from tolerance",
            "MazEF-dependent tolerance may be separable from ica-dependent biomass accumulation: a genetic epistasis experiment could identify whether the same regulatory branch controls both features or whether matrix production merely masks a distinct survivor program.",
            "Construct complemented and double-perturbation strains in two genetic backgrounds, then quantify matrix composition, growth rate, antibiotic kill curves, and survivor regrowth. Require restoration by complementation before assigning a causal branch.",
            "Strain-specific regulatory wiring could make a clean result non-generalizable; replication across clinical isolates is essential before treating the branch as conserved.",
            0,
        ),
        DemoProposal(
            "Persister exit kinetics nominate a sequential killing window",
            "A survivor subpopulation that is metabolically silent during vancomycin exposure may become transiently vulnerable while returning to growth; the duration of that exit window could determine whether a sequential rather than simultaneous combination is informative.",
            "After a vancomycin pulse, sample biofilms every two hours for microcalorimetry, ATP, membrane potential, and viable counts; apply a second agent at prespecified intervals and use kill-curve area rather than one endpoint.",
            "A second agent can appear selective simply because the first agent changed total biomass, so pair all schedules with equal-exposure and order-reversed controls.",
            5,
        ),
        DemoProposal(
            "Small-colony variants are a reversible lineage state, not an endpoint",
            "Antibiotic-exposed small-colony variants may be the observable output of a reversible metabolic lineage state that precedes stable resistance, allowing lineage tracking to distinguish transient tolerance from genetic escape.",
            "Barcode a clinical isolate, grow implant-surface biofilms, and follow colony morphology, whole-genome sequence, respiration, and antibiotic response through exposure and drug-free recovery. Define reversibility before assigning a resistance mechanism.",
            "Barcoding can itself perturb fitness and morphology; unbarcoded replicate populations and reciprocal re-isolation are needed to validate the lineage interpretation.",
            4,
        ),
        DemoProposal(
            "Respiratory stimulation has a narrow therapeutic index in established biofilms",
            "A metabolic stimulus that suppresses early biofilm formation may behave differently in established biofilms; a narrow dose-and-timing window may increase antibiotic susceptibility before it increases biomass or dispersal.",
            "Perform a factorial dose-by-timing experiment in 24-, 48-, and 72-hour biofilms with respiration, biomass, dispersal, and antibiotic kill as co-primary readouts. Use a blinded decision rule to identify a window worth mechanistic follow-up.",
            "A favourable in-vitro window may depend on nutrient-rich media, so the result must be repeated in host-mimicking medium before it is interpreted as broadly relevant.",
            2,
        ),
        DemoProposal(
            "Matrix permeability and cell state make independent contributions to tolerance",
            "The same antibiotic failure may arise from poor penetration or from a metabolically protected cell state; measuring both within intact biofilms can test whether permeability predicts killing after accounting for local physiology.",
            "Combine fluorescent antibiotic analog measurements with oxygen mapping, ATP reporters, and local viability imaging across intact biofilms. Fit a preregistered model comparing permeability-only, physiology-only, and combined explanations.",
            "Fluorescent analogs need not preserve native drug transport, so the key permeability conclusion requires orthogonal confirmation with quantitative mass spectrometry.",
            1,
        ),
    ),
    _SCENARIO_KEYS[1]: (
        DemoProposal(
            "Dopamine-gated microglial surveillance selects a plastic synapse subset",
            "Reward-linked dopaminergic input during adolescence may change microglial surveillance of a subset of frontal synapses, thereby coupling salient experience to later circuit flexibility rather than globally increasing pruning.",
            "In adolescent mice, pair longitudinal two-photon imaging of microglia and labeled frontal boutons with a rule-learning manipulation; perturb D1/D2 or P2RY12 signaling only during the imaging window and measure later set shifting.",
            "Dopamine manipulations can change behavior directly, so microglial-contact and bouton outcomes must be analyzed independently of task performance.",
            5,
        ),
        DemoProposal(
            "Complement tagging encodes synapse history rather than bulk elimination",
            "Complement-associated tagging may mark synapses with a particular recent activity history for refinement, making activity-tagged synapse identity a better predictor of engulfment than total spine density.",
            "Combine activity-dependent labeling, complement staining, and microglial engulfment quantification across early, mid, and late adolescence; add cell-type-specific complement perturbation and rescue arms.",
            "Colocalization alone cannot identify a causal tag, so the study needs a manipulation that changes tagging while preserving the underlying activity pattern.",
            0,
        ),
        DemoProposal(
            "Inhibitory maturation sets the behavioral consequence of pruning",
            "The effect of adolescent excitatory-synapse refinement on flexibility may depend on concurrent maturation of local inhibition; altering pruning without measuring excitation-inhibition balance could conflate two linked developmental processes.",
            "Measure interneuron recruitment, pyramidal-cell activity, spine dynamics, and rule-shift behavior in the same animals. Test a temporally restricted perturbation with electrophysiological rescue as the falsification criterion.",
            "Longitudinal multimodal measurement is technically demanding and may bias the sample; use a staged design with a replication cohort reserved for behavior.",
            1,
        ),
        DemoProposal(
            "Hippocampal–prefrontal coupling mediates a delayed flexibility phenotype",
            "Adolescent local prefrontal refinement may influence cognitive flexibility indirectly by stabilizing hippocampal-prefrontal coordination, producing a neural intermediate that predicts behavior better than spine count alone.",
            "Record simultaneous hippocampal and prefrontal activity during reversal learning before and after an adolescent refinement perturbation; test mediation with preregistered temporal-directionality analyses.",
            "Connectivity measures are correlational unless the timing of the perturbation is used to establish a causal sequence, so behavioral correlation is not sufficient evidence.",
            4,
        ),
        DemoProposal(
            "A sex- and age-resolved critical window explains heterogeneous outcomes",
            "The apparent inconsistency of pruning interventions may reflect a narrow age window whose timing differs by sex and prefrontal subregion, rather than a single adolescent mechanism.",
            "Use a balanced factorial cohort across sex, age window, and mPFC/OFC target; quantify microglial engulfment, spine maturation, and reversal learning with all interaction tests prespecified.",
            "The expanded design risks inadequate power for interactions, so it should begin with a pilot estimating variance and commit to a powered confirmatory cohort.",
            2,
        ),
        DemoProposal(
            "Experience changes the selectivity, not the amount, of adolescent refinement",
            "Cognitive training during adolescence may bias which synapses are stabilized or removed without changing total pruning, offering an explanation for why bulk spine measures can miss behaviorally meaningful remodeling.",
            "Expose mice to structured rule-switch training or matched handling, then track activity-tagged synapses, microglial contacts, total spine density, and adult flexibility. Treat selective stabilization as the primary outcome.",
            "Training can alter stress and arousal, so yoked reward, locomotion, and corticosterone controls are needed before attributing the result to experience-dependent refinement.",
            3,
        ),
    ),
    _SCENARIO_KEYS[2]: (
        DemoProposal(
            "CUL2 status defines an NRF2-stabilized ferroptosis-resistant state",
            "CUL2-high PDAC models may maintain NRF2 signalling by competing for KEAP1, creating a biomarker-defined ferroptosis-resistant state that can be separated from generic gemcitabine resistance.",
            "Stratify cell lines and organoids by CUL2 expression, quantify KEAP1-NRF2 engagement, lipid peroxidation, GPX4, and gemcitabine response, then test CUL2 knockdown with rescue by stabilized NRF2.",
            "CUL2 has broad cellular functions, so a rescue that isolates the NRF2 branch is necessary before any ferroptosis-specific interpretation.",
            3,
        ),
        DemoProposal(
            "USP8 creates a pharmacodynamic delay in NRF2 turnover",
            "USP8-mediated stabilization of NRF2 may determine how long antioxidant defenses persist after gemcitabine exposure, making turnover kinetics a more useful combination biomarker than a static baseline expression measurement.",
            "Perform pulse-chase NRF2 measurements after gemcitabine in parental and resistant PDAC models with USP8 perturbation; couple them to live lipid-peroxidation imaging and clonogenic survival.",
            "Proteostasis effects can be pleiotropic, so the experiment requires catalytic-dead USP8 and NRF2-rescue controls rather than inhibitor-only evidence.",
            1,
        ),
        DemoProposal(
            "TSPAN15–ITGB1 signaling couples adhesion to GPX4-dependent survival",
            "TSPAN15 may sustain an integrin-linked FAK/AKT/mTOR program that raises GPX4 and protects a matrix-adherent PDAC subpopulation from gemcitabine-associated ferroptosis.",
            "Compare two-dimensional, matrix-rich organoid, and co-culture conditions after TSPAN15 knockdown; measure ITGB1 stability, kinase signaling, GPX4, lipid peroxidation, and death-pathway rescue.",
            "An adhesion-dependent phenotype may be model-specific, so the same rank order must be observed in at least one patient-derived organoid system.",
            1,
        ),
        DemoProposal(
            "ADSL loss reroutes purine stress into ferroptosis escape",
            "Reduced ADSL may create a metabolic state in which purine-pathway stress and antioxidant signalling jointly lower ferroptosis sensitivity, offering a mechanistically distinct route to gemcitabine resistance.",
            "Use isogenic ADSL perturbation in parental and resistant models, quantify purine intermediates, CARMA3, NRF2 activity, lipid peroxidation, and drug response, then restore ADSL as a rescue.",
            "Metabolic intermediates are highly context-dependent, so flux measurements rather than steady-state metabolite abundance are needed for a causal claim.",
            2,
        ),
        DemoProposal(
            "CASC9 marks an inflammatory-redox feedback state with actionable heterogeneity",
            "A CASC9–NRF2–NF-κB feedback state may identify PDAC models in which oxidative-stress modulation enhances gemcitabine response without assuming that all tumors share the same redox dependency.",
            "Profile CASC9, NRF2 targets, NF-κB activity, and drug response across organoids; perturb CASC9 and use ferroptosis, apoptosis, and necroptosis rescue panels to define the death mechanism.",
            "The observed benefit could reflect non-ferroptotic cell death, so the proposal is only supported if orthogonal ferroptosis readouts and rescue experiments converge.",
            4,
        ),
        DemoProposal(
            "Early redox trajectories predict durable response better than endpoint viability",
            "The time-resolved trajectory of lipid peroxidation, glutathione depletion, and mitochondrial morphology may distinguish a reversible stress response from a ferroptosis-linked combination response before clonogenic outcomes are known.",
            "Collect 2-, 8-, 24-, and 72-hour multimodal redox measurements in a training panel, build a locked predictor, and validate it prospectively in independent patient-derived organoids.",
            "A predictive signature can overfit a small panel, so model development and validation must be separated and the final predictor reported with uncertainty.",
            0,
        ),
    ),
}
