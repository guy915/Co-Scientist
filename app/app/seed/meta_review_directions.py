"""Curated ``main_research_directions`` for the three demo scenarios.

R14-27: the published ranking report's own "Main Research Directions"
section -- two flowing prose paragraphs weaving a run's directions
together (bolded direction names inline, why each matters, closing on a
cross-direction observation), distinct from the itemized per-direction
array ``seed/overview.py`` already renders on the Research Overview
document. A real run's meta-review call produces this narrative; a
curated demo has no such call, so this module hand-authors the same shape
-- grounded in each scenario's own top-3 hypotheses
(``demo_seed_data_scenarios.py``), mechanistic prose only, no invented
citations, PMIDs, or attributed findings.

Split out of ``seed.overview`` so that module stays within the line-count
cap; keyed by ``scenario_key`` exactly as the other curated content
modules (``seed.overview_directions``, ``seed.config_synthesis``,
``seed.evidence``) are.
"""

from __future__ import annotations

from app.demo_seed_data import _SCENARIO_KEYS

# Each entry weaves together that scenario's own top-3 hypotheses
# (demo_seed_data_scenarios.py, in Elo-descending order -- the same
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
