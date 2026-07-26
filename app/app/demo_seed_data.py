"""Curated, clearly illustrative scenarios for the default demo runs.

The startup demos are product examples, not generated scientific findings.
They use real, linked publications as context but keep every proposed
mechanism and experiment explicitly exploratory.  The data is intentionally
small enough to browse while still exercising the complete run surface.
"""

# Curated publication titles and reader-facing prose are intentionally kept
# intact here; wrapping individual literals would make this data hard to audit.
# ruff: noqa: E501, RUF001

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
    duration_seconds: float
    elo_ceiling: int
    elo_step: int
    evolution_count: int
    second_pass_count: int
    evidence: tuple[DemoEvidence, ...]
    hypotheses: tuple[DemoHypothesis, ...]


DEMO_SEED_VERSION = 7

DEMO_SCENARIOS: dict[str, DemoScenario] = {
    "What mechanisms drive antibiotic resistance in Staphylococcus aureus "
    "biofilms, and which metabolic pathways could be targeted to restore "
    "susceptibility?": DemoScenario(
        title="Metabolic Vulnerabilities in S. aureus Biofilms",
        summary=(
            "Illustrative demo: a ranked set of preclinical proposals for "
            "testing whether metabolic state contributes to biofilm antibiotic "
            "tolerance. It is not treatment guidance."
        ),
        meta_review=(
            "The proposals converge on metabolic state as a modulator of "
            "tolerance, but each needs strain-aware validation in a mature "
            "biofilm model before any translational interpretation."
        ),
        direction=(
            "Separate growth-rate effects from biofilm-specific tolerance by "
            "pairing viability, matrix, and antibiotic-kill measurements."
        ),
        duration_seconds=1628.0,
        elo_ceiling=1386,
        elo_step=15,
        evolution_count=6,
        second_pass_count=0,
        evidence=(
            DemoEvidence(
                title=(
                    "The Toxin-Antitoxin MazEF Drives Staphylococcus aureus "
                    "Biofilm Formation, Antibiotic Tolerance, and Chronic "
                    "Infection"
                ),
                authors=("Ma et al.",),
                year=2019,
                url="https://pubmed.ncbi.nlm.nih.gov/31772059/",
                abstract=(
                    "A mouse and strain-comparison study linked the MazEF "
                    "system to S. aureus biofilm antibiotic tolerance."
                ),
            ),
            DemoEvidence(
                title="Antimicrobial Treatment of Staphylococcus aureus Biofilms",
                authors=("Tuon et al.",),
                year=2023,
                url="https://pubmed.ncbi.nlm.nih.gov/36671287/",
                abstract=(
                    "A review describes why biofilm physiology can make "
                    "standard susceptibility measurements poorly predictive."
                ),
            ),
        ),
        hypotheses=(
            DemoHypothesis(
                title="Metabolic wake-up before vancomycin exposure",
                statement=(
                    "A short, non-growth-promoting metabolic pulse before "
                    "vancomycin may reduce tolerance in mature S. aureus "
                    "biofilms."
                ),
                mechanism=(
                    "The proposal tests whether temporarily increasing "
                    "metabolic activity makes antibiotic targets more exposed "
                    "without dispersing the biofilm."
                ),
                expected_effect=(
                    "Greater antibiotic killing than vancomycin alone, with "
                    "no increase in planktonic growth."
                ),
                experiment=(
                    "Grow 48-hour biofilms from three clinical isolates; "
                    "compare pulse-plus-vancomycin with matched vehicle and "
                    "antibiotic-only controls; quantify CFU, ATP, and biomass."
                ),
                review=(
                    "Strongly testable, but the pulse must be shown not to "
                    "increase biomass or select a faster-growing subpopulation."
                ),
                elo=1368,
                evidence_index=1,
            ),
            DemoHypothesis(
                title="MazEF state predicts a tolerant biofilm subpopulation",
                statement=(
                    "MazEF-associated transcriptional state may identify the "
                    "biofilm cells that survive bactericidal antibiotic pulses."
                ),
                mechanism=(
                    "MazEF is treated as a state marker and perturbation point, "
                    "not as a validated therapeutic target."
                ),
                expected_effect=(
                    "Survivor-enriched cells would show a reproducible MazEF "
                    "signature relative to killed cells."
                ),
                experiment=(
                    "Perform time-resolved RNA profiling before and after an "
                    "antibiotic pulse, then validate the candidate state with "
                    "targeted reporters and knockdown/rescue."
                ),
                review=(
                    "Mechanistically interesting, though causality requires a "
                    "rescue experiment rather than expression correlation alone."
                ),
                elo=1324,
                evidence_index=0,
            ),
            DemoHypothesis(
                title="Matrix-restricted nutrient access creates a reversible tolerance niche",
                statement=(
                    "Nutrient gradients within the matrix may create a reversible "
                    "low-energy niche that can be selectively disrupted."
                ),
                mechanism=(
                    "The proposal distinguishes a spatial metabolic niche from "
                    "a population-wide resistance mutation."
                ),
                expected_effect=(
                    "Nutrient and oxygen microgradients would co-localize with "
                    "lower antibiotic killing in intact biofilms."
                ),
                experiment=(
                    "Map oxygen and metabolic activity across intact biofilms, "
                    "then compare local killing after matrix modulation."
                ),
                review=(
                    "Potentially informative but technically demanding; establish "
                    "the spatial readout before testing intervention."
                ),
                elo=1278,
                evidence_index=1,
            ),
        ),
    ),
    "How does synaptic pruning in the prefrontal cortex contribute to "
    "cognitive flexibility during adolescent development?": DemoScenario(
        title="Adolescent Prefrontal Circuit Refinement",
        summary=(
            "Illustrative demo: testable developmental-neuroscience proposals "
            "linking adolescent circuit refinement to cognitive flexibility; "
            "not a clinical interpretation."
        ),
        meta_review=(
            "The best path is a longitudinal design that measures circuit "
            "refinement and behavior in the same animals, while avoiding a "
            "claim that pruning alone determines cognition."
        ),
        direction=(
            "Align the timing of microglial engagement, synapse remodeling, "
            "and rule-shift behavior rather than treating adolescence as one "
            "uniform developmental window."
        ),
        duration_seconds=2314.0,
        elo_ceiling=1337,
        elo_step=14,
        evolution_count=9,
        second_pass_count=1,
        evidence=(
            DemoEvidence(
                title="Microglial Pruning of Synapses in the Prefrontal Cortex During Adolescence",
                authors=("Mallya et al.",),
                year=2019,
                url="https://pubmed.ncbi.nlm.nih.gov/29668872/",
                abstract=(
                    "A rat study reported a transient increase in microglial "
                    "engulfment of prefrontal synaptic elements during adolescence."
                ),
            ),
            DemoEvidence(
                title="Reorganization of adolescent prefrontal cortex circuitry is required for mouse cognitive maturation",
                authors=("Kätzel et al.",),
                year=2023,
                url="https://pubmed.ncbi.nlm.nih.gov/37979584/",
                abstract=(
                    "A mouse study linked adolescent prefrontal circuit "
                    "reorganization to later cognitive maturation."
                ),
            ),
        ),
        hypotheses=(
            DemoHypothesis(
                title="A narrow microglial refinement window calibrates rule shifting",
                statement=(
                    "Transient microglial synapse engagement during mid-adolescence "
                    "may calibrate later prefrontal rule-shift performance."
                ),
                mechanism=(
                    "The proposal predicts timing-specific, rather than chronic, "
                    "microglial influence on circuit refinement."
                ),
                expected_effect=(
                    "Perturbation within the candidate window would alter adult "
                    "set-shifting without a comparable effect outside that window."
                ),
                experiment=(
                    "Track prefrontal microglia and dendritic spines across "
                    "adolescence, perturb one predefined window, and assess an "
                    "adult attentional set-shifting task."
                ),
                review=(
                    "High value if the temporal specificity holds; pre-register "
                    "age windows and include locomotor controls."
                ),
                elo=1376,
                evidence_index=1,
            ),
            DemoHypothesis(
                title="Complement tagging separates flexible from persistent synapses",
                statement=(
                    "Complement-associated tagging may preferentially mark a "
                    "subset of adolescent prefrontal synapses for refinement."
                ),
                mechanism=(
                    "The proposal asks whether synapse identity and activity, not "
                    "bulk synapse number, predict microglial engagement."
                ),
                expected_effect=(
                    "Tagged synapses would show distinct activity histories and "
                    "be selectively enriched among engulfed material."
                ),
                experiment=(
                    "Combine activity labeling with complement and microglial "
                    "engulfment measurements in a longitudinal adolescent cohort."
                ),
                review=(
                    "A crisp mechanistic question, but it needs a cell-type "
                    "specific manipulation to avoid a broad inflammatory confound."
                ),
                elo=1328,
                evidence_index=0,
            ),
            DemoHypothesis(
                title="Circuit synchrony mediates the behavior link",
                statement=(
                    "The effect of adolescent refinement on flexibility may be "
                    "mediated by maturation of prefrontal network synchrony."
                ),
                mechanism=(
                    "Circuit-level synchrony is positioned as an intermediate "
                    "readout between synapse remodeling and behavior."
                ),
                expected_effect=(
                    "Animals with altered refinement would show a matching change "
                    "in task-relevant prefrontal synchrony."
                ),
                experiment=(
                    "Record prefrontal population activity during rule shifts and "
                    "test whether synchrony mediates the perturbation effect."
                ),
                review=(
                    "Useful integrative hypothesis, though it depends on the "
                    "higher-risk imaging and behavioral pipeline."
                ),
                elo=1286,
                evidence_index=1,
            ),
        ),
    ),
    "What are the key molecular regulators of ferroptosis in pancreatic cancer "
    "cells, and how might their modulation enhance chemotherapy sensitivity?": DemoScenario(
        title="Ferroptosis Sensitization in Pancreatic Cancer",
        summary=(
            "Illustrative demo: preclinical hypotheses for studying ferroptosis "
            "regulators alongside chemotherapy in pancreatic cancer models; not "
            "clinical advice."
        ),
        meta_review=(
            "The proposals share a redox-resistance theme. Priority should go "
            "to biomarker-stratified combinations with orthogonal death-pathway "
            "controls before moving beyond cell and organoid models."
        ),
        direction=(
            "Test whether a molecular marker predicts a selective ferroptosis "
            "response, rather than assuming all pancreatic tumors share the "
            "same vulnerability."
        ),
        duration_seconds=2047.0,
        elo_ceiling=1392,
        elo_step=16,
        evolution_count=9,
        second_pass_count=3,
        evidence=(
            DemoEvidence(
                title="CPEB1 Controls NRF2 Proteostasis and Ferroptosis Susceptibility in Pancreatic Cancer",
                authors=("Liu et al.",),
                year=2024,
                url="https://pubmed.ncbi.nlm.nih.gov/38904009/",
                abstract=(
                    "A pancreatic cancer study connected CPEB1 loss to p62/KEAP1/NRF2 "
                    "signaling and reduced ferroptosis susceptibility."
                ),
            ),
            DemoEvidence(
                title="ARID3A enhances chemoresistance of pancreatic cancer via inhibiting PTEN-induced ferroptosis",
                authors=("Mao et al.",),
                year=2024,
                url="https://pubmed.ncbi.nlm.nih.gov/38781729/",
                abstract=(
                    "A preclinical study linked ARID3A, PTEN, GPX4, ferroptosis, "
                    "and gemcitabine response in pancreatic cancer models."
                ),
            ),
        ),
        hypotheses=(
            DemoHypothesis(
                title="CPEB1-low tumors depend on NRF2 redox buffering",
                statement=(
                    "CPEB1-low pancreatic cancer models may have a measurable "
                    "NRF2-buffering state that predicts reduced response to a "
                    "ferroptosis-inducing combination."
                ),
                mechanism=(
                    "CPEB1 loss is proposed to stabilize an anti-ferroptotic "
                    "program through the p62/KEAP1/NRF2 axis."
                ),
                expected_effect=(
                    "CPEB1-low models would show lower lipid-peroxidation response "
                    "unless the buffering program is jointly perturbed."
                ),
                experiment=(
                    "Stratify PDAC cell lines and organoids by CPEB1 status; test "
                    "a matrix of gemcitabine and ferroptosis-pathway perturbations "
                    "with rescue by lipid antioxidant."
                ),
                review=(
                    "Best-ranked because it has a clear biomarker and a rescue; "
                    "confirm that observed killing is ferroptotic, not generic stress."
                ),
                elo=1384,
                evidence_index=0,
            ),
            DemoHypothesis(
                title="ARID3A-PTEN-GPX4 status selects a chemosensitization subgroup",
                statement=(
                    "An ARID3A-high, PTEN-suppressed subgroup may be selectively "
                    "sensitized when ferroptosis resistance is relieved during "
                    "gemcitabine exposure."
                ),
                mechanism=(
                    "The proposal tests a transcriptional route from ARID3A to "
                    "PTEN and GPX4-linked lipid-peroxide control."
                ),
                expected_effect=(
                    "Combination benefit would be larger in the biomarker-defined "
                    "subgroup than in an unselected panel."
                ),
                experiment=(
                    "Use isogenic ARID3A perturbation and PTEN rescue across "
                    "gemcitabine-sensitive and -resistant PDAC models."
                ),
                review=(
                    "Compelling translational stratification, but test dose ordering "
                    "and normal-cell toxicity before interpreting synergy."
                ),
                elo=1336,
                evidence_index=1,
            ),
            DemoHypothesis(
                title="Early lipid-peroxidation kinetics predict durable combination response",
                statement=(
                    "Early lipid-peroxidation kinetics may distinguish transient "
                    "stress from a durable ferroptosis-linked chemosensitization "
                    "response."
                ),
                mechanism=(
                    "A kinetic biomarker is proposed to connect proximal redox "
                    "effects to longer-term loss of clonogenic survival."
                ),
                expected_effect=(
                    "Models with a sustained early lipid-peroxidation signal would "
                    "show the largest later clonogenic deficit."
                ),
                experiment=(
                    "Collect 2-, 8-, 24-, and 72-hour redox and viability readouts, "
                    "then validate the predictor in an independent organoid set."
                ),
                review=(
                    "A useful de-risking assay that complements the mechanistic "
                    "proposals, though it is not itself a therapeutic target."
                ),
                elo=1289,
                evidence_index=0,
            ),
        ),
    ),
}


