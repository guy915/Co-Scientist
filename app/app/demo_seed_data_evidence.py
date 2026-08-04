"""Additional curated sources shown alongside each scenario's own evidence.

Content only: ``demo_seed_data.scenario_evidence`` appends these records to
the primary sources a scenario carries.
"""

# Curated publication titles and reader-facing prose are intentionally kept
# intact here; wrapping individual literals would make this data hard to audit.
# ruff: noqa: E501

from __future__ import annotations

from app.demo_seed_data_scenarios import _SCENARIO_KEYS
from app.demo_seed_data_types import DemoEvidence

# These are source records selected for browseability in the demo, not a
# systematic review. Their PubMed pages remain the durable primary links.
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
