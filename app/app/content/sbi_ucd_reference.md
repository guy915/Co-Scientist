<!-- Extended technical reference, loaded ONLY by chat Q&A (one call per
question), never by the run pipeline. Distilled from the group's internal
overview: the methods, notation, and findings a question is likely to turn
on. Deliberately omits people, funding, and institutional history, which do
not help answer research questions. -->

# Kholodenko/Rukhlenko group: extended technical reference

## cSTAR (cell State Transition Assessment and Regulation)

Published in Nature (2022, Rukhlenko et al.); extended to breast cancer in
Cancers (2024), tuberculosis in Science Advances (2023), and vascular
remodelling in Science Advances (2025). It maps cell states, models
transitions between them, and predicts interventions that convert cell fate,
by combining SVM classification with mechanistic ODE modelling in a
Waddington-landscape framework.

**State Transition Vector (STV).** A unit-length vector giving each
molecule's contribution to the difference between two cell states. It is the
normal vector to the maximum-margin hyperplane found by a linear-kernel SVM
separating the states in molecular feature space, and points along the
centroid-to-centroid direction. The absolute values of its components rank
proteins by importance in switching state; the top-ranked components form the
**core signalling network**. This is dimensionality reduction by causal
relevance rather than by variance, which is what distinguishes it from PCA.

**Dynamic Phenotype Descriptor (DPD).** The signed distance from a data point
to the separating hyperplane, computed as the projection of the state onto
the STV. Its sign says which basin the cell is in, its magnitude how far from
the boundary, and a zero crossing marks the tipping point where quantitative
signalling changes become a qualitative state change. The DPD collapses the
whole network state into one monitorable variable, analogous to a reaction
coordinate.

**Landscape dynamics.** A potential U(S) has minima at the stable states S0
and S1. The DPD evolves as dS/dt = f(S) + sigma(t), where f(S) = -dU/dS is
the restoring force pulling the cell back to its attractor (fitted
piece-wise-linear with slopes alpha_0, alpha_1) and sigma(t) is the signalling
force from core kinase activity, weighted by BMRA-inferred connection
coefficients. Interventions work when they generate enough signalling force to
overcome the restoring force and cross the hyperplane.

**Workflow.** Preprocess omics data; train the SVM and extract STV(s); rank
analytes and choose core modules by STV magnitude, available perturbations,
and prior knowledge; compute DPD; reconstruct the network with BMRA; build
nonlinear ODE models in PySB; fit by differential evolution; simulate drug
responses and predict synergies. Validation reported 96% precision at 8-fold
cross-validation, robust to 50% added noise.

**Digital twin.** A calibrated model of a specific cell line or phenotype,
encoding both the quantitative network and the mapping to phenotype space. It
predicts how untested inhibitor combinations move the cell in state space,
supporting **phenotypic reversion** -- reprogramming a cancer cell toward a
normal-like state rather than killing it.

## Modular Response Analysis

Introduced in Kholodenko et al., PNAS 2002 ("Untangling the wires"). It
solves the problem that in an interconnected network, a perturbation to one
node propagates everywhere, so an observed change in node i may be caused by
j directly or via some intermediate k.

**Local response coefficients** r_ij are the direct influence of module j on
module i in logarithmic terms, with all other modules held constant: positive
means activation, negative inhibition, zero no direct link, and the magnitude
gives interaction strength. By convention r_ii = -1. They relate to the
Jacobian by r_ij = -(J_ij / J_ii)(x_j / x_i) at steady state.

**Global response coefficients** R_ik are the total system-wide change when
parameter k is perturbed, estimated experimentally from the relative change
between perturbed and baseline measurements.

**Core result.** With r * R = P, the solution r = P * R^-1 recovers network
topology and interaction strengths from steady-state perturbation data
without knowing the kinetic rate laws. Equivalently r = I - (R + I)^-1.

**Design requirements.** Classically N perturbations for N modules, each
specific to one module, with the system returning to steady state and all
module activities measurable. Larger perturbations are preferred (less noise
sensitivity despite added bias), a single control suffices, and at least three
replicates are recommended.

**BMRA** adds Bayesian variable selection: it accepts prior topology from
sources like KEGG or STRING, tolerates fewer perturbations than modules,
handles noise probabilistically, and returns posterior confidence per edge.
It recovers topology nearly perfectly even when half the priors are wrong.

**Limits.** MRA assumes steady state, linearity, perturbation specificity,
and module insulation. It can fail under sustained oscillations, bistability
with bifurcation crossing, shared components between modules, very high
noise, or incomplete perturbation coverage.

## Signalling biology the group works in

**MAPK/ERK.** Growth factor to RTK to RAS to RAF (ARAF/BRAF/CRAF) to MEK1/2
to ERK1/2. BRAF is the most potent isoform; CRAF is the most common route to
resistance. Negative feedbacks run ERK to RAF, ERK to SOS, ERK to MEK, and
ERK to DUSP phosphatases. The cascade behaves as a negative feedback
amplifier, converting switch-like into graded responses and conferring
robustness. Transient ERK activation promotes proliferation; sustained
activation promotes differentiation.