@dataclass(frozen=True)
class DemoProposal:
    """One additional generation-wave proposal for a curated demo."""

    title: str
    premise: str
    experiment: str
    limitation: str
    evidence_index: int


# These are source records selected for browseability in the demo, not a
# systematic review. Their PubMed pages remain the durable primary links.
_SCENARIO_KEYS = tuple(DEMO_SCENARIOS)

_EXTRA_EVIDENCE: dict[str, tuple[DemoEvidence, ...]] = {
    _SCENARIO_KEYS[0]: (
        DemoEvidence(
            title="Small-Molecule-Induced Activation of Cellular Respiration Inhibits Biofilm Formation and Triggers Metabolic Remodeling in Staphylococcus aureus",
            authors=("Kim et al.",),
            year=2022,
            url="https://pubmed.ncbi.nlm.nih.gov/35852317/",
            abstract=(
                "A small-molecule screen linked respiratory activation, metabolic "
                "remodeling, reduced biofilm formation, and increased aminoglycoside "
                "sensitivity in S. aureus."
            ),
        ),
        DemoEvidence(
            title="Structural and metabolic responses of Staphylococcus aureus biofilms to hyperosmotic and antibiotic stress",
            authors=("Bertaux et al.",),
            year=2018,
            url="https://pubmed.ncbi.nlm.nih.gov/29460278/",
            abstract=(
                "NMR and oxygen measurements showed that antibiotic-stressed "
                "biofilms can shift metabolism and develop anoxic regions."
            ),
        ),
        DemoEvidence(
            title="Tolerant Small-colony Variants Form Prior to Resistance Within a Staphylococcus aureus Biofilm Based on Antibiotic Selective Pressure",
            authors=("Urish et al.",),
            year=2021,
            url="https://pubmed.ncbi.nlm.nih.gov/33835090/",
            abstract=(
                "An implant-model study distinguished phenotypic tolerance, "
                "small-colony variants, and acquired resistance under antibiotic "
                "selective pressure."
            ),
        ),
        DemoEvidence(
            title="Isothermal Microcalorimetry Detects the Presence of Persister Cells in a Staphylococcus aureus Biofilm After Vancomycin Treatment",
            authors=("Bachmann et al.",),
            year=2019,
            url="https://pubmed.ncbi.nlm.nih.gov/30858842/",
            abstract=(
                "Microcalorimetry detected metabolically inactive persister cells "
                "after vancomycin exposure and described their return to growth."
            ),
        ),
    ),
    _SCENARIO_KEYS[1]: (
        DemoEvidence(
            title="Differential expression of cytoskeletal regulatory factors in the adolescent prefrontal cortex: Implications for cortical development",
            authors=("Koss et al.",),
            year=2017,
            url="https://pubmed.ncbi.nlm.nih.gov/27735056/",
            abstract=(
                "Mouse work describes subregion-specific adolescent spine refinement "
                "and changes in cytoskeletal regulatory factors."
            ),
        ),
        DemoEvidence(
            title="Synapse-specific roles for microglia in development: New horizons in the prefrontal cortex",
            authors=("Blagburn-Blanco et al.",),
            year=2022,
            url="https://pubmed.ncbi.nlm.nih.gov/36003220/",
            abstract=(
                "A review frames microglial control of mPFC circuit maturation as "
                "synapse-, age-, and context-specific rather than uniform pruning."
            ),
        ),
        DemoEvidence(
            title="Development of Hippocampal-Prefrontal Cortex Interactions through Adolescence",
            authors=("Tymofiyeva et al.",),
            year=2020,
            url="https://pubmed.ncbi.nlm.nih.gov/31670797/",
            abstract=(
                "A longitudinal human imaging study associated adolescent maturation "
                "of hippocampal-prefrontal connectivity with executive performance."
            ),
        ),
        DemoEvidence(
            title="Linking mPFC circuit maturation to the developmental regulation of emotional memory and cognitive flexibility",
            authors=("Klune et al.",),
            year=2021,
            url="https://pubmed.ncbi.nlm.nih.gov/33949949/",
            abstract=(
                "A developmental review connects changes in mPFC circuitry, synapses, "
                "inhibition, and flexible behavior while emphasizing unresolved causal links."
            ),
        ),
    ),
    _SCENARIO_KEYS[2]: (
        DemoEvidence(
            title="Nrf2-mediated adenylosuccinate lyase promotes resistance to gemcitabine in pancreatic ductal adenocarcinoma cells through ferroptosis escape",
            authors=("Hsu et al.",),
            year=2024,
            url="https://pubmed.ncbi.nlm.nih.gov/39164986/",
            abstract=(
                "PDAC cell-line work linked NRF2-regulated ADSL, ferroptosis escape, "
                "and acquired gemcitabine resistance."
            ),
        ),
        DemoEvidence(
            title="CUL2 confers ferroptosis resistance in pancreatic cancer by disrupting KEAP1-mediated NRF2 degradation",
            authors=("Wang et al.",),
            year=2025,
            url="https://pubmed.ncbi.nlm.nih.gov/41402811/",
            abstract=(
                "A preclinical study reports that CUL2 can alter KEAP1-NRF2 handling, "
                "reduce ferroptosis susceptibility, and attenuate gemcitabine response."
            ),
        ),
        DemoEvidence(
            title="CASC9 potentiates gemcitabine resistance in pancreatic cancer by reciprocally activating NRF2 and the NF-κB signaling pathway",
            authors=("Zhang et al.",),
            year=2023,
            url="https://pubmed.ncbi.nlm.nih.gov/35913601/",
            abstract=(
                "CASC9 suppression increased oxidative stress and enhanced gemcitabine "
                "cytotoxicity in the reported pancreatic cancer models."
            ),
        ),
        DemoEvidence(
            title="Brusatol Enhances the Chemotherapy Efficacy of Gemcitabine in Pancreatic Cancer via the Nrf2 Signalling Pathway",
            authors=("Xi et al.",),
            year=2018,
            url="https://pubmed.ncbi.nlm.nih.gov/29849873/",
            abstract=(
                "A preclinical study tested suppression of NRF2 signaling alongside "
                "gemcitabine in pancreatic cancer cells and xenografts."
            ),
        ),
    ),
}


