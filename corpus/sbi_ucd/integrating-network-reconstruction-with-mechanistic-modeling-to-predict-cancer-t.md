# Integrating network reconstruction with mechanistic modeling to predict cancer therapies

Integrating network reconstruction with mechanistic
modeling to predict cancer therapies
2016 © The Authors,
some rights reserved;
of Science.
Melinda Halasz,1,2* Boris N. Kholodenko,1,2,3 Walter Kolch,1,2,3* Tapesh Santra1*
Signal transduction networks carry extracellular signals from the cell
membrane to the nucleus and internal signals from organelles or related to cell stress or metabolic status through finely controlled networks of protein interactions (1). Many diseases, such as cancer, are
consequences of harmful changes in these networks, caused by oncogenic mutations or aberrant expression of genes encoding the participant proteins (1). Understanding the functional consequences of
these alterations is key to effective treatment (1). Systems biologists
have developed an array of computational tools to gain understanding
into the network rewiring and functional consequences of such rewiring. Although mechanistic models of network are useful tools (2–9),
their construction requires comprehensive prior information about
the components and wiring structure (that is, the topology) of the
network being modeled (10, 11) and plenty of experimental data for
model calibration. Their application to the signaling networks in
cancer cells is challenging, because these networks are often rewired
with often unknown effects on the network (1).
An alternative strategy is to use experimental data and data-driven
modeling instead of prior knowledge (12–24). However, such reconstructed networks, although useful in visualizing static network topologies, have limited use in predicting functional properties, such as the
temporal and spatial dynamics of signaling networks, the consequences of sequential or pulsed drug treatments (22), the phenotypic
differences after treatments with different drugs that target the same
molecules using different mechanisms (22), and the acquired resistance after treatment. Most of these functional properties and perturbation outcomes can be predicted using mechanistic models.
However, building mechanistic models based on reconstructed networks is not trivial, because the existing network reconstruction
methods have limitations. For instance, some algorithms cannot detect
feedback loops (15, 16), some cannot determine the direction of protein interactions (23), and some can only indicate the presence and
absence of interactions (15–18) but cannot quantify the influence of
one protein on another (19–22). Noise in measurements and sub-
optimal experimental designs affect the reliability and accuracy of
the reconstructed networks (25).
Here, we present a two-stage computational platform that enables
the construction of mechanistic models based on reconstructed
models of signal transduction networks. The first stage consists of
a network reconstruction algorithm that can reconstruct cell- and
tissue-specific models of networks by combining prior knowledge
of generic signal transduction network topologies with cell- and
tissue-specific experimental data. The reconstructed models reveal
the cell- and tissue-specific topology of the network and quantify
the strengths of its interactions. In the second stage, an ordinary differential equation (ODE)–based mechanistic model, encompassing
all previously known and newly inferred interactions of the network,
is developed. The parameters of this model are then calibrated to
ensure that the interaction strengths between different components
of the mechanistic model closely resemble those inferred by the network reconstruction algorithm. The calibrated ODE model is then
used to predict the effects of therapeutic intervention that targets
the networks in different cells or tissues.
We tested our method on a publicly available data set (22) that
contains quantitative measurements of different components of the
epidermal growth factor receptor (EGFR) and insulin-like growth
factor 1 receptor (IGF1R) signaling networks in a panel of colorectal
cancer (CRC) cells. The first stage of network reconstruction uncovered differences in the topologies of the EGF and IGF1 signaling
pathways of different CRC cell lines; some of these network differences
were associated with EGFR inhibitor resistance in subsets of CRC cells.
In the second stage, we constructed a mechanistic model of the EGF
and IGF1 signaling networks for the EGFR inhibitor–resistant CRC
cell line HCT116. The model correctly predicted the responses of
the EGFR and IGF1R networks to different individual and combinatorial perturbations, as well as predicted a mechanism to overcome
resistance to EGFR inhibition. We validated these predictions in
cultured CRC cells and in zebrafish xenograft models.
Computationally integrating network reconstruction
methods with mechanistic modeling of signaling networks
Our computational framework (Fig. 1A) consists of two stages: (i)
network reconstruction (Fig. 1B) using a Bayesian reformulation of
Systems Biology Ireland, University College Dublin, Belfield, Dublin 4, Ireland.
School of Medicine, University College Dublin, Belfield, Dublin 4, Ireland. 3Conway
Institute of Biomolecular and Biomedical Research, University College Dublin, Belfield,
Dublin 4, Ireland.
*Corresponding author. Email: walter.kolch@ucd.ie (W.K.); tapesh.santra@ucd.ie
(T.S.); melinda.halasz@ucd.ie (M.H.)
Signal transduction networks are often rewired in cancer cells. Identifying these alterations will enable more effective
cancer treatment. We developed a computational framework that can identify, reconstruct, and mechanistically
model these rewired networks from noisy and incomplete perturbation response data and then predict potential
targets for intervention. As a proof of principle, we analyzed a perturbation data set targeting epidermal growth
factor receptor (EGFR) and insulin-like growth factor 1 receptor (IGF1R) pathways in a panel of colorectal cancer cells.
Our computational approach predicted cell line–specific network rewiring. In particular, feedback inhibition of insulin
receptor substrate 1 (IRS1) by the kinase p70S6K was predicted to confer resistance to EGFR inhibition, suggesting
that disrupting this feedback may restore sensitivity to EGFR inhibitors in colorectal cancer cells. We experimentally
validated this prediction with colorectal cancer cell lines in culture and in a zebrafish (Danio rerio) xenograft model.
Posterior distribution of
Fig. 1. Schematic outline of the computational analysis pipeline and its components. (A) Workflow of the
integrated analysis platform. (B) Workflow of the BMRA algorithm, which reconstructs network models of signal
transduction networks from perturbation data sets. (C) Workflow of the BMM algorithm, which reconstructs ODE
models of signal transduction networks using reconstructed network models.
modular response analysis (BMRA) (19, 20)
and (ii) mechanistic model development
and calibration using a Bayesian mechanistic modeling (BMM) algorithm (Fig.
1C). BMRA combines prior literature
knowledge with quantitative noisy experimental data to generate and statistically
assess potential network models (topology and interaction strengths) of signaling networks (see note S1 and Materials
and Methods for details). We compared
the accuracy and robustness of BMRA
with several existing network reconstruction algorithms. We benchmarked its
performance using five data sets published by the DREAM (challenge 4) consortium (http://dreamchallenges.org/)
(see note S2 for details). When applied
without the inclusion of any “prior”
knowledge of the network topology,
BMRA ranked second, third, and fourth
(of 29) on each of the five data sets, and
with the inclusion of noisy prior knowledge, BMRA performed better than all
of the original 29 algorithms in the challenge (Table 1).
We also systematically evaluated the
sensitivity of BMRA to noise and the lack
of experimental perturbation data using
simulated data of the mitogen-activated
protein kinase (MAPK) pathway based
on a previously published mathematical
model (18) of the pathway. Using the
model, we simulated 2300 steady-state
perturbation response data sets, 100 replicate data sets in 23 categories, containing different levels of noise and data
incompleteness (see note S3 for details).
We compared the performance of BMRA
on these data sets with other methods
based on Lasso regression (26–29), linear matrix inequality (30–32), and MRA
by Klinger et al. (22), the latter of which
was originally used to analyze the same
experimental data set as we use here.
BMRA outperformed the other algorithms in most cases except at high levels
of noise, where all methods collapsed
(Fig. 2, A to C). These results indicate
BMRA’s higher accuracy and robustness
against noise, low numbers of replicates,
or sparseness of perturbations in experimental data.
The next step is to “feed” the BMRAreconstructed network topology model
into the BMM algorithm to develop predictive mechanistic network models (Fig.
1C and note S4). Any interactions that
were inferred from the BMRA and not
Table 1. Performances of BMRA and the top five performers of the
DREAM challenge.
0.985* 0.984* 0.992* 0.994* 0.9594* 0.930* 0.937* 0.968* 0.9569* 0.7738*
0.954 0.928 0.916 0.547 0.968 0.852
0.967 0.796 0.916 0.936† 0.822 0.881 0.543† 0.682 0.774† 0.673
0.934† 0.751† 0.869 0.922 0.776 0.740† 0.382 0.659 0.698
0.884 0.657 0.8675 0.902 0.7403 0.673 0.301 0.650
0.864 0.655 0.824 0.884 0.723 0.623 0.243 0.646 0.675
0.673 0.507 0.288 0.572 0.645
yet supported in the published literature should be validated experimentally, and then an ODE-based mathematical model can be developed for the final validated topological model. The mathematical
model formulates the rate of change in the concentration of each
pathway component by a parametric function dependent on its
own concentration and that of its regulators. The parameters of these
rate functions are then calibrated using a Bayesian parameter calibration algorithm.
Reconstructing EGFR and IGF1R networks in a panel of
We used the computational pipeline (see note S5 for details) to analyze a publicly available data set containing perturbation responses of
EGFR and IGF1R networks in six genetically diverse CRC cell lines:
HCT116, HT29, LIM1215, SW403, SW480, and RKO (22). This data
set comprises measurements of phosphorylation changes in eight key
signaling proteins [AKT Ser473, extracellular signal–regulated kinase 2
(ERK2) Thr185/Tyr187, MAPK kinase 1 (MEK1) Ser217/Ser221, p70S6K
Thr421/Ser424, IGF1R Tyr1131, glycogen synthase kinase 3 a/b (GSK3a/
b) Ser21/Ser9, IkBa Ser32/Ser36, and insulin receptor substrate 1 (IRS1)
Ser636/Ser639] in response to individual treatment by four inhibitor
drugs [targeting the kinases MEK, phosphatidylinositol 3-kinase
(PI3K), IkB kinase (IKK), or GSK3a/b] followed by stimulation with
transforming growth factor–a (TGFa; a ligand of EGFR) and IGF1.
Because the RKO cells showed very little response to the drugs, we
excluded them from our analysis.
Despite the size of the data set, it is still incomplete and insufficient
for most network reconstruction algorithms (12–17, 19–22). Because
of the technology used to acquire the data, the measurements have a
lot of noise (33). However, the data set probes the EGFR and IGFR
pathways, which are well described in the existing literature. Thus, this
data set provides a suitable test bed for our computational pipeline,
which is designed to integrate prior knowledge with noisy and insufficient data to reconstruct a predictive model of the network. The data
set enables the investigation of a pressing issue in cancer biology, that
is, the problem of EGFR inhibitor resistance in CRC. EGFR inhibition
is one of the mainstays in the therapy of metastatic CRC (34). Unfortunately, about 30 to 50% of CRC patients have a mutated KRAS
*Results of BMRA with prior knowledge.
prior knowledge.
gene that renders them resistant to EGFR-targeted therapies (35). In
addition, about half of the patients with wild-type KRAS will develop
resistance to EGFR inhibition (36). Several studies indicate that the
extensive cross-talk between EGFR and IGF1R might contribute to
the acquired resistance to EGFR inhibition (37). Therefore, developing
predictive models of these pathways in EGFR inhibitor–resistant CRC
cells (such as HCT116 and SW480) may provide valuable insight into
the resistance mechanisms of CRC.
First, we developed a literature-based generic signaling network
for EGFR and IGF1R pathways consisting of all known interactions
(note S6) between the measured proteins across a diverse range of
cell types. The generic network model represents our prior knowledge of EGFR and IGF1R pathways and was used to formulate the
prior distribution for the BMRA algorithm. With the prior distributions, we used BMRA to reconstruct separate models for networks
activated by TGFa or IGF1 in five CRC cell lines from the corresponding perturbation data sets. This resulted in 10 network models,
corresponding to the five CRC cell lines each stimulated by TGFa
(Fig. 3A) or IGF1 (Fig. 3B).
In the reconstructed networks, each interaction is annotated
with cell-specific symbol for the probability distribution of its
strength, which includes whether the interaction has a positive or
negative effect, and the probability of its existence (Fig. 3, A and B).
The reconstructed models predicted several differences in the signal
integration, interpathway links, and feedback mechanisms of the
EGFR and IGF1R pathways across the different CRC cell lines.
For instance, the networks indicated that ERK inhibits AKT phosphorylation in LIM1215 and SW403 cells stimulated with TGFa,
but this inhibition was predicted to be much weaker in HCT116
and SW480 cells. Furthermore, the networks predicted that ERK
stimulates AKT phosphorylation in HT29 cells in response to
TGFa. The networks of IGF1-stimulated cells indicated that ERK
inhibits AKT phosphorylation in all cells, with the weakest effect
predicted for SW480 cells. In IGF1- or TGFa-stimulated cells,
the networks predicted that AKT promotes MEK phosphorylation
in all cells except the SW480 cells, in which the relationship from
AKT to MEK is negative in IGF1-stimulated cells. The networks
also predicted differences in signal integration resulting from the
actions of ERK and AKT on GSK3b and p70S6K phosphorylation.
The HCT116 cell networks predicted that GSK3b is regulated by
both ERK and AKT, but the LIM1215 cell networks indicated
mostly ERK as promoting GSK3b phosphorylation, and the
HT29 cell networks predicted an inhibitory effect of AKT on
GSK3b phosphorylation in response to TGFa and a relatively small
positive effect in response to IGF1. Similarly, in SW403 cells, the
networks predicted differential AKT-mediated effects on GSK3b
in response to IGF1 or TGFa: IGF1 promoted a positive and predominant regulation of GSK3b phosphorylation by AKT, and
TGFa produced an inhibitory effect of AKT on GSK3b phosphorylation. The SW403 cells were again predicted to be different from
the other cell lines with regard to regulation of p70S6K phosphorylation, which is stimulated by ERK in all cell lines and also by
AKT in all except the SW403 cells.
Feedback loops were also predicted to operate differentially between cell lines. For instance, p70S6K can function as part of a negative feedback loop that inhibits IRS1 by phosphorylating its
inhibitory sites (Ser636 and Ser639). This negative feedback loop
was strongest in the models of SW480 cells and was not present in
the models of LIM1215 cells exposed to either TGFa or IGF1. Both
KRAS allele (40); and HT29 cells, which
have a BRAFV600E mutation. We investigated the strength of the p70S6K to IRS1
feedback loop by inhibiting p70S6K phosphorylation or reducing p70S6K abundance and subsequently measuring
IRS1S636/S639 phosphorylation 0, 10, and
60 min after TGFa stimulation. We inhibited p70S6K phosphorylation using
a small-molecule inhibitor of AKT,
which directly phosphorylates p70S6K,
and small interfering RNA (siRNA) that
reduces p70S6K abundance. The AKT
inhibitor reduced TGFa-stimulated
p70S6K phosphorylation in all four cell
lines (Fig. 4A and fig. S2), although the
effect was less in the SW480 cells. Only
in the HCT116 and SW480 cell lines
did AKT inhibition significantly reduce
IRS1S636/S639 phosphorylation. The siRNAmediated p70S6K knockdown was variably effective across the cell lines, with the
HCT116 and HKE3 cells showing the most
effective reduction in p70S6K abundance.
Despite the differences in knockdown efficiency, the p70S6K-targeted siRNA caused
a significant reduction in IRS1S636/S639
phosphorylation in HCT116 and SW480
cells, but not in HKE3 and HT29 cells,
60 min after TGFa stimulation (Fig. 4B
and fig. S3). Thus, the observed differences
in IRS1S636/S639 phosphorylation did not
correlate with efficiency of knockdown
and were more likely to represent cell
line differences in the strength of the
feedback loop.
These observations suggested that the
p70S6K to IRS1 negative feedback is
prominent in HCT116 and SW480 cells,
but it is weaker or not present in HT29
and HKE3 (Fig. 4C). The differences in
Fig. 2. Sensitivity of BMRA to noise and data incompleteness in comparison to other algorithms. (A) Performances
this feedback between HCT116, SW480,
of BMRA, LMML, pLasso, and CORENet in terms of area under the receiver operating characteristic (AUROC) curve and area
and HT29 cells agree with the results of
under the precision recall (AUPR) curve values at different levels of noise. (B) Performances of BMRA, LMML, pLasso, and
CORENet in terms of AUROC and AUPR values for decreasing numbers of replicates. (C) Performances of BMRA, LMML,
the networks resulting from the BMRA
pLasso, and CORENet in terms of AUROC and AUPR values for decreasing numbers of perturbation experiments.
algorithm (Fig. 3A). Additionally, the differences in this feedback between
HCT116 and SW480 are resistant to EGFR inhibitor drugs (38), and HCT116 and HKE3 cells, which differ only by the presence or absence
negative feedback loops may play important roles in drug resistance of the mutated KRAS allele, suggested that the KRAS mutation
(39). Therefore, we chose this feedback loop for further exploration contributes to the strength of this negative feedback loop. However,
and performed biochemical experiments to (i) validate its existence the BMRA algorithm did not predict that this feedback would be
and (ii) determine whether it is associated with any of the commonly strong in SW403 cells, which also have the KRAS mutation. This
occurring oncogenic mutations.
may be due to noise in the perturbation data set that prevented the
BMRA algorithm from detecting this feedback in SW403 cells. AlterDifferential feedback inhibition of IRS1 by p70S6K in
natively, the KRAS mutation alone may not suffice to enable this
feedback loop, which may depend on other genotypic features that
We chose four cell lines for the biochemical experiments: HCT116 and are common to HCT116 and SW480 cells but are absent in SW403
SW480 cells, which have oncogenic KRAS mutations; HKE3 cells, which cells. However, the data indicated that, in the context of these CRCs,
are genetically identical to HCT116 with the exception that the mutant the KRAS mutation is necessary but may not be sufficient for the
KRAS allele was knocked out, leaving the cells with a single wild-type p70S6K to IRS1 negative feedback loop.
Fig. 3. Network reconstruction of the EGFR and IGF1R pathways in colon cancer cells. (A and B) Reconstructed network models of cells stimulated with TGFa or
IGF1. The left graphs show the predicted interaction strengths, with red bars indicating positive interaction strengths and blue bars indicating negative interaction
strengths. The x axis represents interactions that occur in the TGFa- or IGF1-stimulated cells, the y axis represents cell lines, and the z axis represents interaction
strengths. The height of each bar and the associated error bar represent the absolute mean and SD of the corresponding interaction strength. The width of each
bar represents the corresponding interaction probability. The right network diagrams show the differences in the topologies of the TGFa- or IGF1-stimulated pathways
in different CRC lines. EGFR is not part of the reconstructed networks, because it was not measured in the perturbation data set (22). We included it in these diagrams
for convenience of visualization. The squares and circles associated with each connection represent the positive (+ve) or negative (−ve) interaction strengths. The size
of the circles or squares indicates the interaction strengths; the cell lines are color-coded.
Both HCT116 and SW480 contain the negative feedback loop and
are resistant to EGFR inhibitor drugs (38). However, the network
models reconstructed by the BMRA algorithm cannot provide a
mechanistic explanation of whether and how this feedback loop, in
association with the KRAS mutation, causes resistance to EGFR inhibitors. The analysis so far also does not enable us to predict whether
targeting this feedback will sensitize the cells to subsequent treatment
with EGFR inhibitors. Therefore, we used the BMM algorithm to
Fig. 4. p70S6K-mediated feedback inhibition of IRS1 in
SW480, HCT116, HKE3, and HT29 cells. (A) Effects of AKT inhiGAPDH
bition on p70S6KT421/S424 and IRS1S636/S639 phosphorylation in
SW480, HCT116, HKE3, and HT29 cells. Starved cells were treated
TGFα 0’ 10’ 60’ 0’ 10’ 60’
with AKT inhibitor VIII (10 mM) for 1 hour and then stimulated with
TGFa (100 nM) for 0, 10, and 60 min. Phospho-AKTS473,
phospho-IRS1S636/S639, total IRS1, phospho-p70S6KT421/S424, and
total p70S6K were measured by Western blotting. (B) Effects of
p70S6K knockdown (KD) on IRS1 phosphorylation in SW480,
HCT116, HKE3, and HT29 cells. Cells were transfected with siRNA
against p70S6K. Twenty-four hours later, cells were serumGAPDH
starved for 4 hours, treated with TGFa, and analyzed as above.
Blots were quantified using ImageJ. In (B) and (C), the phosphorylated proteins were normalized to the respective total proteins, and the normalized levels were scaled between 0
and 1 and plotted. Error bars were calculated from n = 3 independent experiments (figs. S2 and S3). P values were calculated using Kruskal-Wallis test. (C) Graphical summary of
the results. The squares and circles represent the positive (+Ve) or negative (−Ve) interaction strengths, respectively. GAPDH, glyceraldehyde-3-phosphate dehydrogenase.
derive a mechanistic model of the EGFR and IGF1R pathways in
HCT116 cells and used this mechanistic model to address these
questions.
Initial validation of the mechanistic model
We performed model simulation using an ensemble of ODE
models, each of which was fitted with parameter values sampled
from the corresponding posterior distribution (note S6). We then
used the average and SD of the ensemble simulations to represent
simulation results and the corresponding confidence intervals.
First, we verified that the interaction strengths simulated by the calibrated model resembled those estimated by the BMRA algorithm
(fig. S1, A to C). Subsequently, we simulated the dynamics of the
amount of active ERK and AKT in response to different amounts of
ligands. The model simulations suggested that ERK and AKT were
transiently activated at low levels of ligand stimulation but then
quickly achieved sustained activation at higher levels (Fig. 6A).
To validate these predictions, we tested the dynamics of AKT
and ERK phosphorylation in serum-deprived HCT116 cells in response to high and low concentrations of EGF and insulin. EGF
and insulin activate the same receptors as TGFa and IGF1, but
EGF and insulin are more commonly used in literature for studying
ERK and AKT activities. By using EGF and insulin for these
experiments, we could use existing information from literature to
determine different aspects for the validation experiments, such as
high and low ligand concentrations and optimal time points for
measurement. The measured dynamics of ERK and AKT in response to the two different concentrations of EGF were similar
to those predicted by the model simulations—transient and sustained activation at low and high ligand concentrations, respectively
(Fig. 6B and fig. S4). The response to insulin was not as consistent
with the simulations as the EGF response was (Fig. 6C and fig. S4).
In agreement with the model simulation, the cells exhibited sustained
phosphorylation of AKT at high insulin concentration. However, at
low insulin concentration, simulations indicated an initial peak in
AKT activity at ~10 min, which then dipped at ~40 min before
mostly recovering at 60 min (Fig. 6A). This transient reduction
in AKT phosphorylation was not captured in the experimental
results, which were obtained at 0, 10, and 60 min (Fig. 6C and
fig. S4). Also, the cells had high basal ERK phosphorylation even
before insulin stimulation. This was an unexpected observation
and did not agree with simulations, because in the simulation
study, we assumed that starved cells start from a basal state lacking
phosphorylation (2–9).
Despite some discrepancies between the simulation and experimental data, which can be attributed to unexpected basal phosphorylation and low temporal resolution in the experimental data, the
model did match ERK and AKT dynamics in many respects in response to ligand stimulations. Therefore, we thought that the
model would be useful to explore the role of the p70S6K to IRS1
negative feedback loop in the resistance of HCT116 cells to EGFR
inhibitors.
Mechanistic modeling of EGFR and IGF1R networks in
HCT116 cells using the BMM algorithm
The main purpose that we had for developing the mechanistic
model was to study the effects of ligands (TGFa for the EGFR
pathway and IGF1 for the IGF1R pathway), EGFR inhibitors,
and perturbations to p70S6K to IRS1 negative feedback loop on
the amount of active ERK and AKT in HCT116 cells. We developed an ODE model of the generic EGFR and IGF1R pathways
using the generic network (Fig. 5A). We could use the generic
network, because BMRA did not infer any previously unknown interactions (Fig. 3).
The generic model (Fig. 5A) only contains a single receptor
(IGFR) and lacks RAS, which we determined was important for
the negative feedback loop and is present in an oncogenic form
in HCT116 cells, and the kinase RAF, which is activated by RAS
and signals to MEK and AKT (3, 22, 41). The generic model also
lacks PI3K, which is mutated in HCT116 cells (3, 41). Therefore,
we had to modify the generic network to include both receptor inputs EGFR (the target of EGFR inhibitors) and IGFR, RAS (representing KRAS and connecting EGFR to RAF), RAF (connecting
RAS and AKT to MEK), and PI3K (connecting IRS to downstream
AKT). To reduce the complexity of the model, we excluded GSK3b
and IkB, which are downstream of ERK and AKT and have limited
influence on the activities of either ERK or AKT. The resulting
model (Fig. 5B) contains 10 proteins—EGFR, IGFR, RAS, RAF,
MEK, ERK, IRS, PI3K, AKT, and p70S6K—and the relationships
connecting them.
We collected information about the mechanism of protein activation or inhibition from the literature (3–6, 8–10, 24, 34). Protein
activation or inhibition events are often multistage processes that
can involve multisite phosphorylation, conformation change, dimerization, or interaction with other partners, among others
(3–6, 8–10, 24, 34). To reduce model complexity, we simplified these
processes to single partial steps (3) that transform a protein from its
inactive to active or inhibited form or vice versa. We modeled most
protein activation and inhibition processes using Michaelis-Menten
kinetics, except for the modulation of AKT phosphorylation by
ERK, which is indirect and occurs through unknown components.
We modeled the ERK-mediated regulation of AKT as a hyperbolic
modifier function (42).
The resulting ODE model had 66 parameters that were initially
unknown (Fig. 5B). The BMM algorithm identified 17 parameters
(highlighted yellow in Fig. 5B) that were predicted to have the most
impact on the model output (note S6). We used the BMM algorithm
to estimate HCT116-specific posterior distributions of these parameters while keeping the remaining parameters at fixed values (note
S6). BMM iteratively compared the simulated interaction strengths
among IGFR, IRS, AKT, MEK, ERK, and p70S6K with those estimated by the BMRA algorithm (Fig. 3, A and B) for parameter estimation. We excluded the interaction strengths among GSK3b, IkB,
AKT, and ERK from the BMM algorithm, because these proteins are
not in the ODE model. The estimated posterior distributions (Fig.
5C) reflect well-known characteristics of EGFR and IGF1R pathways
in HCT116 cells. For instance, the activating KRAS mutation in
HCT116 cells was well described by the posterior distributions of
the RAS activation and inactivation rates, which indicated that
RAS is activated at a much higher rate (kras1 = 1.35 ± 0.36 min− 1 and
kras2 = 3.02 ± 1.5 min−1; see Fig. 5C) than when it is inactivated
[VMras = 0.012 ± 0.18 arbitrary unit (AU) min−1]. Additionally, the
inferred posterior distributions of many model parameters have
more than one mode or peak and, in most cases, have two dominant
peaks (bimodal) (Fig. 5C), which is consistent with what is known
about how the activation and inactivation rates of the components
vary depending on the input signal and the stimulation of the EGFR
or IGFR (3, 9, 41).
Sensitizing the model to EGFR inhibitors by simulating
Model simulations indicated that knocking down p70S6K would
not affect ERK phosphorylation but would increase AKT phosphorylation (Fig. 7A) in HCT116 cells stimulated through the EGFR
pathway. To verify this prediction, we knocked down p70S6K in
the serum-starved HCT116 cells
and exposed the cells to TGFa
(Fig. 7B and fig. S5). Although
both EGF and TGFa were previously shown to strongly
stimulate p70S6K phosphorylation (43, 44), we used TGFa
in these experiments because
we detected the p70S6K- and IRS1-mediated feedback loop in TGFastimulated networks (Fig. 3). p70S6K knockdown increased the
amount of TGFa-stimulated AKT phosphorylation without causing
a significant change in ERK phosphorylation (Fig. 7B and fig. S5), suggesting that AKT activity is affected by the p70S6K to IRS1 negative
feedback loop. Hence, we analyzed AKT activity in serum-grown
Fig. 5. Mechanistic modeling of
EGFR and IGF1R pathways in HCT116
cells. (A) Extending the generic signaling
network for mathematical modeling.
The indexed gray dashed lines in the
left panel represent the interactions
that were expanded for ODE modeling.
The blue lines in the right panel represent the corresponding (indicated by the
index) expanded interactions. The red
lines in the right panel represent newly
added interactions. The light gray nodes
and lines in the right panel represent the
interactions that were excluded from the
ODE modeling. (B) Mathematical model
of the generic EGFR and IGF1R pathways.
Each protein has an inactive and active
state denoted by the suffix “a.” Proteins
that are phosphorylated at inhibitory
sites also have inhibited states denoted
by the suffix “i.” MM(kx, Kx) represents
the Michaelis-Menten kinetics with rate
and dissociation constants kx and Kx, respectively; MM1(KMx, VMx) represents
the Henri-Michaelis-Menten kinetics
with the Michaelis constant KMx and
the maximum velocity constant VMx;
HM(kx, Kx, Kx1, b) represents the general
hyperbolic modifier kinetics (29) with
the rate constant kx, dissociation constant Kx, activation or inactivation constant Kx1, and modification constant b.
The molecules in red have activating
mutations in HCT116 cells. The model
was found to be sensitive to the parameters highlighted in yellow. (C) Prior
and posterior distributions of the sensitive parameters. The x axis of each
subplot represents the values of the
corresponding parameter, and the y
axis represents the posterior probabilities associated with these values. The
distributions of prior values are represented by gray curves.
in the presence of serum, the system is
not starting from baseline of no activiAKT
ty. First, we simulated active AKT conpERKT202/Y204
centration in response to either p70S6K
knockdown or EGFR inhibition. As in
the case of ligand-mediated stimulation
of the EGFR pathway with either TGFa
or EGF, simulating p70S6K knockdown
produced an increase in the amount of
active AKT; simulating EGFR inhibition with a reversible and selective inhibitor showed a small reduction in
the amount of active AKT at ~12 min
before recovering to its initial amount
at ~27 min (Fig. 7C). Analysis of
AKT phosphorylation in HCT116 cells
exposed to the reversible and selective
EGFR inhibitor BIBX1382 or in which
p70S6K was knocked down showed
profiles consistent with the simulation
results (Fig. 7, D and E, and fig. S5).
We then simulated the amount of active
AKT in response to combinations of difGAPDH
ferent p70S6K knockdown efficiencies
and “doses” of EGFR inhibitor (note
S6) in serum-grown HCT116 cells. The
simulation suggested that a combination
of partial p70S6K knockdown and EGFR
inhibitor results in reduction in AKT
phosphorylation compared to either individual treatments (Fig. 7F). This was
confirmed in biochemical experiments
HCT116 cells using inhibitors or knockdown to perturb the cells with- (Fig. 7, D and G, and fig. S5). This effect on AKT activation is counout exogenous ligands in addition to the ones in the serum.
terintuitive, because one might predict that loss of a negative feedback
In the simulations of ligand-stimulated responses, the system loop would enhance activity rather than suppress it.
starts from a resting point with no active AKT or ERK. When
The presence of multiple positive and negative feedback loops that
we simulate the effects of p70S6K knockdown or EGFR inhibition affect AKT activity may explain this counterintuitive behavior of AKT
Fig. 6. Biochemical validation of the mechanistic ODE model. (A) Simulated dynamics of
ERK and AKT activation for different levels of
EGF/TGFa and insulin/IGF1 stimulations, respectively. The x axis represents time in minutes, the
y axis represents EGF or insulin levels in AUs,
and the z axis represents the concentrations of
activated ERK (A and C) and AKT (B and D) in
AUs. Solid lines represent average activities,
and the shaded areas correspond to SDs. (B
and C) Phosphorylation levels of ERK1/2T202/Y204
and AKTS473 at 0, 10, and 60 min were determined
by Western blotting after stimulation of serumstarved HCT116 cells with EGF (20 or 100 ng/ml)
(B) or insulin (1 or 10 mg/ml) (C). Blots were quantified using ImageJ. The phosphorylation levels of
ERK1/2T202/Y204 and AKTS473 were then normalized
to the loading control GAPDH, scaled between 0
and 1, and plotted. The data represent n = 3
independent experiments (fig. S4), with error
bars indicating SD. P values were calculated
using Kruskal-Wallis test.
P (CTRL vs. BIBX) = 0.458
BIBX:
TGFα (100 nM) 0’ 10’ 60’ 0’ 10’ 60’
TGFα (100 nM) 0’ 10’ 60’ 0’ 10’ 60’
Fig. 7. The role of the p70S6K-mediated negative feedback to IRS1 in EGFR inhibitor resistance of HCT116 cells. (A) Simulated active ERK (blue) and AKT (red) concentrations after p70S6K knockdown and different levels of EGF or TGFa (EGF/TGFa) stimulations. Solid lines and shaded areas represent means and SDs. (B) Effects of p70S6K
knockdown on AKTS473 and ERK1/2T202/Y204 phosphorylation. HCT116 cells were transfected with nontargeting siRNAs (CTRL) or siRNAs against p70S6K (KD) and grown in serum
(see fig. S2 for knockdown efficiency) for 24 hours. Then, starved (4 hours) cells were stimulated with TGFa (100 nM) for the indicated time points. Protein levels were quantified
and normalized as above. Data are representative of n = 3 independent experiments (fig. S6). P values were calculated using Kruskal-Wallis test. (C) Simulated effects of p70S6K
knockdown and EGFR inhibition on AKT activation in serum-grown HCT116 cells. The starting amounts of ligand were set to 0.01 AU. (D and E) Effects of p70S6K knockdown and
EGFR inhibition on AKTS473 phosphorylation in serum-grown HCT116 cells. Control and knockdown HCT116 cells were treated with the EGFR inhibitor BIBX1382 (BIBX; 5 mM).
Phosphorylated AKTS473 levels were measured at the indicated time points after treatment and normalized by total AKT levels. Data are from n = 3 independent experiments
(fig. S5). P values were calculated using Kruskal-Wallis test. A representative blot is shown in (E). (F) Simulation of AKT activity for different p70S6K knockdown efficiencies and
EGFR inhibitor strengths. (G) Phosphorylated AKT S473 levels in control and knockdown HCT116 cells with and without BIBX1382 treatment. Data represent n = 3 independent
experiments. P values were calculated using Kruskal-Wallis test. (H) Feedback loops that control AKT phosphorylation. Positive feedback loops (highlighted in blue) controlling
AKT phosphorylation and negative feedback loops (highlighted in red) controlling AKT phosphorylation.
Fish with micrometastases in tail
Fig. 8. Synergism between EGFR inhibition and p70S6K knockdown in cultured and xenografted HCT116 cells. (A) Effects of p70S6K knockdown and EGFR
inhibition on apoptosis of CRC cells. Left, HCT116; middle, HKE3; right, HT29. Control and knockdown cells were treated with 5 mM BIBX1382, and apoptosis was
measured 48 hours later. Fold changes in apoptosis with respect to control cells are shown. Results represent four independent experiments (figs. S7 to S9). P values
were calculated using Kruskal-Wallis test. (B) Workflow of the zebrafish xenograft–based model validation system. dpf, days post-fertilization. (C) Effect of lapatinib or
control [dimethyl sulfoxide (DMSO)] treatment on zebrafish embryos co-injected with DiO-labeled control and DiI-labeled p70S6K knockdown HCT116 cells in the yolk
sac. Fish were assessed for survival and dissemination of injected HCT116 cells (the number of fish with no cells detected outside the yolk sac = no dissemination or
cells detected in the tail) 3 days after injection and treatment. (D) Quantitation of disseminated cells within the zebrafish after DMSO (n = 11 fish) or lapatinib (n = 9 fish)
treatment (mean ± SEM). P values were calculated using Kruskal-Wallis test. (E) Microscopic images of disseminated DiO-labeled control (CTRL; green) and DiI-labeled
p70S6K knockdown (KD; red) HCT116 cells in the zebrafish tail after DMSO or lapatinib treatment. The white bar represents 0.5 mm.
in response to the combination of p70S6K knockdown and EGFR inhibition. AKT activity is tightly controlled by several negative and positive feedback loops (Fig. 7H), and some of these involve p70S6K. In the
HCT116 cells, the negative feedback loop involving AKT and p70S6K is
usually operational and causes an increase in AKT phosphorylation in
response to p70S6K knockdown (Fig. 7, A to E). However, the positive
feedback loops involve the RAF-MEK-ERK pathway, which becomes
saturated in the presence of ligand, aided by mutant RAS, and is not
affected by p70S6K knockdown (Fig. 7, A and B, and fig. S6). EGFR
inhibition releases this pathway from this saturating effect, enabling
the positive feedback loops involving p70S6K and AKT to have an effect. When both positive and negative feedbacks involving p70S6K and
AKT are operational, AKT phosphorylation may either increase or decrease in response to p70S6K knockdown depending on which
feedback loops have more impact on its phosphorylation. The positive
feedback loops involving p70S6K are reinforced by several other positive
No. of micrometastases in tail
feedback loops (Fig. 7H), involving the RAF-MEK-ERK pathway.
Therefore, it is possible that, in the presence of EGFR inhibitors, the
positive feedback loops have a stronger impact on AKT phosphorylation
than the negative feedback loops, which leads to a decrease in AKT
phosphorylation in response to p70S6K knockdown.
Here, we present a computational pipeline that reconstructs network
models by combining prior knowledge with perturbation data sets
and then develops predictive mechanistic models on the basis of the
reconstructed networks. This method of developing predictive network
models relaxes the dependence of such predictive models on prior
knowledge and provides a data-driven approach. This approach also
overcomes some limitations, for example, sensitivity to noise and data
incompleteness, of other network reconstruction and modeling
approaches. Furthermore, BMRA characterizes each interaction by
the probability distribution of its strength and the probability of its existence. These attributes reveal critical details of each interaction: its
strength (mean of its distribution), type [that is, whether the interaction
activating or inhibiting (sign of the mean)], direction, confidence interval for its strength (SDs of the distribution), co-dependence between
different interactions (covariance between interaction strengths), and
the probability of whether it is genuine or an artefact of spurious noise.
Consider an N node (ni, i = 1 … N) biochemical network. MRA
a perturbation (pk ), the fractional
in the steady-state concentration (xiSS ) of
a network node (ni) is linearly related to that (Rjk, j ≠ i) of the other
nodes (nj, j ≠ i) through the corresponding interaction strengths
(rij, j ≠ i).
∑nj¼1;j≠i rij Rjk ¼ Rik ; i ≠ k; i; k ¼ 1 …N
Synergistic effects of EGFR inhibition and p70S6K
knockdown in culture and in vivo
Inhibition of AKT pathway increases apoptosis and decreases invasiveness of some cancer cells (45–50). Therefore, we tested the effects
of combining EGFR inhibition with p70S6K knockdown on serumgrown HCT116 cells (Fig. 8A and fig. S7). The combination induced
a significantly higher level of apoptosis in HCT116 cells compared to
either individual treatment. The Bliss independence score of the
combination, which is the log2 ratio of the expected to observed cell
mortality rates, was found to be −0.217, suggesting that the combined treatment killed more cells than the individual treatments
combined and indicating a synergistic effect of the combination on
HCT116 cell death. HKE3 and HT29 cell lines, which our analysis
indicated lack this feedback loop, exhibited increased apoptosis in
response to EGFR inhibition, and the amount of toxicity was unchanged by p70S6K knockdown (Fig. 8A and figs. S8 and S9).
We also tested the effect of the EGFR inhibitor lapatinib on metastasis of control or p70S6K knockdown HCT116 cells in a zebrafish
(Danio rerio) metastasis assay. We used lapatinib because we found
that BIBX1382 was toxic to zebrafish embryos, which died shortly after exposure to BIBX1382. The dye-labeled HCT116 cells that migrated out of the yolk sac (the site of injection) to the tail represented
metastasis. Lapatinib treatment of embryos injected with control
HCT116 cells reduced the number of fish with cells in the tail (Fig. 8,
B and C). Lapatinib treatment was even more effective when used
on the embryos injected with p70S6K knockdown cells (Fig. 8D),
consistent with the synergistic effect that we observed in the HCT116
cells in culture.
These results suggested that the negative feedback loop from p70S6K
to IRS1 plays a role in defining the sensitivity of HCT116 cells to EGFR
inhibition line and that inhibition of p70S6K could increase the cytotoxic effects of EGFR inhibition. This further strengthens the hypothesis
that p70S6K-mediated negative feedback loop plays a role in the EGFR
inhibitor resistance of HCT116 cells.
Such details are invaluable in building mechanistic models based on reconstructed networks. A benefit of our mechanistic modeling approach
is that it does not require extensive multiconditional time course
experiments for model calibration. It relies on the quantitative and qualitative properties of the reconstructed networks.
Nevertheless, our approach is not without limitations: It is applicable
in cases where a reasonable amount of prior knowledge and experimental data are available, and the ODE model in our method is calibrated to
exhibit similar interaction strengths as the probabilistic networks, which
are estimated from steady-state perturbation data. Therefore, these
models are more likely to correctly simulate steady-state behavior than
pathway dynamics. This could be remedied by using additional time
course data for calibration. Finally, our algorithm is computationally
intensive and, in its current form, can be used to analyze networks
containing a maximum of 25 nodes within reasonable time. For bigger
networks, the number of parameters that need to be calibrated increases, which would require using specialized Markov chain Monte
Carlo (MCMC) methods designed for exploring high-dimensional
parameter spaces, such as Riemann manifold Langevin–adjusted
Metropolis-Hastings methods (51). Despite these limitations, we demonstrated that the current computational approach is a useful tool for
exploring the mechanistic roles of signaling networks in disease and
drug resistance and for predicting new therapeutic targets.
We demonstrated the effectiveness of our method by revealing a
mechanism of EGFR inhibitor resistance in HCT116 cells using a
small set of highly incomplete and noisy data. Additionally, our computational pipeline pinpointed a potential therapeutic approach to
overcome EGFR inhibitor resistance in colon cancer cells. We identified a role of the p70S6K to IRS1 negative feedback loop in EGFR
inhibitor resistance of metastatic CRC lines. Here, we provided experimental support for the role of this feedback in EGFR inhibitor
resistance and identified an association of this feedback loop with
KRAS mutation in some colon cancer cells. This feedback loop has
been suspected, but not supported experimentally, in EGFR inhibitor resistance of several breast, colon, lung, kidney, pancreas, and
glioblastoma cancer cells (52, 53). Because inhibition/siRNAmediated knockdown of p70S6K synergistically kills head neck and
small cell lung cancer cells when combined with EGFR inhibitors (54,
55), this feedback loop may be an important target for many different
cancers. Here, using multiple methods, we showed that p70S6K
knockdown synergizes with subsequent EGFR inhibitor treatment to
kill KRAS-mutated colon cancer cells, but not cells lacking this mutation. Additionally, this combination synergized in reducing metastasis
of KRAS-mutated colon cancer cells in zebrafish xenografts. Therefore,
our study contributed valuable insight for treating patients with KRASmutated, EGFR inhibitor–resistant, metastatic CRC.
If node nj, j ≠ i directly influences node ni, then rij ≠ 0; otherwise,
rij = 0. We modified this equation by introducing two more variables,
a binary variable Aij in Eq. 1 to indicate whether nj directly influences
ni (Aij = 1) or not (Aij = 0) and an error variable (Dik) to account
for the imbalance in Eq. 1 caused by noisy experimental data. The
resulting modified MRA equation is shown below.
∑nj¼1;j≠i Aij rij Rjk þ Dik ¼ Rik ; i ≠ k; k ¼ 1 …N
P Ai ºexp  y  dH ðAi ; A i Þ
where y is a constant and dH ðAi ; A i Þ is the Hamming distance between
Ai and A i . P(Ai) favors the subnetworks that are in agreement with
existing knowledge and penalizes those that are in disagreement.
The extent of penalty depends on y with larger values, resulting in
stiffer penalties. The prior distribution of ri is dependent on Ai and
is denoted by P(ri|Ai). In the absence of a direct interaction from nj
to ni (that is, Aij = 0), the corresponding interaction strength (rij) was
assumed to have 0 value with probability 1, whereas the interaction
strengths representing direct interactions (Aij = 1, j ≠ i) were assumed
to have Gaussian priors (note S1) (18, 56). The above prior distributions
(P(Ai), P(ri|Ai)) were then used to calculate the likelihood (P(R|ri, Ai))
of the global changes (R) given the network descriptors (Ai, ri) (note
S1). Subsequently, we applied Bayes’ rule (57) to calculate the joint posterior distribution (P (Ai,ri |R)) for the network descriptors (ri , Ai).
Using the chain rule, the above joint posterior P(Ai, ri |R)) is the product
of the marginal posterior (P(Ai|R)) of the binary indicators (Ai) and the
conditional posterior (P(ri |Ai, R)) of the interactions strengths (ri), that
is, P(Ai, ri |R) = P(ri| Ai, R) × P(Ai|R). The marginal posterior (P(Ai|R))
is proportional to the product of a multivariate Student’s t (MVSt) and
the prior distribution, whereas the conditional posterior (P(ri| Ai, R)) is
proportional to the MVSt distribution (note S1). The constant of proportionalities of the above posterior could not be calculated analytically;
therefore, we used an MCMC algorithm to approximate the true joint
posterior P(Ai, ri |R). The MCMC algorithm starts with a random
network, and each iteration (t) randomly proposes a new subnetwork
i ) of A i , which differs from the current subnetwork by only one interaction (note S1) (15, 58). The proposed subnetwork was then accepted
(note S1) (59). Subi ) with probability a ¼ min 1; PðAt jRÞ
sequently, we drew a sample (rti ) from the conditional distributions
Pðri jAti ; RÞ using a random vector generator that samples from custom
MVSt distributions. The above two steps were repeated for a large number (105) of iterations, and after an initial burn-in period (5 × 104 iterations), the accepted network topologies and interaction strengths
were recorded. The mean of an element Aij of Ai over the post–burnHalasz et al., Sci. Signal. 9, ra114 (2016)
Calibrating the parameters of the ODE model
To calibrate the parameters (Q) of the ODE model, we first identified those parameters (Qs ⊆ Q) that had the maximum impact on
the model output(s). Here, the model output (Mo) is defined as the
area under the concentration versus time curve (xo(t)) of the output
node (no) of the model, that is, Mo ¼ ∫∞
t¼0 xo ðtÞdt. When a model
has many output nodes (no1, no2 …), the sum of the areas of their
concentration curves (xo1(t), xo2(t), …) is used as the model output
t¼0 ðxo1 ðtÞ þ xo2 ðtÞ þ …Þdt). If a small change (Dqk) in a
parameter (qk) causes the model output to change by DMo, then
 (Sk) of the model to this parameter is given by Sk ¼