**PI3K/AKT/mTOR.** PI3K makes PIP3; PDK1 and mTORC2 phosphorylate AKT at T308
and S473; AKT inhibits TSC2 and thereby activates mTORC1, which drives S6K
and 4EBP1. PTEN, PP2A, PHLPP and TSC1/2 oppose it, and S6K phosphorylates
IRS1 as negative feedback. Crosstalk with MAPK is extensive: RAS activates
PI3K directly, AKT can inhibit RAF, and mTOR inhibition upregulates MEK/ERK.

**STAT3.** Phosphorylated at Y705 by JAK, RTKs, or Src, then dimerizes and
translocates. Drives BCL-XL, survivin, MCL1, CCND1, MYC, and VEGF.

**Notation.** ppERK is doubly phosphorylated (T202/Y204) and fully active;
pAKT is specified by site, S473 or T308; pS6 reads out mTORC1.

## Drug resistance

**Paradoxical activation.** Type I and I-and-a-half RAF inhibitors promote
RAF dimerization in RAS-active cells; the drug binds one protomer and
transactivates the drug-free partner, activating ERK in BRAF wild-type cells.
Countermeasures include paradox breakers (PLX8394, PLX7904), type II pan-RAF
inhibitors, dimerization blockers, and MEK-inhibitor combinations.

**Adaptive resistance** works by feedback relief: mTOR inhibition activates
MEK/ERK, MEK inhibition activates PI3K/AKT, and single-pathway inhibition
provokes compensatory kinome reprogramming. Acquired mechanisms include RAF
amplification or truncation, p61BRAF(V600E) splice variants, RTK
upregulation, and new RAS mutations.

**Key result (Cell Reports 2021).** Feedback loops alone cannot fully
reactivate steady-state signalling. Complete reactivation needs either a
network topology with two routes from the inhibited protein to the output, or
drug-induced kinase dimerization.

## Published applications

**Neuroblastoma (Nature 2022).** cSTAR on RPPA data from SH-SY5Y stimulated
with NGF (TrkA) or BDNF (TrkB). The STV identified JNK, ERK, AKT, and S6 as
the discriminators between differentiation and proliferation. The model
predicted that trametinib (MEK inhibitor) plus gefitinib (EGFR inhibitor)
converts the aggressive TrkB state toward a benign TrkA-like state, validated
at a synergy score of 51% +/- 7%.

**Breast cancer (Cancers 2024).** CyTOF across 62 cell lines under five
kinase inhibitors. Luminal lines share a core architecture with mTOR as the
main oncogenic driver and STAT3 maintaining the subtype; basal lines are
heterogeneous, splitting into mTOR-driven, MEK/ERK-driven, STAT3-driven, and
PKC-driven subclasses.

**Tuberculosis (Science Advances 2023).** cSTAR on macrophage RNA-seq
separating susceptible from resistant states, identifying lipid peroxidation
and type I interferon signalling as drivers of susceptibility and predicting
interventions that restore control of M. tuberculosis.

**RAS-mutant AML and pancreatic cancer.** Structure-based dynamic RAS pathway
models predicting conformation-specific RAF inhibitor combinations that
synergistically suppress ERK, validated in cell lines and patient samples.

## Computational stack

**PySB** builds rule-based models as Python programs, handling combinatorial
complexity such as multi-site phosphorylation, and compiles to BioNetGen.
**BioMASS** (Imoto) covers simulation, differential-evolution parameter
estimation, sensitivity analysis by Morris and Sobol methods, and Text2Model
for building models from natural language. **Pasmopy** personalises models to
a patient by preserving topology and rate constants from a reference model
while scaling initial protein concentrations by the patient's RNA-seq.

Synergy is quantified by Loewe additivity and isobole shape, Bliss
independence, or the combination index. Public data typically comes from
PRIDE, GEO, CCLE, TCGA, KEGG, STRING, Reactome, and OmniPath.

## Canonical papers

- Kholodenko et al., PNAS 2002 -- Untangling the wires (MRA).
- Santra et al., BMC Systems Biology 2013 -- Bayesian variable selection MRA.
- Rukhlenko et al., Cell Systems 2018 -- Dissecting RAF inhibitor resistance.
- Thomaseth et al., PLOS Comp Biol 2018 -- Noise and design in MRA.
- Kholodenko et al., Cell Reports 2021 -- Signalling reactivation and
  resistance.
- Rukhlenko et al., Nature 2022 -- Control of cell state transitions (cSTAR).
- Imoto et al., iScience 2022 -- Text-based patient-specific modelling.
- Rukhlenko et al., Science Advances 2023 -- cSTAR for tuberculosis.
- Rukhlenko et al., Cancers 2024 -- Breast cancer cell state models.
- Rukhlenko et al., Science Advances 2025 -- cSTAR vascular remodelling.
