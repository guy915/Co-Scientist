"""The three curated demo scenarios and their primary sources.

Content only: the record types live in ``demo_seed_data.types`` and the
functions that derive run artifacts from this content in ``demo_seed_data``.
"""

# Curated publication titles and reader-facing prose are intentionally kept
# intact here; wrapping individual literals would make this data hard to audit.
# ruff: noqa: E501

from __future__ import annotations

from app.demo_seed_data.types import (
    DemoEvidence,
    DemoHypothesis,
    DemoScenario,
)

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

_SCENARIO_KEYS = tuple(DEMO_SCENARIOS)