. These sensitivities quantify the impact of a model’s
parameters on its output. Model sensitivities (Sk) were estimated
for each model parameter (qk) for a large number (105) of randomly generated (note S6) parameter settings using Monte Carlo
sampling (fig. SN6.1). The parameters that had low (≈ 0) average
sensitivities were assigned fixed values (note S6), and those with
higher average sensitivities (≫ 0) were calibrated using a Bayesian
parameter estimation algorithm. First, we assigned a prior probability distribution (P(Qs))(note S6) to the sensitive parameters
 likelihood function (LðQs Þ) for the same:
LðQs Þº ∏l jSrl j2 exp ðrMl  mrl ÞT S1
rl ðrMl  mrl Þ . Here, rl represents the simulated interaction strengths in condition l (for example, ligand stimulation); mrl and Srl are their means and covariance
matrices as estimated by the BMRA algorithm from experimental
data. We then used Bayes’ rule (57) to calculate the posterior
distribution [P(Qs| mrl, Srl, l = 1, 2 …)] of the sensitive parameters
(Qs): PðQs jmrl ; Srl ; l ¼ 1; 2…ÞºLðQs ÞPðQs Þ: However, the posterior distribution could only be calculated up to a constant of proportionality. Therefore, MCMC sampling was used to estimate the
true posteriors of these parameters. The MCMC algorithm starts
with a random set of values for the sensitive parameters, and each
iteration (t) proposes a new set of values (Qtn
s ) based on their current
values (Qts ) using a Gaussian proposal
s Qs Þ ),
which is defined in log space, that is, log Qs Þ ∼ N logðQs Þ; VQ , where
VQs is the covariance matrix of the proposal distribution (note S6).
a ¼ min 1 PðQst jm rl;Srlrl;l¼1;2…:Þ (note S6) (59). This process was res
peated many times (2.5 × 10 5), and the samples drawn after a
burn-in (105) period were used to estimate the posterior distribution
of Qs. The variances ðVQs Þ of the proposal distribution were adaptively (note S6) tuned to improve mixing of the MCMC chains (60).
For a robust exploration of the parameter space, we deployed
multiple parallel Markov chains that operate at different “temperatures”
(parallel tempering) (61). The chains that operate at high temperatures
(temperature ≫ 1) take large steps and can explore a vast region in the
parameter space relatively quickly. The chains that operate at low temperature (≈ 1) take small steps and perform local searches. These chains
pass information among each other in a probabilistic manner, helping the
We used Bayesian statistics to infer the probability distributions of
Aij, i ≠ j and rij, i ≠ j from experimentally measured R. First, we conceptually divided the N node network into N smaller subnetworks, each of
which consists of a specific node (ni) and its regulators. The probability
distributions of the network descriptors (Ai = {Aij, j ≠ i}, ri = {rij, j ≠ i}) of
each of these subnetworks were inferred separately. We first formulated
prior probability distributions of Ai and ri based on existing knowledge
of the network topology. The binary vector A i denotes the known regulators of node ni. The prior distribution (P(Ai)) of Ai was then formulated as follows:
in samples was then used as the posterior
probability of the interaction
from node nj to ni, that is,P Aij jR ¼ 510
4 ∑t¼5104 þ1 Aij. On the other
hand, the sample means, variance, and covariance of different interaction strengths (rij) across the post–burn-in samples were used as the
posterior mean, variance, and covariance, respectively, of the strengths
of the interaction from node nj to ni. A MATLAB implementation of
the above (BMRA) algorithm can be found in the Supplementary
Materials (code S1).
Markov chains operating at low temperature to avoid getting stuck at local minima. The samples drawn by the chain operating at normal temperature (temperature = 1) were used to estimate the posterior
distribution of Qs. A MATLAB implementation of the above calibration
algorithm can be found in the Supplementary Materials (code S1).
The human colorectal adenocarcinoma cell line HT29 was acquired
from the European Collection of Cell Cultures. The human colorectal carcinoma cell lines HCT116 and HKE3 were provided by
S. Shirasawa (43). Cells were maintained in complete medium [highglucose Dulbecco’s modified Eagle’s medium (DMEM) (Invitrogen
Life Technologies), supplemented with 10% fetal bovine serum
(FBS) (Invitrogen Life Technologies), penicillin (100 IU/ml), and
streptomycin (100 mg/ml) (Invitrogen Life Technologies)] and incubated at 37°C in a humidified atmosphere of 5% CO2.
Validated siRNA to interfere with RPS6KB1 mRNA (sense, 5′GGUUUUUCAAGUACGAAAAtt-3′; antisense, 5′-UUUUCGUACUUGAAAAACCtt-3′) and nontargeting control siRNA were predesigned
and obtained from Ambion. Transfections were performed with
Oligofectamine (Invitrogen Life Technologies) according to the manufacturer’s instructions. Briefly, diluted oligonucleotides were preincubated with Oligofectamine for 20 min at room temperature, and then
the mixtures were added dropwise to 1.5 × 105 cells in Opti-MEM
(Invitrogen Life Technologies). After 4 hours at 37°C, DMEM with
30% FBS was added to the cultures to achieve a final FBS of 10%.
Cells were lysed after 24, 48, or 72 hours for Western blot analyses
to test the efficiency of knockdown.
Quantitative immunoblotting
Cells were serum-starved for 4 hours before stimulation. Cells were
lysed in 1× Lysis Buffer (Cell Signaling Technology Inc.) according
to the manufacturer’s instructions. NuPAGE Bis-Tris gels (Novex,
Life Technologies) were used to resolve proteins. Gels were transferred to polyvinylidene difluoride membrane at 30 V for 1 hour.
Membranes were blocked with tris-buffered saline (TBS)–Tween
(pH 7.4) containing 5% skim milk for 1 hour and incubated with
1:1000 diluted rabbit anti-human phospho-AKT (Ser473), AKT,
phospho-p44/42 MAPK (Thr202/Tyr204), p44/42 MAPK, p70 S6
kinase, phospho-p70 S6 kinase (Thr389), IRS1, and phospho-IRS1
(Ser636/Ser639) antibodies or as control with mouse anti-human
GAPDH (all from Cell Signaling Technology Inc.) in TBS-Tween with
5% bovine serum albumin overnight at 4°C. After washing, bound
antibodies were detected with 1:5000 diluted horseradish peroxidase–
conjugated anti-rabbit or anti-mouse immunoglobulin G (Cell Signaling Technology Inc.), followed by development with WesternBright
chemiluminescent substrate (Advansta). Membranes were scanned
using a high-sensitivity charge-coupled device camera (Chemi Image,
The FITC Annexin V Apoptosis Detection Kit (BD Biosciences) was
used to detect apoptosis by flow cytometry. Cells were exposed to
BIBX1382 treatment for 48 hours, harvested (including detached
cells), and processed according to the manufacturer’s instructions.
Briefly, cells were washed twice with phosphate-buffered saline
(PBS) and resuspended in 1× annexin V binding buffer. Then, 1 ×
105 cells were incubated with 5 ml of annexin V–fluorescein isothiocyanate and 5 ml of propidium iodide for 15 min at room temperature.
Finally, 400 ml of 1× binding buffer was added. Labeled cells were analyzed with an Accuri C6 flow cytometer (Becton Dickinson Immunocytometry Systems) equipped with the Accuri C6 software program
(Becton Dickinson) for data acquisition and analysis.
Alternatively, after the drug treatments, cells were fixed in ethanol and stained with propidium iodide. The sub-G1 population
was determined using an Accuri C6 flow cytometer.
Zebrafish (D. rerio) maintenance and experiments were approved by
the University College Dublin Animal Research Ethics Committee.
Wild-type (AB line) embryos were produced by natural spawning
and kept on a 14-hour light/10-hour dark cycle at 28.5°C. Control
or p70S6K knockdown HCT116 cells were labeled with DiO or DiI
(Vybrant, Invitrogen Life Technologies) lipophilic fluorescent dyes, respectively, as described by Halasz et al. (62). Equal amounts of control
and p70S6K knockdown HCT116 cells were mixed, resuspended in
PBS, and kept on ice before microinjections. Two days after fertilization, dechorionated zebrafish embryos were anesthetized with 0.016%
MS-222 (Sigma-Aldrich), and about 100 cells were transplanted into
the yolk sac of embryos using a microinjector [PV830 Pneumatic
PicoPump (World Precision Instruments) with M-152 manipulator
(Narishige)] equipped with a glass capillary (World Precision Instruments). Then, embryos were incubated for 1 hour at 31°C and
checked for cell presence. Fish with fluorescent cells outside the implantation area were excluded from further analysis. All other fish
were incubated with DMSO or 2.5 mM lapatinib (Selleck Chemicals)
at 33°C for up to 3 days. Disseminations of cells were monitored using
an Olympus SZX10 fluorescent stereo microscope equipped with an
Olympus DP71 camera.
We compared data from Western blots, apoptosis assays, and zebrafish xenografts using nonparametric hypothesis tests, because these
tests do not make any tacit assumption about the underlying
distribution of the data. Kruskal-Wallis test (63) was used to compare
data from two or more conditions (for example, control, drug treatment, and siRNA transfection), whereas Friedman’s test (64) was used
to compare data that have multiple covariates (for example, time
course measurements in control and treated samples, the two covariates being time points and treatment).
www.sciencesignaling.org/cgi/content/full/9/455/ra114/DC1
Note S1. Details of the BMRA algorithm.
Note S2. Benchmarking the BMRA algorithm.
Note S3. Sensitivity of the BMRA algorithm to noise and data incompleteness.
The following inhibitors were used: PI3K inhibitor LY294002 (10 mM;
Calbiochem), AKT inhibitor IV (10 mM; EMD Millipore), AKT inhibitor VIII (10 mM; Sigma-Aldrich), MEK inhibitor U0126 (10 mM;
Promega), EGFR inhibitor BIBX1382 (10 mM; Calbiochem), and
lapatinib (2.5 mM; Selleck Chemicals). Cells were treated with TGFa
(100 ng/ml; PeproTech), EGF (100 ng/ml; PeproTech), or insulin
(10 mg/ml; Sigma-Aldrich).
Advanced Molecular Vision). Quantification of the bands was performed by using the ImageJ software.
Note S4. Mechanistic modeling and parameter calibration using the BMM algorithm.
Note S5. Implementing BMRA to reconstruct the EGFR and IGF1R pathways.
Note S6. Mechanistic modeling of the EGFR and IGF1R pathways and the BMM algorithm.
Fig. S1. Interaction strengths of EGF and IGF1 network based on model simulation and
experimental data.
Fig. S2. Effect of AKT inhibitor on IRS1 phosphorylation in four CRC cell lines.
Fig. S3. Effect of p70S6K knockdown on IRS1 phosphorylation in four CRC cell lines.
Fig. S4. Dynamics of ERK and AKT phosphorylation in HCT116 cells exposed to different
concentrations of ligand.
Fig. S5. Effects of p70S6K knockdown and BIBX1382 treatment on serum-grown HCT116 cells.
Fig. S6. The amount of phosphorylated ERK in response to p70S6K knockdown in serumgrown HCT116 cells.
Fig. S7. Combined effect of p70S6K knockdown and BIBX1382 treatment on apoptosis of
HCT116 cells.
Fig. S8. Combined effect of p70S6K knockdown and BIBX1382 treatment on apoptosis (cell
death) of HKE3 cells.
Fig. S9. Combined effect of p70S6K knockdown and BIBX1382 treatment on apoptosis (cell
death) of HT29 cells.
Code S1. MATLAB source codes for the BMRA, BMM algorithm, and the ODE models.
1. W. Kolch, M. Halasz, M. Granovskaya, B. N. Kholodenko, The dynamic control of signal
transduction networks in cancer cells. Nat. Rev. Cancer 15, 515–527 (2015).
2. F. Bertaux, S. Stoma, D. Drasdo, G. Batt, Modeling dynamics of cell-to-cell variability in
TRAIL-induced apoptosis explains fractional killing and predicts reversible resistance.
PLOS Comput. Biol. 10, e1003893 (2014).
3. N. Borisov, E. Aksamitiene, A. Kiyatkin, S. Legewie, J. Berkhout, T. Maiwald,
N. P. Kaimachnikov, J. Timmer, J. B. Hoek, B. N. Kholodenko, Systems-level interactions
between insulin–EGF networks amplify mitogenic signaling. Mol. Syst. Biol. 5, 256 (2009).
4. C. Chen, W. T. Baumann, R. Clarke, J. J. Tyson, Modeling the estrogen receptor to
growth factor receptor signaling switch in human breast cancer cells. FEBS Lett. 587,
3327–3334 (2013).
5. C. Chen, W. T. Baumann, J. Xing, L. Xu, R. Clarke, J. J. Tyson, Mathematical models of the
transitions between endocrine therapy responsive and resistant states in breast cancer.
J. R. Soc. Interface 11, 20140206 (2014).
6. D. Fey, D. R. Croucher, W. Kolch, B. N. Kholodenko, Crosstalk and signaling switches in
mitogen-activated protein kinase cascades. Front. Physiol. 3, 355 (2012).
7. A. Gambin, A. Charzyńska, A. Ellert-Miklaszewska, M. Rybiński, Computational models of
the JAK1/2-STAT1 signaling. JAKSTAT 2, e24672 (2013).
8. B. N. Kholodenko, O. V. Demin, G. Moehren, J. B. Hoek, Quantification of short term
signaling by the epidermal growth factor receptor. J. Biol. Chem. 274, 30169–30181
(1999).
9. R. J. Orton, M. E. Adriaens, A. Gormand, O. E. Sturm, W. Kolch, D. R. Gilbert, Computational
modelling of cancerous mutations in the EGFR/ERK signalling pathway. BMC Syst. Biol. 3,
100 (2009).
10. B. B. Aldridge, J. M. Burke, D. A. Lauffenburger, P. K. Sorger, Physicochemical modelling of
cell signalling pathways. Nat. Cell Biol. 8, 1195–1203 (2006).
11. B. N. Kholodenko, Cell-signalling dynamics in time and space. Nat. Rev. Mol. Cell Biol. 7,
165–176 (2006).
12. P. K. Kreeger, R. Mandhana, S. K. Alford, K. M. Haigis, D. A. Lauffenburger, RAS mutations
affect tumor necrosis factor–induced apoptosis in colon carcinoma cells via ERKmodulatory negative and positive feedback circuits along with non-ERK pathway effects.
Cancer Res. 69, 8191–8199 (2009).
13. M. K. Morris, J. Saez-Rodriguez, D. C. Clarke, P. K. Sorger, D. A. Lauffenburger, Training
signaling pathway maps to biochemical data with constrained fuzzy logic: Quantitative
analysis of liver cell responses to inflammatory stimuli. PLOS Comput. Biol. 7, e1001099
(2011).
14. A. R. Tentner, M. J. Lee, G. J. Ostheimer, L. D. Samson, D. A. Lauffenburger, M. B. Yaffe,
Combined experimental and computational analysis of DNA damage signaling reveals
context-dependent roles for Erk in apoptosis and G1/S arrest after genotoxic stress. Mol.
Syst. Biol. 8, 568 (2012).
15. S. Mukherjee, T. P. Speed, Network inference using informative priors. Proc. Natl. Acad. Sci.
U.S.A. 105, 14313–14318 (2008).
16. K. Sachs, O. Perez, D. Pe’er, D. A. Lauffenburger, G. P. Nolan, Causal protein-signaling
networks derived from multiparameter single-cell data. Science 308, 523–529 (2005).
17. Ö. Sahin, H. Fröhlich, C. Löbke, U. Korf, S. Burmester, M. Majety, J. Mattern, I. Schupp,
C. Chaouiya, D. Thieffry, A. Poustka, S. Wiemann, T. Beissbarth, D. Arlt, Modeling ERBB
receptor-regulated G1/S transition to find novel targets for de novo trastuzumab
resistance. BMC Syst. Biol. 3, 1 (2009).