_PROPOSALS: dict[str, tuple[DemoProposal, ...]] = {
    _SCENARIO_KEYS[0]: (
        DemoProposal("Oxygen-gradient collapse reveals an antibiotic-sensitive sublayer", "In mature S. aureus biofilms, a spatially restricted oxygen deficit may create a low-energy survivor compartment; restoring oxygen availability immediately before antibiotic challenge should shrink that compartment without requiring biofilm dispersal.", "Use oxygen microsensors, redox imaging, and spatial CFU recovery in 48-hour clinical-isolate biofilms. Compare controlled oxygenation, sham handling, and matrix-disruption controls before a fixed vancomycin pulse; pre-specify a spatial kill-gradient as the primary endpoint.", "Oxygen manipulation can alter antibiotic chemistry and growth independently of a tolerant state, so the design needs matched planktonic and abiotic antibiotic-stability controls.", 3),
        DemoProposal("MazEF–ica epistasis partitions biomass from tolerance", "MazEF-dependent tolerance may be separable from ica-dependent biomass accumulation: a genetic epistasis experiment could identify whether the same regulatory branch controls both features or whether matrix production merely masks a distinct survivor program.", "Construct complemented and double-perturbation strains in two genetic backgrounds, then quantify matrix composition, growth rate, antibiotic kill curves, and survivor regrowth. Require restoration by complementation before assigning a causal branch.", "Strain-specific regulatory wiring could make a clean result non-generalizable; replication across clinical isolates is essential before treating the branch as conserved.", 0),
        DemoProposal("Persister exit kinetics nominate a sequential killing window", "A survivor subpopulation that is metabolically silent during vancomycin exposure may become transiently vulnerable while returning to growth; the duration of that exit window could determine whether a sequential rather than simultaneous combination is informative.", "After a vancomycin pulse, sample biofilms every two hours for microcalorimetry, ATP, membrane potential, and viable counts; apply a second agent at prespecified intervals and use kill-curve area rather than one endpoint.", "A second agent can appear selective simply because the first agent changed total biomass, so pair all schedules with equal-exposure and order-reversed controls.", 5),
        DemoProposal("Small-colony variants are a reversible lineage state, not an endpoint", "Antibiotic-exposed small-colony variants may be the observable output of a reversible metabolic lineage state that precedes stable resistance, allowing lineage tracking to distinguish transient tolerance from genetic escape.", "Barcode a clinical isolate, grow implant-surface biofilms, and follow colony morphology, whole-genome sequence, respiration, and antibiotic response through exposure and drug-free recovery. Define reversibility before assigning a resistance mechanism.", "Barcoding can itself perturb fitness and morphology; unbarcoded replicate populations and reciprocal re-isolation are needed to validate the lineage interpretation.", 4),
        DemoProposal("Respiratory stimulation has a narrow therapeutic index in established biofilms", "A metabolic stimulus that suppresses early biofilm formation may behave differently in established biofilms; a narrow dose-and-timing window may increase antibiotic susceptibility before it increases biomass or dispersal.", "Perform a factorial dose-by-timing experiment in 24-, 48-, and 72-hour biofilms with respiration, biomass, dispersal, and antibiotic kill as co-primary readouts. Use a blinded decision rule to identify a window worth mechanistic follow-up.", "A favourable in-vitro window may depend on nutrient-rich media, so the result must be repeated in host-mimicking medium before it is interpreted as broadly relevant.", 2),
        DemoProposal("Matrix permeability and cell state make independent contributions to tolerance", "The same antibiotic failure may arise from poor penetration or from a metabolically protected cell state; measuring both within intact biofilms can test whether permeability predicts killing after accounting for local physiology.", "Combine fluorescent antibiotic analog measurements with oxygen mapping, ATP reporters, and local viability imaging across intact biofilms. Fit a preregistered model comparing permeability-only, physiology-only, and combined explanations.", "Fluorescent analogs need not preserve native drug transport, so the key permeability conclusion requires orthogonal confirmation with quantitative mass spectrometry.", 1),
    ),
    _SCENARIO_KEYS[1]: (
        DemoProposal("Dopamine-gated microglial surveillance selects a plastic synapse subset", "Reward-linked dopaminergic input during adolescence may change microglial surveillance of a subset of frontal synapses, thereby coupling salient experience to later circuit flexibility rather than globally increasing pruning.", "In adolescent mice, pair longitudinal two-photon imaging of microglia and labeled frontal boutons with a rule-learning manipulation; perturb D1/D2 or P2RY12 signaling only during the imaging window and measure later set shifting.", "Dopamine manipulations can change behavior directly, so microglial-contact and bouton outcomes must be analyzed independently of task performance.", 5),
        DemoProposal("Complement tagging encodes synapse history rather than bulk elimination", "Complement-associated tagging may mark synapses with a particular recent activity history for refinement, making activity-tagged synapse identity a better predictor of engulfment than total spine density.", "Combine activity-dependent labeling, complement staining, and microglial engulfment quantification across early, mid, and late adolescence; add cell-type-specific complement perturbation and rescue arms.", "Colocalization alone cannot identify a causal tag, so the study needs a manipulation that changes tagging while preserving the underlying activity pattern.", 0),
        DemoProposal("Inhibitory maturation sets the behavioral consequence of pruning", "The effect of adolescent excitatory-synapse refinement on flexibility may depend on concurrent maturation of local inhibition; altering pruning without measuring excitation-inhibition balance could conflate two linked developmental processes.", "Measure interneuron recruitment, pyramidal-cell activity, spine dynamics, and rule-shift behavior in the same animals. Test a temporally restricted perturbation with electrophysiological rescue as the falsification criterion.", "Longitudinal multimodal measurement is technically demanding and may bias the sample; use a staged design with a replication cohort reserved for behavior.", 1),
        DemoProposal("Hippocampal–prefrontal coupling mediates a delayed flexibility phenotype", "Adolescent local prefrontal refinement may influence cognitive flexibility indirectly by stabilizing hippocampal-prefrontal coordination, producing a neural intermediate that predicts behavior better than spine count alone.", "Record simultaneous hippocampal and prefrontal activity during reversal learning before and after an adolescent refinement perturbation; test mediation with preregistered temporal-directionality analyses.", "Connectivity measures are correlational unless the timing of the perturbation is used to establish a causal sequence, so behavioral correlation is not sufficient evidence.", 4),
        DemoProposal("A sex- and age-resolved critical window explains heterogeneous outcomes", "The apparent inconsistency of pruning interventions may reflect a narrow age window whose timing differs by sex and prefrontal subregion, rather than a single adolescent mechanism.", "Use a balanced factorial cohort across sex, age window, and mPFC/OFC target; quantify microglial engulfment, spine maturation, and reversal learning with all interaction tests prespecified.", "The expanded design risks inadequate power for interactions, so it should begin with a pilot estimating variance and commit to a powered confirmatory cohort.", 2),
        DemoProposal("Experience changes the selectivity, not the amount, of adolescent refinement", "Cognitive training during adolescence may bias which synapses are stabilized or removed without changing total pruning, offering an explanation for why bulk spine measures can miss behaviorally meaningful remodeling.", "Expose mice to structured rule-switch training or matched handling, then track activity-tagged synapses, microglial contacts, total spine density, and adult flexibility. Treat selective stabilization as the primary outcome.", "Training can alter stress and arousal, so yoked reward, locomotion, and corticosterone controls are needed before attributing the result to experience-dependent refinement.", 3),
    ),
    _SCENARIO_KEYS[2]: (
        DemoProposal("CUL2 status defines an NRF2-stabilized ferroptosis-resistant state", "CUL2-high PDAC models may maintain NRF2 signalling by competing for KEAP1, creating a biomarker-defined ferroptosis-resistant state that can be separated from generic gemcitabine resistance.", "Stratify cell lines and organoids by CUL2 expression, quantify KEAP1-NRF2 engagement, lipid peroxidation, GPX4, and gemcitabine response, then test CUL2 knockdown with rescue by stabilized NRF2.", "CUL2 has broad cellular functions, so a rescue that isolates the NRF2 branch is necessary before any ferroptosis-specific interpretation.", 3),
        DemoProposal("USP8 creates a pharmacodynamic delay in NRF2 turnover", "USP8-mediated stabilization of NRF2 may determine how long antioxidant defenses persist after gemcitabine exposure, making turnover kinetics a more useful combination biomarker than a static baseline expression measurement.", "Perform pulse-chase NRF2 measurements after gemcitabine in parental and resistant PDAC models with USP8 perturbation; couple them to live lipid-peroxidation imaging and clonogenic survival.", "Proteostasis effects can be pleiotropic, so the experiment requires catalytic-dead USP8 and NRF2-rescue controls rather than inhibitor-only evidence.", 1),
        DemoProposal("TSPAN15–ITGB1 signaling couples adhesion to GPX4-dependent survival", "TSPAN15 may sustain an integrin-linked FAK/AKT/mTOR program that raises GPX4 and protects a matrix-adherent PDAC subpopulation from gemcitabine-associated ferroptosis.", "Compare two-dimensional, matrix-rich organoid, and co-culture conditions after TSPAN15 knockdown; measure ITGB1 stability, kinase signaling, GPX4, lipid peroxidation, and death-pathway rescue.", "An adhesion-dependent phenotype may be model-specific, so the same rank order must be observed in at least one patient-derived organoid system.", 1),
        DemoProposal("ADSL loss reroutes purine stress into ferroptosis escape", "Reduced ADSL may create a metabolic state in which purine-pathway stress and antioxidant signalling jointly lower ferroptosis sensitivity, offering a mechanistically distinct route to gemcitabine resistance.", "Use isogenic ADSL perturbation in parental and resistant models, quantify purine intermediates, CARMA3, NRF2 activity, lipid peroxidation, and drug response, then restore ADSL as a rescue.", "Metabolic intermediates are highly context-dependent, so flux measurements rather than steady-state metabolite abundance are needed for a causal claim.", 2),
        DemoProposal("CASC9 marks an inflammatory-redox feedback state with actionable heterogeneity", "A CASC9–NRF2–NF-κB feedback state may identify PDAC models in which oxidative-stress modulation enhances gemcitabine response without assuming that all tumors share the same redox dependency.", "Profile CASC9, NRF2 targets, NF-κB activity, and drug response across organoids; perturb CASC9 and use ferroptosis, apoptosis, and necroptosis rescue panels to define the death mechanism.", "The observed benefit could reflect non-ferroptotic cell death, so the proposal is only supported if orthogonal ferroptosis readouts and rescue experiments converge.", 4),
        DemoProposal("Early redox trajectories predict durable response better than endpoint viability", "The time-resolved trajectory of lipid peroxidation, glutathione depletion, and mitochondrial morphology may distinguish a reversible stress response from a ferroptosis-linked combination response before clonogenic outcomes are known.", "Collect 2-, 8-, 24-, and 72-hour multimodal redox measurements in a training panel, build a locked predictor, and validate it prospectively in independent patient-derived organoids.", "A predictive signature can overfit a small panel, so model development and validation must be separated and the final predictor reported with uncertainty.", 0),
    ),
}


