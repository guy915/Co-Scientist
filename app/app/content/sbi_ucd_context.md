<!-- Compact group profile. This text is injected into EVERY audience-tagged
LLM call: run planning, generation, reflection, each tournament comparison,
evolution, and meta-review. Tournament ranking is roughly quadratic in the
hypothesis count, so a run makes far more calls than it does hypotheses --
keep this file dense and under roughly 800 tokens. Depth belongs in
sbi_ucd_reference.md, which only chat Q&A loads. -->

# Research context: Kholodenko/Rukhlenko group, Systems Biology Ireland

The user works in the computational systems biology group co-led by Prof.
Boris Kholodenko and Dr. Oleksii Rukhlenko at Systems Biology Ireland (SBI),
University College Dublin. The group reconstructs the causal topology of
signalling networks from perturbation data and models cell-state transitions
mechanistically, running a tight loop between wet-lab measurement and
computational modelling.

## Methods the group owns

- **Modular Response Analysis (MRA)** and **Bayesian MRA (BMRA)**: infer
  direct connection coefficients between network modules from steady-state
  perturbation data, separating direct causal links from indirect effects
  propagating through the network.
- **cSTAR** (cell State Transition Assessment and Regulation): an SVM-derived
  State Transition Vector (STV) ranks each molecule's contribution to a state
  change and defines the core signalling network; the Dynamic Phenotype
  Descriptor (DPD), the signed distance to the separating hyperplane, acts as
  a single order parameter for cell state on a Waddington landscape. Used to
  predict interventions that push a cell across a state boundary.
- **Mechanistic ODE modelling** of signalling networks, including
  structure-based kinase models (RAF dimerization, paradoxical activation,
  conformation-specific inhibitor combinations) and drug-synergy prediction.

## Data the group can generate

CyTOF phospho-profiling at single-cell resolution (30-40 markers), RPPA,
mass-spectrometry phosphoproteomics, scRNA-seq, growth-factor time courses
(early responses 7-17 min, late/feedback 40-60 min), and perturbation panels
built from kinase inhibitors, knockdowns, and CRISPR knockouts.

## Systems in use

Breast cancer (MCF7, MDA-MB-231, T47D, BT-474, SKBR3, MDA-MB-468),
neuroblastoma (SH-SY5Y, TrkA/TrkB, MYCN), melanoma (A375 BRAF V600E,
MEL-JUSO), RAS-mutant AML, pancreatic and colorectal cancer, and macrophage
polarisation in tuberculosis. Pathways of interest: MAPK/ERK, PI3K/AKT/mTOR,
STAT3, PKC, and receptor tyrosine kinases (EGFR/ERBB, Trk).

## Tooling

Python (NumPy, SciPy, scikit-learn), PySB and BioNetGen for rule-based
models, BioMASS and Pasmopy (both developed in this group), differential
evolution for parameter fitting, UCD HPC.

## What makes a hypothesis useful to this group

Favour mechanistic, quantitative hypotheses that name specific network
modules and the sign and direction of the interactions between them, and that
can be tested by perturbing one module and reading the others out with the
assays above. Say which measurement would discriminate the hypothesis from
its alternatives. A hypothesis that could be written as an ODE model or as an
MRA perturbation design is more useful here than a descriptive association.
Feedback structure, network rewiring under drug treatment, and adaptive
resistance are recurring concerns.

Treat this as background about the user's field, not as a constraint that
overrides their stated research goal. If the goal falls outside these systems
or methods, follow the goal.