def scenario_evidence(scenario: DemoScenario) -> tuple[DemoEvidence, ...]:
    """Return the curated six-source evidence bundle for one demo scenario."""
    return scenario.evidence + _EXTRA_EVIDENCE[scenario_key(scenario)]


def scenario_key(scenario: DemoScenario) -> str:
    """Resolve a scenario's stable key from its object identity."""
    for key, candidate in DEMO_SCENARIOS.items():
        if candidate is scenario:
            return key
    raise ValueError("Unknown curated demo scenario")


def _proposal_hypothesis(proposal: DemoProposal) -> DemoHypothesis:
    """Expand a concise generation seed into the full hypothesis record."""
    return DemoHypothesis(
        title=proposal.title,
        statement=proposal.premise,
        mechanism=(
            f"{proposal.premise} The experiment is designed to distinguish the "
            "nominated mediator from correlated changes in the surrounding model "
            "system rather than treating an association as causal evidence."
        ),
        expected_effect=(
            "If the mechanism is correct, the pre-specified perturbation will "
            "shift the primary readout and that shift will be reversed by the "
            "named rescue or orthogonal control."
        ),
        experiment=proposal.experiment,
        review=proposal.limitation,
        elo=1200,
        evidence_index=proposal.evidence_index,
    )


def _evolved_hypothesis(source: DemoHypothesis) -> DemoHypothesis:
    """Create a distinct second-generation version with stronger falsification."""
    return DemoHypothesis(
        title=f"Refined: {source.title}",
        statement=(
            f"{source.statement} This evolved version adds a preregistered "
            "stratification rule, an orthogonal readout, and a rescue criterion "
            "so that a negative result can distinguish a failed mechanism from "
            "an uninformative assay."
        ),
        mechanism=(
            f"{source.mechanism} The refinement explicitly tests whether the "
            "candidate mediator is necessary and sufficient, rather than relying "
            "on a single association or endpoint."
        ),
        expected_effect=(
            f"{source.expected_effect} Concordance across the primary assay, "
            "orthogonal assay, and rescue arm is required before advancing it."
        ),
        experiment=(
            f"{source.experiment} Repeat the highest-value condition in an "
            "independent model set and prospectively define the effect size that "
            "would justify a follow-up study."
        ),
        review=(
            f"{source.review} The evolved version reduces this risk, but the "
            "claim remains exploratory until the independent replication agrees."
        ),
        elo=1200,
        evidence_index=source.evidence_index,
    )


def _second_pass_hypothesis(source: DemoHypothesis) -> DemoHypothesis:
    """Create a validation-focused iteration for only the strongest ideas."""
    source_title = source.title.removeprefix("Refined: ")
    return DemoHypothesis(
        title=f"Validation-ready: {source_title}",
        statement=(
            f"{source.statement} This second-pass variant narrows the claim to "
            "a prespecified population or state and advances only if the effect "
            "replicates under blinded analysis in an independent model set."
        ),
        mechanism=(
            f"{source.mechanism} The additional pass prioritizes a decisive "
            "necessity-and-rescue test over another broad exploratory screen."
        ),
        expected_effect=(
            f"{source.expected_effect} The result is considered actionable only "
            "when the predeclared replication and rescue thresholds are met."
        ),
        experiment=(
            f"{source.experiment} Lock the analysis plan, randomize the "
            "validation cohort, and report the result alongside the original "
            "discovery cohort rather than pooling them."
        ),
        review=(
            f"{source.review} This pass deliberately trades breadth for a more "
            "credible validation decision."
        ),
        elo=1200,
        evidence_index=source.evidence_index,
    )


def scenario_hypotheses(scenario: DemoScenario) -> tuple[DemoHypothesis, ...]:
    """Return a scenario-specific multi-generation hypothesis set."""
    first_wave = scenario.hypotheses + tuple(
        _proposal_hypothesis(item)
        for item in _PROPOSALS[scenario_key(scenario)]
    )
    evolved = tuple(
        _evolved_hypothesis(item)
        for item in first_wave[: scenario.evolution_count]
    )
    second_pass = tuple(
        _second_pass_hypothesis(item)
        for item in evolved[: scenario.second_pass_count]
    )
    return first_wave + evolved + second_pass
