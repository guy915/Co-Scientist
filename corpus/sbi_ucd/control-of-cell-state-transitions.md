# Control of cell state transitions

Control of cell state transitions
https://doi.org/10.1038/s41586-022-05194-y
Received: 11 January 2021
Published online: 14 September 2022
Oleksii S. Rukhlenko1, Melinda Halasz1,2,5, Nora Rauch1,5, Vadim Zhernovkov1, Thomas Prince1,
Kieran Wynne1, Stephanie Maher1, Eugene Kashdan1, Kenneth MacLeod3, Neil O. Carragher3,
Walter Kolch1,2 & Boris N. Kholodenko1,2,4 ✉
Understanding cell state transitions and purposefully controlling them is a
longstanding challenge in biology. Here we present cell state transition assessment
and regulation (cSTAR), an approach for mapping cell states, modelling transitions
between them and predicting targeted interventions to convert cell fate decisions.
cSTAR uses omics data as input, classifies cell states, and develops a workflow that
transforms the input data into mechanistic models that identify a core signalling
network, which controls cell fate transitions by influencing whole-cell networks. By
integrating signalling and phenotypic data, cSTAR models how cells manoeuvre in
Waddington’s landscape1 and make decisions about which cell fate to adopt. Notably,
cSTAR devises interventions to control the movement of cells in Waddington’s
landscape. Testing cSTAR in a cellular model of differentiation and proliferation shows
a high correlation between quantitative predictions and experimental data. Applying
cSTAR to different types of perturbation and omics datasets, including single-cell
data, demonstrates its flexibility and scalability and provides new biological insights.
The ability of cSTAR to identify targeted perturbations that interconvert cell fates will
enable designer approaches for manipulating cellular development pathways and
mechanistically underpinned therapeutic interventions.
The concept of cell states is a useful lens through which to view and understand the organization of tissues and organisms, their development, and
responses to exogenous and endogenous changes. Although they were
initially based on phenotypical descriptions, global analysis methods
can now connect phenotypes with underlying molecular processes. These
methods characterize cell states with fine molecular resolution and open
the door to understanding how cell states can evolve and transition into
each other. In 1940, Waddington suggested that cells move through a
landscape of mountains and valleys as rolling marbles from one (meta)
stable state to another1. This now famous model appeals through its intuitive nature but leaves open why the marbles roll into certain valleys and
whether they can revert to an initial state. Recent efforts have applied
computational models to understand cell state transitions, generated
by stochastic molecular processes2,3, or have used lineage analysis to
characterize and infer cell state transitions4. These efforts have shown that
cell states are interconvertible and that this involves changes in dynamic
molecular processes, such as gene expression and signal transduction
networks. However, a critical gap is the lack of a mechanistic understanding of how cellular networks drive cell state transitions that would allow
us to purposefully manipulate and control cell states.
Here, we present cSTAR, which distinguishes cell states, quantifies their
determining elements, reconstructs a mechanistic network that controls
cell state transitions, and identifies pathway manipulations that allow us
to convert one cell state into another. cSTAR can use different types of
omics data, is scalable to different data sizes and is flexible in terms of
the granularity of the analyses. We validate cSTAR with experimental data
and identify precision interventions for controlling cell fate decisions.
As its input, cSTAR uses molecular data that contain enough information to distinguish different cell states. Initially, we use reverse phase
protein arrays (RPPA) phosphoproteomic data and subsequently
show that other omics data are suitable if they contain perturbations
and reflect different cell states. cSTAR integrates the following steps
(Fig. 1a). (1) Data clustering and construction of a hyperplane separating
the molecular features that characterize a cell state. We use support
vector machines (SVMs), as they exploit high dimensional space to
efficiently separate data by maximizing the distance between data
points belonging to different cell states. (2) Construction of a state
transition vector (STV) that, in the molecular dataspace, indicates a
path leading from the centroid of a point cloud of one cell state to the
centroid of another cell state. The STV identifies the components of a
core signalling network that governs cell state transitions. (3) A dynamic
phenotype descriptor (DPD) that quantifies cell phenotypic changes
in response to a perturbation by measuring whether the perturbation
moves the centroid towards or away from the separating hyperplane.
(4) A Bayesian formulation of modular response analysis5 (BMRA),
which reconstructs the topology, directions and strengths of causal
connections between nodes of the core network created from the components specified by the STV. The DPD is an additional node in this
core network representing the remainder of the global network upon
which the core network acts to drive cell fate transitions. (5) A resulting
mechanistic model based on ordinary differential equations (ODEs)
or stochastic differential equations (SDEs) that calculates the quality
Systems Biology Ireland, School of Medicine, University College Dublin, Dublin, Ireland. 2Conway Institute of Biomolecular and Biomedical Research, University College Dublin, Dublin, Ireland.
Cancer Research UK Edinburgh Centre, Institute of Genetics and Cancer, The University of Edinburgh, Edinburgh, UK. 4Department of Pharmacology, Yale University School of Medicine,
New Haven, USA. 5These authors contributed equally: Melinda Halasz, Nora Rauch. ✉e-mail: boris.kholodenko@ucd.ie
Nature | Vol 609 | 29 September 2022 | 975
Experimental validation of
perturbations predicted to
DPD (S) dynamics describes cell
manoeuvring in Waddington’s landscape
Sst.st.
st.st.
Fig. 1 | Overview of cSTAR and experimental system. a, The cSTAR approach
workflow. Clockwise from top left: (1) acquisition of omics datasets; (2) cell
state classification by clustering and SVM state separation; (3) the STV
indicates a path between centroids of cell state data point clouds; (4) a core
signalling network of high-ranked STV components is reconstructed by BMRA
and the DPD summarizes the cell-wide network; (5) a mechanistic model of the
core network and cell state transitions. x, the outputs of signalling modules;
S, the DPD module output; U, the potential cell state transitions interpreted as
cell manoeuvring in Waddington’s landscape. b, SH-SY5Y cells stably
expressing TrkA or TrkB receptors were stimulated with 100 ng ml−1 NGF or
BDNF, resulting in differentiation or proliferation, which were assessed 72 h
after stimulation.
and quantity of changes needed to convert one cell state to another.
This model quantifies the forces that move a cell along Waddington’s
landscape and provides direct instructions for experimental perturbations that can convert one cell state into another.
marked by neurite outgrowth, whereas TrkB drives proliferation7
(Fig. 1b). Differentiated TrkA-expressing cells (hereafter TrkA cells)
continue to proliferate, albeit more slowly than TrkB-expressing cells
(hereafter TrkB cells) (Extended Data Fig. 1). These diverse phenotypes
correlate with clinical outcomes in neuroblastoma. TrkA expression is
associated with good prognosis, whereas TrkB expression correlates
with aggressive tumour behaviour8. TrkA and TrkB activate similar
signalling pathways, and it is unclear how they cause these distinct
cell fate decisions7. We stimulated isogenic SH-SY5Y cell lines stably
expressing TrkA or TrkB receptors with their cognate ligands and used
a custom made RPPA with 115 validated antibodies (Supplementary
Table 1). We measured the activities of pathways involved in TrkA and
TrkB signalling7 in untreated cells and cells treated with NGF (TrkA
Experimental system and datasets
To develop cSTAR we chose an experimental system that features robust
cell fate decisions on the basis of subtle molecular differences. The
SH-SY5Y human neuroblastoma cell line is a well-established model for
neuronal differentiation, neurodegeneration and therapeutic target
discovery6. Expression of the TrkA or TrkB receptor tyrosine kinases
(RTKs) specifies different cell fates. TrkA stimulates differentiation
976 | Nature | Vol 609 | 29 September 2022
ligand) or BDNF (TrkB ligand) for 10 or 45 min (Extended Data Fig. 2 and
Supplementary Table 1). After normalization, we calculated the fold
changes in protein phosphorylation levels or abundances, producing
a data point for each protein. In addition, TrkA and TrkB activities were
measured by western blotting (Supplementary Table 2).
Separating distinct physiological states
Building a state transition vector
The second step builds a vector which connects the centroids of the
point clouds that represent the differentiation and proliferation
states. The components of this vector are the differences of fold
changes in the phosphorylation levels or abundances of each protein
between the centroids of the TrkA and TrkB point clouds. Dividing
this centroid-connecting vector by its length gives the STV (Fig. 2a).
Hence, the STV is a unit length vector that characterizes each molecule’s
contribution to the difference between cell states and determines the
direction of cell state transitions (here from differentiation to proliferation). The absolute values of these contributions directly rank individual proteins according to their importance in switching cell states.
Thus, we can identify the components of a core signalling network that
controls a larger network of cellular responses (Extended Data Fig. 3b).
Including more components increases the granularity but also the
number of perturbations needed for subsequent network reconstruction. Hence, the cut-off for components to include depends on the data
and desired granularity. Importantly, cSTAR robustly separates cell
states and determines core network components for different types
of noisy omics data (Supplementary Information and Supplementary
Tables 14 and 15).
In the TrkA/B system, the highest ranked proteins are RTKs, cytosolic
kinases (AKT and ERK), and the ribosomal S6 protein that is phosphorylated by RSK and S6K, which themselves are targets of ERK and AKT
signalling pathways (Supplementary Table 3). We also included the
JNK stress kinase, because we previously showed that JNK activation
dynamics in neuroblastoma predicts clinical response15. The ERK and
AKT pathways are main downstream effectors of TrkA and TrkB receptor
signalling16. This indicates that the differential integration of ERK and
AKT activities may be key to determining different cell fates in these
The individual data points for TrkA and TrkB cells can be perceived as
points in the molecular dataspace of 115 dimensions (corresponding to
the measurement of 115 protein features) that describe the cell states.
However, phenotypically SH-SY5Y cells exhibit only three different
states, a common ‘ground’ state with no growth factor stimulation,
a differentiation state following stimulation of TrkA cells with NGF,
and a proliferation state following stimulation of TrkB cells with
BDNF. This suggests that distinct states might be determined by
a handful of patterns hidden in the molecular data. Consequently,
transitions between different cell states can be described by a few
critical parameters, termed order parameters for complex systems9,10.
Whereas in physics the order parameters are found by modelling state
transitions11,12, no mechanistic models can determine the dynamic
changes in whole-cell signalling patterns distinguishing cell states13.
To address this gap we developed the STV, which informs us how
signalling data patterns of a given cell state must change to allow one
cell state transitioning into another.
The first step distinguishes and separates distinct cell states in protein phosphorylation and/or expression dataspace using machine
learning methods to cluster and classify signalling patterns (Extended
Data Fig. 3a and Methods). Using a SVM14, we built a hyperplane that
maximizes the separation between distinct phenotypic states in the
multidimensional RPPA dataspace. Principal component analysis
(PCA) visualizes this hyperplane that separates TrkA and TrkB cell
states (Fig. 2a).
Fig. 2 | Separation of proliferation and differentiation signalling patterns
and projection of the STV into the PCA space. a, Following growth factor
stimulation, TrkA (blue triangles) and TrkB (red triangle) cell states were
separated by SVM. Large triangles are point cloud centroids. Projections of
data points, the separating hyperplane (grey) and the STV (dark red) are shown
in the space of the first three principal components. b, Decomposition of a
perturbation vector (solid black line) into a vector collinear with the STV and a
vector perpendicular to the STV (dotted lines). TrkB cells were treated with
BDNF and the p90RSK inhibitor BI-D1870. Green triangles, TrkB data points
after perturbation. RSKi, RSK inhibitor.
cells. Next, we tested whether this knowledge can be used to design
interventions that switch cell fates.
The dynamic phenotype descriptor
A logical strategy would be to perturb the STV-defined core components experimentally and test whether these perturbations can change
the cell states. The STV contains information about the contributions
of all signalling network components measured by RPPA. Removing
the core components from the STV renders it a representation of
Nature | Vol 609 | 29 September 2022 | 977
the overall signalling network downstream of the core components.
It also eliminates potentially confounding effects resulting from the
perturbations indirectly affecting the activity of upstream network
components through feedback loops. For instance, ERK inhibition
abolishes negative feedbacks to TrkA- or TrkB-mediated RAS activation, which would register as a change in ERK signalling. However, this
is inconsequential for ERK downstream signalling, as ERK is blocked by
the inhibitor. Thus, this reduced STV can estimate the network effects
and biological outcomes of experimental perturbations.
For each perturbation, we determine a perturbation vector that connects the centroids of the point clouds before and after the perturbation. This vector changes the phenotype when it pushes the centroid
of the point cloud across the hyperplane that separates different cell
states, stabilizes a cell state when moving the centroid away from the
separating hyperplane, or has no effect when it moves (nearly) parallel
to this hyperplane (Fig. 2b). The perturbation outcomes are defined
by the DPD. Its absolute value (|S|) quantifies the distance from the
separating hyperplane to a point cloud centroid, and its sign indicates
the direction relative to the STV. Here, S is positive if the point cloud
centroid is on the same side of the separating plane as the proliferation cloud, and negative at the differentiation side. Any perturbation
that drives the cellular response from differentiation to proliferation
increases S and can change its sign to positive, whereas moving from
proliferation to differentiation decreases S and can make it negative.
For experimental testing we targeted core components with small
molecule inhibitors. The effects of the inhibitors on the DPD correlated
well with their experimentally observed phenotypical effects (Supplementary Table 4). As predicted, Trk and p70S6K inhibition changed
the DPD from positive to negative values and strongly increased differentiation of TrkB cells. The RSK inhibitor decreased differentiation
in TrkA cells and weakly increased differentiation in TrkB cells. These
correlations show that the DPD accurately predicts which perturbations
can move cells into the differentiation state. However, the DPD changes
do not necessarily correlate with the proliferation rate (Extended Data
Fig. 1), as some inhibitors can lead to cell cycle arrest and apoptosis,
and because proliferation and differentiation may not be mutually
exclusive in neuroblastoma.
In Waddington’s terms, the DPD predicts how we can steer a marble into
a valley without revealing why that steering works. The only means to
both precisely predict and explain the outcome of these experimental
manipulations, which manoeuvre a cell through a Waddington landscape, is to explicitly model the nonlinear signalling dynamics that
determine cell state transitions. This mechanistic model needs to comprise (1) a faithfully reconstructed topology of the core network components deduced from the STV with interaction signs and strengths;
and (2) a network node, which summarizes the remainder of the global
network controlled by the core network and links signalling changes
to phenotypic changes; this node output is the DPD described above.
Reconstructing a mechanistic core network
We previously developed a physics-based method—modular response
analysis (MRA)—to exactly reconstruct and quantify causal, local connections between network nodes, including feedback loops, from
perturbation data5,17–19. Each node is a reaction module, which can be
a single protein or gene, a pathway, or any object defined in terms of
input–output relations. For instance, in our core network the ERK module is a three-tier pathway that includes all RAF, MEK and ERK isoforms.
The network topology is quantified by connection coefficients—also
known as local responses—or connection strengths20. They cannot
be measured directly, as perturbations propagate. MRA infers network connections from systems-level responses at steady states or at
time instances when a signalling response approaches its maximum
978 | Nature | Vol 609 | 29 September 2022
or minimum, because in both cases the time derivative is zero21,22.
Whereas the overall topology does not markedly change between early
peak and steady-state responses, the connection strengths are highly
dynamic22,23. The original MRA requires as many perturbations as there
are network nodes and is sensitive to noise in the data24. To overcome
these limitations, we developed a Bayesian MRA (BMRA) that requires
fewer perturbations, is tolerant to noise, and allows incorporation of
existing knowledge as a prior network to improve inference precision25.
Even when this information is inaccurate for half of the network edges,
BMRA recovers a nearly perfect network topology26.
Mapping the core components specified by the STV onto known signalling pathways, we obtained a prior topology of a core network, which
was identical for the TrkA- and TrkB-expressing cells (Extended Data
Fig. 4a). To reconstruct the posterior network, we used drug perturbations (Supplementary Table 4) and measured 10- and 45-min timepoints
in TrkA and TrkB cells stimulated with NGF or BDNF. Activation of TrkA,
TrkB, EGFR, ERBB2, AKT and ERK peaked around 10 min and attained
steady-state levels at around 45 min (Extended Data Fig. 4b). BMRA network reconstruction showed that connection strengths were different
between the peak and steady-state levels (Supplementary Table 5), but
a consensus network can readily be derived for each cell line (Extended
Data Fig. 5). These signalling networks feature major differences—for
instance, the activation of the ERBB module by strong positive feedback
from RSK to ERBB in the TrkB network. The ERBB→ERK→RSK→ERBB
loop acts as an autocatalytic amplifier of the ERBB module. The strong
activation of p70S6K by ERK in TrkB cells is subverted into a strong
inhibition of ERK by p70S6K in TrkA cells. Overall, the TrkA network
has more inhibitory connections, whereas the TrkB network comprises
more stimulatory interactions and positive feedback loops.
The DPD describes the phenotype as summary of molecular features
of all other components of the cell-wide network (proteins, mRNAs, and
so on), which are outside of the core network. Using BMRA to include
the DPD as a node in our core network enabled us to systematically
examine the influence of all core network pathways on cell state transitions alone and in combination. We determined connections to the
DPD, as a network node or module, for each core pathway (Fig. 3a,b).
As the DPD links the network to cell fate decisions, a connection to
the DPD node indicates how a signalling change influences the phenotype. A positive connection means that the cell is pushed towards
proliferation, whereas a negative coefficient indicates a push to differentiation. Because the changes in the DPD are downstream of the
core network and therefore require more time, we assessed the DPD
responses after 45 min of growth factor stimulation. Measuring fold
changes in the outputs of signalling pathways and the DPD module,
we obtained the global, systems-level responses to perturbations and
inferred the influence of each signalling pathway on the DPD and cell
phenotype (Fig. 3c,d and Supplementary Table 5). In this analysis, the
ERK and S6K modules have positive connection coefficients to the
DPD promoting cell proliferation in both TrkA and TrkB networks.
However, the influence of the RSK and JNK modules on cell phenotypes
is drastically different. In the TrkA network, RSK and JNK suppress
proliferation and induce differentiation, whereas in the TrkB network
these pathways do not influence the DPD and the phenotype. Thus,
ERK-induced activation of JNK and RSK modules in TrkB-expressing
cells does not suppress proliferation of these cells.
Predicting signalling dynamics
The BMRA-quantified core network topologies and their inferred influences on the DPD allow us to directly derive mechanistic models for
TrkA and TrkB cells, which predict both the dynamics of core pathway
outputs and associated changes in cellular phenotypes (see Methods for
a detailed model description). The TrkA and TrkB core networks contain
the same nodes but differ in connections and their strengths (Extended
Data Fig. 5). The model predicts that these differences cause distinct
signalling patterns, which is supported by experimental data (Fig. 4a,b).
Fig. 3 | Output of the DPD module. a,b, BMRA-reconstructed topologies of the
core signalling networks and connections to the DPD module in TrkA (a) and
TrkB (b) cell lines. Arrowheads indicate activation, blunt ends show inhibition
and line widths indicate the absolute values of interaction strengths. Edges
specific to TrkA and TrkB are shown in blue and red, respectively. c,d, Blue, red
and green triangles show PCA-compressed 45 min data points for TrkA cells
treated with NGF, TrkB cells treated with BDNF (c,d), and a combination of
BDNF and RSK inhibitor (RSKi; d). The distances of TrkB centroids to the
separating hyperplane (grey) before and after perturbation are shown by black
lines. The DPD module output is the distance of a centroid from the separation
hyperplane determined along or opposite the STV direction taken with the plus
sign if the centroid is located on the right side from the separation hyperplane
(proliferation), and with the minus sign if the centroid is at the left side
(differentiation).
On the basis of the inferred activation of ERBB by TrkB and amplifying
autocatalytic loops, ERBB→ERK→ERBB and ERBB→ERK→RSK→ERBB,
the model predicts higher and sustained levels of active RTKs, ERK,
AKT, S6K and RSK in TrkB cells compared with TrkA cells (Fig. 4a,b).
The model also correctly predicts the responses of core network pathways of TrkA and TrkB cells to NGF and BDNF stimulation and their
responses to different drug perturbations (Extended Data Figs. 6–8).
For example, S6K inhibition increases ERK and AKT activation owing
to downregulation of S6K-induced negative feedback loops, which
are stronger in TrkA than in TrkB cells (Extended Data Fig. 6a). In both
TrkA and TrkB cells, inhibition of Trk receptors suppresses signalling
by all core pathways confirming that they are driven by Trk receptors
(Extended Data Fig. 6b). Even a moderate inhibition of ERK substantially
downregulates phosphorylation of ERBB, AKT and their downstream
effectors in TrkB cells, whereas these effects are minute in TrkA cells
(Extended Data Fig. 7a). This is explained by the positive feedback from
the ERK module to ERBB via RSK in TrkB cells (Fig. 3a,b). Also, AKT
inhibition suppresses core pathways in TrkB more efficiently than in
TrkA cells owing to positive feedback from AKT to ERBB in TrkB cells
(Extended Data Fig. 7b). Thus, self-amplifying positive feedback loops
from ERK and AKT to ERBB receptors drive the sustained proliferation
of TrkB cells.
changes. It enables us to map how a cell manoeuvres in Waddington’s
landscape and how external perturbations influence a cell’s journey
in this landscape. In the molecular dataspace, centroids of data point
clouds present population-averaged cell states and phenotypes. Before
ligand stimulations or drug perturbations, cells reside in (meta)stable
states. Following a perturbation, centroid movements are governed by
two forces: a signalling driving force emerging from the changes in core
network activities, and a restoring force that pushes the centroid back
to its original (meta)stable state (Extended Data Fig. 9). Only pathways
with non-zero connections to the DPD node generate a driving force
that affects the DPD (Fig. 3 and Supplementary Table 5). The restoring
force is a gradient force that increases in the vicinity of the stable steady
state but then decreases to zero at the cell state separation surface
(Extended Data Fig. 9a). A combination of signalling and restoring
forces determines the shape of Waddington’s landscape (Extended Data
Fig. 9c). Whereas internal or external noise can stochastically induce
the crossing of landscape peaks and subsequent cell fate changes, the
signalling force directs cell fate decisions in a controlled way. Summarizing, cSTAR can calculate the driving signalling force and predict the
corresponding interventions, enabling us to steer cell fate decisions
in Waddington’s landscape (Extended Data Fig. 9).
Our simulations show that ligand stimulation moves TrkA and
TrkB cells from the ground state through Waddington’s landscape
along different trajectories towards differentiation or proliferation
(Fig. 4c–e). These predictions are supported by experimental data
(Fig. 4f). Calculating the DPD trajectories after inhibitor perturbations (Fig. 5a–l) showed that TrkB or S6K inhibition promotes
Cell manoeuvring in Waddington’s landscape
cSTAR integrates cell state transitions into a mechanistic model, following both the output kinetics of the core network and cellular phenotype
Nature | Vol 609 | 29 September 2022 | 979
Fig. 4 | Computing signalling patterns and modelling cell manoeuvring in
Waddington’s landscape using the DPD. a,b, Experimental data on AKT, ERK,
JNK, S6K, RSK and ERBB (a) and Trk (b) are imposed on model-predicted time
courses for NGF-stimulated TrkA (blue) and BDNF-stimulated TrkB (red) cells.
c,d, Waddington’s landscape evolution predicted by the model for TrkA (c) and
TrkB (d) cells following ligand stimulation. The Waddington landscape
potential W is plotted against the DPD output (S) and time (0 to 45 min). At t = 0,
cells reside in a stable ground state (s0). Following stimulation by growth
factors, TrkA and TrkB cells manoeuvre to differentiation (c) and proliferation
(d) states (model-predicted trajectories are shown by black lines).
e, Experimentally measured (dots) and model-predicted (solid lines) DPD
responses (S) to ligand stimulation in TrkA and TrkB cells. f, Percentages of
differentiated TrkA and TrkB cells stimulated with growth factors for 72 h
compared with unstimulated controls. The decrease in differentiation of
BNDF-stimulated TrkB cells reflects the increase in proliferation. Data are
mean ± s.e.m. for n = 3 biologically independent experiments. The data are
shown in Supplementary Table 13. *P < 0.05, unpaired one-sided t-test.
differentiation, whereas RSK inhibition in TrkA cells interferes with
differentiation. All simulations, except DPD responses to MEK inhibition in TrkB cells, were corroborated by quantifying cell differentiation by imaging. MEK inhibition features an abrupt transition
between differentiation and proliferation. Thus, a small inaccuracy
in the calculated DPD response to MEK inhibitor might have led to
an incorrect phenotypic prediction.
Nevertheless, the model captures both direct and network-mediated
effects of drugs on cellular phenotypes. It predicted that ramping up
AKT activity in TrkA cells converts differentiation into proliferation
(Fig. 5m). This was experimentally confirmed by transfecting TrkA cells
with constitutively active myristoylated AKT (Fig. 5n,o). Simulations
predicted that inhibition of TrkB, AKT, S6K or RSK converts TrkB signalling to differentiation (Fig. 5a,b,g,i), as supported by experimental
980 | Nature | Vol 609 | 29 September 2022
Fig. 5 | Model-predicted DPD values and quantification of phenotypic
responses of TrkA and TrkB cells to different inhibitors. a–c,g–i, Modelpredicted time courses (lines) and experimentally measured (dots) DPD
responses of TrkA (blue) and TrkB (red) cells to treatment with inhibitors of
Trk (a), AKT (b), JNK (c), S6K (g), MEK (h) and RSK (i). (Inhibitor concentrations
are provided in Extended Data Figs. 6–8). d–f,j–l, Percentages of differentiated
TrkA and TrkB cells quantified using live-cell imaging. Cells were treated
with inhibitors of Trk (d), AKT (e) and JNK (f), S6K ( j), MEK (k) and RSK (l).
m, Simulated DPD time course of the response of NGF-stimulated TrkA cells
to a tenfold increase in AKT activity predicts persistent proliferation (solid
line), whereas simulated DPD time course of NGF-stimulated control cells
predicts differentiation (dashed line). n,o, Live-cell images of TrkA cells
transfected with myristoylated AKT with (o) or without (n) NGF stimulation for
72 h. Representative images of three biological replicates are shown. Images in
(n,o) confirm the predictions of the model (m). Data are mean ± s.e.m. of n = 3
biologically independent experiments. *P < 0.05, unpaired one-sided t-test.
observations (Fig. 5d,e,j,l). Representative images of TrkA and TrkB cells
for all inhibitor perturbations are shown in Extended Data Figs. 10 and 11.
Using the model, we calculated cell state responses for drug combinations. The efficiency of a two-drug combination was assessed
by the DPD response across a two-dimensional plane of drug doses,
similar as pathway responses are assessed in pharmacology and therapeutics27. The lines of constant DPD are termed Loewe isoboles. For
non-interacting drugs, Loewe isoboles are straight lines and for synergizing inhibitors they are concave, whereas convex isoboles indicate
antagonism. Predictive simulations suggested that combining ERBB
Nature | Vol 609 | 29 September 2022 | 981
0.
2.
5 2.5 1.25 Gefitinib (μM)
− 0.05 0.1 Trametinib (μM)
Fig. 6 | Inhibition of ERBB and ERK modules synergistically induces
differentiation of TrkB-expressing cells. a, Model-predicted DPD
responses of TrkB cells to ERBB and MEK inhibitors applied separately and in
combinations are shown in a 2D plane of the drug doses at 45 min following
BDNF stimulation. Constant DPD lines, Loewe isoboles, show the borders
between the differently coloured areas. Concave isoboles demonstrate
synergy. Kd, dissociation constant. b, Percentages of differentiated TrkB cells
corroborate the model-predicted synergy between ERBB and MEK inhibitors in
inducing TrkB cell differentiation. Data are mean ± s.e.m. of n = 3 biologically
independent experiments. *P < 0.05, unpaired one-sided t-test. c, Responses of
FAK phosphorylation (cell differentiation marker28) to gefitinib (2.5 and 5 μM),
trametinib (0.1 and 0.2 μM) and combined (2.5 μM gefitinib and 0.05 μM
trametinib, and 1.25 gefitinib and 0.1 μM trametinib) at 72 h. Gel source data are
shown in Supplementary Fig. 1. Representative blot of three biological
replicates is shown. d, ERBB and MEK inhibitors synergistically induce Trk
B cell differentiation. The DPD values calculated are calculated using
phosphoproteomics data from mass spectrometry for TrkA and TrkB cells
treated with trametinib (0.5 μM), gefitinib (2.5 μM) and combined (0.25 μM
trametinib and 1.25 μM gefitinib) after 45 min of stimulation. Data are
mean ± s.e.m. of n = 3 biologically independent samples examined over 2
independent experiments. The dashed, red bar shows the expected DPD value
for the Bliss independence of a combination treatment of TrkB cells with
trametinib and gefitinib.
and MEK inhibition synergizes to change the DPD and induce differentiation in TrkB cells (Fig. 6a) without affecting cell states in TrkA cells
(Extended Data Fig. 12a). Experimentally, combination treatment with
gefitinib (ERBB inhibitor) and trametinib (MEK inhibitor) markedly
induced TrkB cell differentiation, despite individual treatments at
double doses being ineffective (Fig. 6b and Extended Data Fig. 13). This
combination of inhibitors synergistically induced FAK phosphorylation (Fig. 6c), which is a well-established differentiation marker28. As
predicted by the model, TrkA cell states were not affected (Extended
Data Fig. 12b,c).
differentiation without affecting the TrkA cell phenotype (Fig. 6d and
Supplementary Information), which was experimentally validated.
Thus, cSTAR produces robust and reproducible results even when the
input data differ vastly in scale and bias.
cSTAR flexibility and scalability
Next, we tested cSTAR’s performance with data of different types and
scales. Using the same conditions as in the RPPA dataset, we acquired
quantitative phosphoproteomics mass spectrometry datasets for TrkA
and TrkB cells (Supplementary Table 6). Calculating the STV and DPD
changes for cell-wide signalling pattern of around 5,000 phosphorylation sites (Supplementary Tables 7 and 8) resulted in similar core
network components (Extended Data Fig. 15) and a key prediction
of synergy between ERBB and MEK inhibitors in inducing TrkB cell
982 | Nature | Vol 609 | 29 September 2022
RAF inhibitor-resistant melanoma
To map mechanisms of drug resistance, we applied cSTAR to an extensive RPPA dataset of 238 proteins measured under 89 perturbations of
RAF inhibitor-resistant SKMEL-133 cells29. As different phenotypic states
we selected proliferation (untreated cells) and apoptosis induced by
combination treatment with MEK plus PI3K, AKT or mTOR inhibitors
(Extended Data Fig. 16). The STV ranked the MEK–ERK, AKT, mTOR–
S6K, SRC, CDK4/6, PKC and IRS modules as the components of a core
network that controlled these states (Supplementary Table 9 and
Methods). Next, we applied BMRA to single-drug perturbation data,
inferring the core network circuitry and its connections to the DPD
module (Fig. 7a and Supplementary Table 10). The reconstructed network included known signalling routes, including the IRS-mediated
activation of the ERK and AKT modules, AKT activation of mTOR,
CDK4/6 activation by ERK and mTOR, and negative feedback from
MYC is added to a core network
Fig. 7 | cSTAR analysis of RAF inhibitor-resistant SKMEL-133 cells.
a,b, Inferred topologies of a core signalling network that lacks (a) or includes
(b) MYC. Arrowheads indicate activation, blunt ends show inhibition and line
widths indicate the absolute values of interaction strengths. c,d, Modelpredicted steady-state DPD responses to MYC and MEK inhibitors (c) and
insulin and IGF1R (insulin/IGF1R) inhibitors with PI3K and AKT (PI3K/AKT)
inhibitors (d) are shown by Loewe isoboles. Synergy is more pronounced in d.
e–g, Model-predicted SKMEL-133 cell manoeuvring (black lines) in
Waddington’s landscape following inhibitor treatments. The Waddington
landscape potential (W) plotted against the DPD (S) and time. At t = 0, cells
reside in a highly proliferating state (high positive values of DPD). PI3K/AKT
and insulin/IGF1R inhibitors were added at t = 30 min at the 3Kd and 4Kd doses.
e,f, When the inhibitors were applied separately, the decreasing DPD values
remain in the proliferation region (positive DPD values). g, Treated with a
combination of inhibitors in twice lower doses (1.5Kd for PI3K/AKT inhibition
and 2Kd for insulin/IGF1 inhibition), the cells manoeuvre to the apoptotic state
manifested by negative DPD values. A threshold-like switch to negative DPD
(black arrow) is a switch from proliferation to apoptosis.
mTOR to IRS26. However, BMRA also uncovered activating connections from PKC to AKT, mTOR, SRC and CDK4/6, a negative connection
from PKC to IRS, and CDK4/6-induced positive and negative feedback
loops to the AKT and SRC modules (Fig. 7a). On the basis of their direct
connections to the DPD, mTOR and PKC drive proliferation, whereas
the phenotypical effect of other nodes is indirect. For instance, ERK
activates mTOR through SRC and CDK4/6 to stimulate proliferation,
partially counteracted by CDK4/6-mediated feedback inhibition of ERK.
Although SRC directly inhibits the DPD, it stimulates proliferation on
the systems level by activating mTOR.
MYC inhibition synergizes with BRAF or MEK inhibition to suppress
proliferation and induce apoptosis29. Thus, we added MYC to our core
network and re-inferred network connections. This extended network
was very similar to the original network except that CDK inhibited SRC
not directly, but via MYC (Fig. 7b and Supplementary Table 10). The
equivalence of these networks illustrates that BMRA allows zooming
in or out on the inferred connections by adding nodes of interest or
deleting unimportant nodes5.
Informed by the BMRA network reconstruction, we built a nonlinear dynamical model of SKMEL-133 cell signalling and phenotypic
Nature | Vol 609 | 29 September 2022 | 983
behaviour. Because cSTAR enables building models of different granularities, we tested the effects of including or omitting MYC. Adding MYC
only changed parameters of modules directly interacting with MYC
without changing any model predictions. Thus, the ODE description of
each network module can be extended to include additional mechanistic knowledge (see Methods for successive steps of model refinement).
The model predicted that an mTOR inhibitor was the most efficient
single drug to induce apoptosis in SKMEL-133 cells, whereas PI3K–AKT
inhibition was less effective (Extended Data Fig. 17a). This differential sensitivity is explained by the double-positive feedback between
CDK4/6 and mTOR (Fig. 7a,b), which greatly increases the stimulation
of proliferation by mTOR and CDK4/6. PKC inhibition also markedly
reduced proliferation, as PKC directly influences the DPD, whereas inhibition of other nodes, including MEK–ERK signalling, was less effective.
The cSTAR model recapitulated the results by Korkut et al.29, including the synergy between MEK and MYC inhibitors (Fig. 7c). Furthermore, the model predicted that combining inhibition of insulin–IGF1R
and PI3K–AKT enhances synergy (see Fig. 7d). This result is supported
by calculating the Talalay–Chou combination index (CI) (Methods) and
simulating SKMEL-133 cell manoeuvring in Waddington’s landscape
following inhibitor treatments. Inhibitors of PI3K–AKT or insulin–IGF1R
given separately do not switch the DPD to the negative, apoptotic region
(Fig. 7e,f). However, given in combination at half their respective doses,
they shift the DPD to apoptosis (Fig. 7g). We also found that combining
MEK–ERK and PI3K–AKT inhibitors was highly synergistic30 (Extended
Data Fig. 17b). This example shows that cSTAR is a powerful tool to
analyse drug responses and predict synergistic combinations.
Epithelial–mesenchymal transition
cSTAR quantifies phenotypic changes via the DPD, opening the possibility of integrating different omics datasets by comparing the normalized
DPD changes following perturbations. Testing this, we applied cSTAR
to two datasets that analysed the suppression of epithelial–mesenchymal transition (EMT) by kinase inhibitors. One study used single-cell
RNA sequencing (scRNA-seq) of four cancer cell lines stimulated with
three different ligands, TGFβ, EGF and TNF31. The other used single-cell
resolution mass cytometry of phosphoproteomic responses in Py2T
breast cancer cells stimulated with TGFβ32.
The results of the cSTAR analysis (Extended Data Fig. 18 and Supplementary Information) correspond well to the original phenomenological observations and conclusions drawn in the original
studies31,32 (Extended Data Fig. 19 and Supplementary Table 11). They
show that cSTAR correctly captures the relationships between phenotypical and underlying molecular states. Moreover, cSTAR adds new
insights. Of note, the DPD analysis of scRNA-seq data demonstrated
that at single-cell resolution the observed partial EMT states comprise
a continuum of intermediate states between fully epithelial and fully
mesenchymal states (Extended Data Figs. 20 and 21). To underpin these
states with mechanistic interpretations, which was previously not possible, we applied BMRA to reconstruct the twelve signalling networks
(four cell lines and three ligands), underlying these phenotypes in each
cell type under each condition. These networks show how differential
network topologies and connection strengths cause cell-type- and
stimulation-specific responses (Supplementary Table 12). These reconstructions of different network topologies will help designing the most
informative experiments to disentangle the relationships between
these multiple EMT states.
A major challenge for modern biologists is the interpretation of the
vast amount of different data types that are generated. There is a need
for tools that can progress accurate classifications into an actionable
and causal analysis of cell states, enabling us to control transitions
984 | Nature | Vol 609 | 29 September 2022
between them. cSTAR bridges the current gap between classification
and mechanistic understanding of cell states and produces actionable
predictions. This is enabled by three key features.
First, the SVM accurately determines the maximal margin hyperplane14 that separates different cell states in the dataspace, whereas
the STV identifies the molecular network components that control
cell state transitions. Generally, several sequential or alternative cell
transitions between several state states are possible. The STV can be
built between any of two selected states, pointing to the overall change
in the molecular features required for the transition between these two
states. However, biologically not all transitions are possible, and this
is an exciting topic for further cSTAR applications.
Second, the DPD enables us to connect phenotypical to molecular changes and the movement in Waddington’s landscape. The idea
behind the DPD is based on two pillars: (1) non-equilibrium thermodynamics suggests that different physicochemical systems can behave
similarly in the vicinity of a critical state, and the system dynamics
can be parametrized by the distance to the critical point9, and (2) our
results suggest that not only is the binary SVM classification informative, but the distance to the separating hyperplane also determines
when the variety of small quantitative changes in the signalling patterns can result in the qualitative change in the cell state. This distance is determined by the absolute DPD value as a key parameter that
describes the dynamics of cell state transitions. The DPD connects
signalling dynamics to the intuitively attractive picture of Waddington’s landscape. Despite many attempts to quantify cell movements
in Waddington’s landscape, cell state transitions were never linked to
external cues and downstream signalling networks that drive these
transitions3. Integrating biochemistry and physics, cSTAR determines
how multiple pathway activities dynamically control cell state transitions in an evolving Waddington’s landscape, making cell fate decisions
tractable and manipulatable.
Third, the BRMA-guided network reconstruction enables a full
mechanistic understanding and dynamic response analysis of the biological system. Notably, core network circuitries differ substantially
in different cell lines, isogenic cells and even within the same cell line
stimulated with different ligands. The inferred networks and resulting
mechanistic models are used for identifying mechanisms of biological
decision making and designing targeted interventions that eliminate
an undesired phenotype—for example, drug resistance.
Our application examples show that cSTAR can utilize and integrate
diverse omics data including targeted and unbiased data of different
scales as well as single-cell data. This universality and scalability distinguishes cSTAR from other approaches that are more specialized
in terms of input data, such as approaches relying on mRNA velocity input33,34. In summary, cSTAR offers a cell-specific, mechanistic
approach to describe, understand and purposefully manipulate cell
fate decisions. As such it has numerous applications across biology that
go beyond the use for interconverting proliferation and differentiation
shown here as examples.
Any methods, additional references, Nature Research reporting summaries, source data, extended data, supplementary information, acknowledgements, peer review information; details of author contributions
and competing interests; and statements of data and code availability
are available at https://doi.org/10.1038/s41586-022-05194-y.
1.
2.
3.
4.
Waddington, C. H. Organisers and Genes (Univ. Press, 1940).
Brackston, R. D., Lakatos, E. & Stumpf, M. P. H. Transition state characteristics during cell
differentiation. PLoS Comput. Biol. 14, e1006405 (2018).
Wang, J., Zhang, K., Xu, L. & Wang, E. Quantifying the Waddington landscape and
biological paths for development and differentiation. Proc. Natl Acad. Sci. USA 108,
8257–8262 (2011).
Hormoz, S. et al. Inferring cell-state transition dynamics from lineage trees and endpoint
single-cell measurements. Cell Syst. 3, 419–433.e418 (2016).
5.
Kholodenko, B. N. et al. Untangling the wires: a strategy to trace functional interactions in
signaling and gene networks. Proc. Natl Acad. Sci. USA 99, 12841 (2002).
6.
Xicoy, H., Wieringa, B. & Martens, G. J. The SH-SY5Y cell line in Parkinson's disease
research: a systematic review. Mol. Neurodegener. 12, 10 (2017).
7.
Schramm, A. et al. Biological effects of TrkA and TrkB receptor signaling in neuroblastoma.
Cancer Lett. 228, 143–153 (2005).
8.
Aygun, N. Biological and genetic features of neuroblastoma and their clinical importance.
Curr. Pediatr. Rev. 14, 73–90 (2018).
9.
Haken, H. Synergetics: Introduction and Advanced Topics (Springer, 2004).
10. Rickles, D., Hawe, P. & Shiell, A. A simple guide to chaos and complexity. J. Epidemiol.
Commun. Health 61, 933 (2007).
11. Sethna, J. P. Statistical Mechanics: Entropy, Order Parameters, and Complexity (Oxford
Univ. Press, 2006).
12. Aron, C. & Chamon, C. Landau theory for non-equilibrium steady states. SciPost Phys. 8,
074 (2020).
13. Needham, E. J., Parker, B. L., Burykin, T., James, D. E. & Humphrey, S. J. Illuminating the
dark phosphoproteome. Sci. Signal. 12, eaau8645 (2019).
14. Cortes, C. & Vapnik, V. Support-vector networks. Mach. Learn. 20, 273–297 (1995).
15. Fey, D. et al. Signaling pathway models as biomarkers: patient-specific simulations
of JNK activity predict the survival of neuroblastoma patients. Sci. Signal. 8, ra130
(2015).
16. Vaishnavi, A., Le, A. T. & Doebele, R. C. TRKing down an old oncogene in a new era of
targeted therapy. Cancer Discov. 5, 25 (2015).
17. de la Fuente, A., Brazhnik, P. & Mendes, P. Linking the genes: inferring quantitative gene
networks from microarray data. Trends Genet. 18, 395–398 (2002).
18. Yalamanchili, N. et al. Quantifying gene network connectivity in silico: scalability and
accuracy of a modular approach. Syst. Biol. 153, 236–246 (2006).
19. Bastiaens, P. et al. Silence on the relevant literature and errors in implementation. Nat.
Biotechnol. 33, 336–339 (2015).
20. Kholodenko, B. N., Hoek, J. B., Westerhoff, H. V. & Brown, G. C. Quantification of
information transfer via cellular signal transduction pathways. FEBS Lett. 414, 430–434
(1997).
21. Kholodenko, B. N. & Kholodov, L. E. Individualization and optimization of dosings of
pharmacological preparations; principle of maximum in the analysis of pharmacological
response. Pharm. Chem. J. 14, 287–291 (1980).
22. Santos, S. D., Verveer, P. J. & Bastiaens, P. I. Growth factor-induced MAPK network topology
shapes Erk response determining PC-12 cell fate. Nat. Cell Biol. 9, 324–330 (2007).
23. Sontag, E., Kiyatkin, A. & Kholodenko, B. N. Inferring dynamic architecture of cellular
networks using time series of gene expression, protein and metabolite data.
Bioinformatics 20, 1877–1886 (2004).
24. Thomaseth, C. et al. Impact of measurement noise, experimental design, and estimation
methods on modular response analysis based network reconstruction. Sci. Rep. 8, 16217
(2018).
25. Santra, T., Rukhlenko, O., Zhernovkov, V. & Kholodenko, B. N. Reconstructing static and
dynamic models of signaling pathways using modular response analysis. Curr. Opin.
Syst. Biol. 9, 11–21 (2018).
26. Halasz, M., Kholodenko, B. N., Kolch, W. & Santra, T. Integrating network reconstruction
with mechanistic modeling to predict cancer therapies. Sci. Signal. 9, ra114 (2016).
27. Greco, W. R., Bravo, G. & Parsons, J. C. The search for synergy: a critical review from a
response surface perspective. Pharm. Rev. 47, 331 (1995).
28. Dwane, S., Durack, E. & Kiely, P. A. Optimising parameters for the differentiation of
SH-SY5Y cells to study cell adhesion and cell migration. BMC Res. Notes 6, 366 (2013).
29. Korkut, A. et al. Perturbation biology nominates upstream-downstream drug
combinations in RAF inhibitor resistant melanoma cells. eLife 4, e04640 (2015).
30. Xing, F. et al. Concurrent loss of the PTEN and RB1 tumor suppressors attenuates RAF
dependence in melanomas harboring (V600E)BRAF. Oncogene 31, 446–457 (2012).
31. Cook, D. P. & Vanderhyden, B. C. Context specificity of the EMT transcriptional response.
Nat. Commun. 11, 2142 (2020).
32. Chen, W. S. et al. Uncovering axes of variation among single-cell cancer specimens. Nat.
Methods 17, 302–310 (2020).
33. Qiu, X. et al. Mapping transcriptomic vector fields of single cells. Cell 185, 690–711.e645
(2022).
34. Lange, M. et al. CellRank for directed single-cell fate mapping. Nat. Methods 19, 159–170
(2022).
Publisher’s note Springer Nature remains neutral with regard to jurisdictional claims in
published maps and institutional affiliations.
Springer Nature or its licensor holds exclusive rights to this article under a publishing
agreement with the author(s) or other rightsholder(s); author self-archiving of the accepted
manuscript version of this article is solely governed by the terms of such publishing
agreement and applicable law.
© The Author(s), under exclusive licence to Springer Nature Limited 2022
Nature | Vol 609 | 29 September 2022 | 985
RPPA and western blot data. Each analyte measurement was first
normalized by the GAPDH level, and then on the value of the same
analyte in the absence of inhibitors and ligand stimulation to obtain
fold changes (Supplementary Tables 1 and 2).
Data clustering and PCA. To cluster RPPA signalling patterns two
different unsupervised machine learning methods, Ward’s hierarchical clustering and the K-means clustering, were used. These methods
generated identical results and determined two distinct sets of data
points that corresponded to two different cell states, NGF-stimulated
TrkA differentiation state and BDNF-stimulated TrkB proliferation state
(Extended Data Figs. 2 and 3a).
The Pandas Python library was used for RPPA data analysis and
manipulation. For PCA compression and K-means data clustering we
used the scikit-learn Python library35. Crucially, PCA was used solely
for visualization purposes, while all cluster analysis, the SVM, STV and
DPD calculations were performed in the original dataspace. R base
functions. The pheatmap R package were used for Ward’s hierarchical
clustering and building a heatmap.
Separation of distinct physiological states using SVMs. Following
stimulation with growth factors or drug perturbations, the fold changes
in phosphorylation levels or protein abundances were depicted in a
molecular dataspace with the Cartesian coordinates. The SVM with a
linear kernel from the scikit-learn Python library was applied to build
a maximum margin hyperplane that distinguishes different cell states
in the molecular dataspace.
The SVM maximizes the separating margin using the data points that
are closer to the hyperplane and are termed the support vectors. The
separating hyperplane is defined as,
Here, x is a radius vector from the origin of the coordinates to any
point on the separating hyperplane, n is the vector of unit length that
is orthogonal to the separating hyperplane, and h is a constant.
Derivation of the STV. Let A be the centroid of a cloud of points Ai
(i = 1, 2 …) that corresponds to state 1, and B be the centroid of the point
cloud Bi corresponding to state 2. A STV from state 1 to state 2 is defined
as a vector s of unit length that has the same direction as the vector AB
connecting the centroids A and B,
Here and below, two sequential capital bold letters denote a vector
spanning from the point corresponding to the first letter and ending at
the point corresponding to the second letter. Equation (2) shows that the
STV is initially built in the full molecular dataspace of 115 dimensions.
the dimensionality of the molecular dataspace where the STV and perturbation vectors are calculated is reduced from 115 to 70.
Let A, with the radius vector xA be the centroid of the point cloud Ai,
corresponding to the unperturbed state 1. Let Apert with the radius vector x A pert be the centroid of the point cloud ( Aipert), corresponding to
the perturbed state 1. Then the perturbation vector is defined as,
x Apert − xA = AA pert = P
Distance from a data point to the separating plane along the STV.
Starting from a data point A in the molecular dataspace we build a vector AAs, which is parallel or antiparallel to the STV (s) and crosses the
separating hyperplane at a point As. Thus, we have,
If the vector AAs has the same direction as the STV, the value of S is
positive, while S is negative if the vector AAs has the opposite direction
to the STV. In either scenario, the length (|S|) of the vector AAs is the
distance from the separating hyperplane to the point A along the STV.
The vectors x As and xA connecting the origin of the coordinates and
the points As and A, respectively, are related by the following equation,
Using equations (1, 4 and 5), we obtain,
(x As, n) = ((xA + S ⋅ s), n) = (xA, n) + S(s, n) = h
Equation (6) allows us to calculate the distance |S| from a point A in
the molecular dataspace to the separating hyperplane between two
different cell states, as follows
∣S∣ = ∣ (h − (xA, n))/(s, n) ∣
If s = n then |S| is the shortest distance to the separating hyperplane.
If s ≠ n then |S| is larger than the shortest distance to the hyperplane,
because vectors s and n have unit lengths. If point A is a centroid of
a point cloud that corresponds to a distinguishable cell state, then
equation (7) determines the distance of this centroid to the separating hyperplane.
Calculation of the DPD module output using experimental data.
In the molecular dataspace, we consider the STV as a vector s of unit
length directed from a centroid of a differentiation TrkA point cloud
to a centroid of a proliferation TrkB point cloud. We now define the
output of the DPD module as the S value,
Ranking each network protein by its contribution to the STV. The
vector s determined by equation (2) in the Cartesian coordinates has
the components sk (k = 1,..., N). Each STV component sk corresponds to
an analyte k, measured by an antibody detecting a specific phosphorylation site on a protein or the abundance of a specific protein. The
absolute value |sk| determines the STV rank of the analyte k informing
us about its importance for the switching of cell states. These STV ranks
for all analytes are presented in Supplementary Table 3. The highest
ranked proteins and some of their immediate effectors were selected
as core signalling network components.
The direction of the vector n, which is orthogonal to the separating
hyperplane, points from the TrkB cloud to the TrkA cloud. In this case,
the DPD value S is positive for proliferation TrkB points and negative
for differentiation TrkA points. The DPD values for TrkA and TrkB cells
after growth factor stimulations and inhibitor treatments are given in
Supplementary Table 4.
Notably, the results of our analyses of all datasets presented in this
work will practically be the same, if we define STV as the normal vector
of the separating hyperplane (n), rather than the vector (s) connecting the centroids of two different cell states. Thus, both n and s can be
defined as STV depending on the situation or preference.
Derivation of perturbation vectors. For a correct interpretation of
perturbation data using the STV, we have to exclude the analytes that
composed the modules of our core signalling network. Accordingly,
Calculations of the DPD changes upon perturbations. Using the STV
(s), a perturbation vector (P) and the unit length vector (n) orthogonal
to the separating hyperplane, we can calculate how the DPD changes
following each perturbation by inhibitors. The DPD values, determined
for the centroids of unperturbed (A) and perturbed (Apert) states, S and
Spert, respectively, are the following (see equation (8)),
Spert = (h − (x A pert, n))/(s, n)
Using equations (3, 9 and 10), the change in the DPD upon a perturbation is expressed as follows,
ΔS = Spert − S = (xA − x A pert, n)/(s, n) = − (P, n)/(s, n)
into n subnetworks, each containing only edges directed to a particular
node (i). To determine the connection coefficients for all xk (k ≠ i), n − 1
independent parameters pj (j = 1,…, n − 1) must be perturbed, neither
of which can directly influence node i, whereas any other node k (k ≠ i)
is affected by at least one of these parameters pj. Formally, for each
xi (i = 1, …, n), we choose a subset Ρi of n − 1 parameters pj known to
have the property that the function fi for node i in equation (12) does
not explicitly depend upon pj, whereas each of the remaining nodes
k (k ≠ i) is perturbed by at least one pj ∈ ΡI. This condition is described
as follows,
From equation (11) it follows that if s = n, then ΔS = −(P, n) .
BMRA network inference. To reconstruct the topology and strengths
of causal connections of the core network, including the influence of
each pathway module on the DPD module, we have used a modified
version of BMRA. A family of MRA methods, including BMRA26, allows
both (1) predicting systems-level network responses to different perturbations and (2) reconstructing the topology and strengths of causal
network connections based on experimentally measured responses to
perturbations19,25,36.
Each core network module has a single quantitative output xi, termed
communicating species in the MRA framework. The temporal dynamics of the module outputs is given by a system of ordinary differential
equations (ODE),
= f (x , …, xn, p), i = 1, …, n
rij = ∂logxi /∂logxj ; xk = const (k ≠ i , j)
Positive and negative rij quantify direct activation and inhibition,
respectively, whereas zero values show that there are no direct connections. The coefficients rij are expressed in terms of the elements
of the Jacobian matrix (∂fi/∂xj) of the ODE system at the steady state
(st.st.), as follows5,
= − ∂f (x , … , x , p)  
st.st.
The connection coefficients cannot be directly measured and are
inferred using the systems-level, global network responses to perturbations. Following a change (Δpj) in a parameter (pj) that affects node j,
the global response (Rij) to this perturbation is determined as,
Taken into consideration that rii = −1 (equation (14)), all connections
to the node i can be found by solving the following system of linear
equations,
rikRkj ,
= 0, i = 1, …, n ; j = 1, …, n − 1;
Repeating this procedure for all n subnetworks, the entire network
is reconstructed.
This standard MRA procedure fails, if the data are too noisy or some
module responses were not detected24. BMRA overcomes these limitations by explicitly incorporating noise in equation (17)26
Here the functions fi describe how the rate of change of independent
variables xi depends on the activities of other network modules. The
parameters pi ∈ Ρ represent kinetic constants and any external or internal conditions, such as the conserved moieties and external concentrations that are maintained constant.
For each network module xi, the connection coefficient rij quantifies
the fractional change (Δxi/xi) in its output brought about by a change
in the output of another module (Δxj/xj), while keeping the remaining
nodes (xk, k ≠ i,j) unchanged to prevent the spread of this perturbation
over the network5,20.
st.st.
To infer the connection coefficients rij based on the experimentally
measured, global responses Rij, the entire network is initially divided
Here, Aik are the elements of the adjacency matrix, which are equal
to 1 if the connection coefficient rik is non-zero, or equal to 0 otherwise;
εij are the error variables assumed to be independently and identically
distributed Gaussian random variables with the 0 mean and the variance σ2, that is, ϵik ∼ N (0, σ 2) . The error variance (σ2) is assumed to be
a random variable with the inverse Gamma distribution, that is,
σ 2 ∼ IG(a, b), where a and b are the location and scale parameters. Following common practice we chose a = 1, b = 1. Further, for brevity we
refer to this distribution P(σ2).
BMRA uses prior knowledge that is formulated in the form of the
prior probability distributions. Based on the existing knowledge16,37
we derived the reference network A0i = {Aik
} . The prior distribution
P(A i)) , A i = {Aik} , has the maximum at the reference network A0i
and penalizes for the deviation from this network as follows,
P(A i) ∝ exp(− ψ ⋅ dH(A i, A0i )),where dH(A i, A0i )is the Hamming distance
between the network A i and the reference network A0i , ψ is a constant.
The prior distribution of ri is dependent on Ai, and σ2 is denoted by
P(ri|A i, σ 2). If there is no direct connection from xj to xi, that is, Aij = 0,
the corresponding connection strength (rij) is assumed to have 0 value
with probability 1, whereas the connection strengths representing
direct interactions (ri = {rij : Aij = 1, j ≠ i }) are assumed to have a Gaussian
prior P(ri|A i) ∼ N(0, Vi), where Vi = c σ 2 (R *i R *iT + λI ). Here, R*i is the global response matrix of the nodes (nj , j ≠ i ) which directly regulate ni
(that is, nj , j ≠ i : Aij = 1), c is the proportionality constant, which is also
known as the Zellner’s constant. As previously described26,38, we chose
c = N ip , where N ip is the number of perturbations other than those
directly affecting node xi, and λ = 0.2.
Bayesian statistics is applied to update prior estimates of the binary
vector Ai = {Aik}, k = 1,…, n, and the vector of connection coefficients
ri = {rik}, k = 1,…, n, to obtain posterior estimates of these variables
using the experimental data, that is, the global response matrix R = Rik
(equation (15)),
P(R|ri, A i, σ )P(ri|A i, σ )P(A i)P(σ )
Here, P(R|ri, A i, σ 2) is the likelihood function of the global response
matrix R, given a connection coefficient vector ri and a binary vector
Ai. P(ri|A i, σ 2) and P(A i) are the prior distributions of ri and Ai, respectively. The denominator P(R) is defined as follows,
P(R) = ∭ P(R|ri, A i, σ 2)P(ri|A i, σ 2)P(A i)P(σ 2)dridA idσ 2
A key to BMRA is that the likelihood function for the observed
global response matrix R is derived from the MRA equations (equations (17–19)),
P(R|ri, A i, σ 2) = N(R i|Ri*Tr, σ 2I )
Here, R i = {Rik , k ≠ i } is the global response of node xi to perturbations
that do not directly affect xi, Ri*T is the global response matrix of the
nodes ( xj , j ≠ i ) which directly regulate node xi (that is, xj , j ≠ i : Aij = 1,
and r = {rij : Aij = 1, j ≠ i }. N(R i∣Ri*Tr, σ 2I ) designates the normal distribution for Ri where the mean equals Ri*Tr and the variance is σ 2I .
The denominator in equation (19) that normalizes the probability
P(ri, A i, σ 2|R) cannot be obtained analytically. Therefore, its posterior
distributions were estimated using a Markov chain Monte Carlo sampling algorithm. The posterior probability of Ai provides a quantitative
measure of how well a certain configuration of Ai is supported by both
prior knowledge and experimental data.
The values and confidence intervals for the corresponding connection coefficients are obtained from the posterior probability of ri. To
increase the accuracy of the method, we have modified the previously
published algorithm26 and applied Occam’s razor approach by calculating the mean and s.d. of ri using not the entire posterior distribution
of ri, but only a part that has the highest posterior likelihood (5,000
networks from 200,000 sample networks).
Preparation of the RPPA perturbation dataset for the BMRA network
inference. Supplementary Table 5 presents a list of analytes that are
outputs of signalling modules (TRK, ERBB, ERK, AKT, JNK, S6K and
RSK) of our core network. The output of the DPD module is determined
using equations (8–11) in the 70-dimensional molecular dataspace. To
calculate the global response coefficients for the signalling modules, xi,
we used central fractional differences to approximate the logarithmic
derivatives,
Here xi0 and xi1 are the ith module outputs before and after a perturbation to the parameter pj. Because the sign of the DPD value (S) could
change for large perturbations, we used either left or right fractional
differences,
A feature of the BMRA formalism is that it can infer the network
topology without the need to perturb all modules. In a core network
we have not perturbed a module consisting of the ERBB family of RTKs,
which can crosstalk with Trk receptors either directly or through downstream signalling pathways and feedback loops. The output of this
additional RTK module (termed ERBB) is determined as the sum of
EGFR and ERBB2 phosphorylation, measured with the corresponding
antibody that does not distinguish between these two ERBB family
receptors. Having determined the global response coefficients of all
modules using equations (22 and 23), BMRA inferred the connection
strengths and confidence intervals that are given in Supplementary
Table 5.
Nonlinear model of the core signalling network and cell state transitions. Using the quantified core network topologies and the inferred
pathway influences on the DPD, a nonlinear ODE model was built for
TrkA and TrkB cells using the rule-based approach39. The signalling
variables are the protein phosphorylation levels normalized by the
protein abundances, and the phenotypic variable is the output of the
DPD module (equation (8)). Below we describe the fundamentals of
the model.
The activation of Trk and ERBB receptors by ligand binding and
dimerization is modelled mechanistically. Briefly, NGF/BDNF binding to
TrkA/TrkB is followed by receptor dimerization and phosphorylation,
whereas a basal rate of ERBB dimerization is maintained by diverse
growth factors present in serum. The homodimerization of TrkA, TrkB
and ERBB, and heterodimerization of TrkB and ERBB40,41 is modelled
using the thermodynamic approach developed previously42. The binding of the first and second molecules of the ligand and the subsequent
homo- and heterodimerization of RTKs satisfy ‘detailed balance’ constraints43,44. These thermodynamic restrictions require the product of
the equilibrium dissociation constants (Kd) along a cycle to be equal to 1,
as at equilibrium the net flux through any cycle vanishes, since the
overall free energy change is zero. Because ligand binding facilitates
the RTK dimerization, following the thermodynamic approach42, we
introduce three thermodynamic factors, describing how the Kd values
of homo- and heterodimerization of RTKs change upon ligand binding.
When Trk receptor inhibitor is added, an inhibitor-free protomer can
still cross-phosphorylate the other protomer in a dimer.
The core network dynamics was modelled up to 45 min, and therefore
the total moieties of ERK, AKT, JNK, S6K and RSK were assumed to be
conserved. However, internalization of RTKs that is occurring on this
timescale is included in the model. Following internalization some
receptor molecules are subsequently degraded, whereas the others are
recycled back to the membrane. The disappearance of RTKs from the
plasma membrane depends on the dimer composition. In the model
the rate of internalization of TrkB-ERBB heterodimers is slower than the
internalization rate of TrkA and TrkB homodimers, based on the literature45,46. The BMRA-inferred connections show that there are multiple
feedback loops to the ERBB module from downstream kinase modules
(Supplementary Table 5). The influence of these feedbacks on the ERBB
module activity is modelled as hyperbolic multipliers that modify the
rate of activating ERBB phosphorylation, defined as follows47,
Here Ya is an active form of protein Y that influences protein X. The
coefficient γYX > 1 indicates activation; γYX < 1 inhibition; and γYX = 1
denotes the absence of regulatory interactions, in which case the
modifying multiplier αYX equals 1. K YX is the activation or inhibition
constant.
The RTK dephosphorylation is catalysed by phosphatases. The activation and deactivation dynamics of the downstream signalling modules
is modelled using Michaelis–Menten kinetics and the hyperbolic multipliers that account for signalling crosstalk between the pathways.
The BMRA network reconstruction constrains parameters of the
dynamical model by maximum likelihood values of the inferred connection strengths (Supplementary Table 5). In particular, only interactions
between modules, where the connection coefficients have statistically
significant non-zero values, are included in the model. Additional constraints on the parameter values occur, because the inferred connection
coefficients are normalized Jacobian elements5, which are functions of
the model parameters (equation (14) and the next section).
DPD time trajectories. The model includes the DPD module whose
output summarizes the contributions of all individual proteins (minus
the core network constituents) to the global network responses. This
module describes cell-wide signalling, and the DPD output (S) is defined
by equation (8). The DPD maps the network-wide changes, which occur
in the multidimensional molecular dataspace upon perturbations, into
a one-dimensional (S) space. Our model allows to determine the dynamics of S following any drug perturbation to core network pathways. If
the data point clouds before and after a particular perturbation are
measured by experiments, ΔS is calculated using equation (11), which
can be used to test the model.
The DPD trajectory is a one-dimensional, time-dependent trajectory of a cell manoeuvring in Waddington’s landscape governed by a
signalling driving force and a restoring force. The signalling driving
force, σ(t), is determined by the outputs of signalling modules of a
core network and their connection coefficients to the DPD module,
σ (t) = ∑ rSj  st.st.
Here, xj(t) are the outputs of signalling modules, rsj are the corresponding BMRA-inferred connection coefficients to the DPD (see Supplementary Table 5), and sst.st and x st.st
are the initial steady-state values
of S and xj before perturbations.
The restoring force f(S) is a gradient force given by the derivative of
the potential (U), as follows
The potential (U) has three minimums. These minimums correspond
to three stable steady states, S0, S1 and S2. There are two unstable steady
states at the borders between the basins of attraction of two neighbouring steady states (Extended Data Fig. 9).
Assuming the quadratic potential U in the vicinity of each stable state,
which is widely used in physics48, the restoring force f(S) is modelled
using a piece-wise linear approximation. This force f(S) is set to zero
at the borders between the basins of attraction, and f(S) reaches its
maximum at the half distance between the border and the stable steady
state (equation (27) and Extended Data Fig. 9a).
α0 S − 2  ,
 α1 S − 2  ,
− α1 (S − S1),
,
,
The DPD trajectory is calculated, as follows,
This equation allows for an interpretation of a cell progressing
through the molecular dataspace as a particle that moves in the gradient
force field and the field of external forces exerted by responses of core
signalling pathways,
+ ∑ rSj  st.st.
This gradient force field and the field of external forces shape the
evolving Waddington’s landscape (W), as follows,
W = U − ∑ rSj  st.st.
In the vicinity of the steady state Si ∈ {S0, S1, S2}, the solution of equation (28) is expressed analytically as follows,
S (t) = Si + e−αt ∫ ∑ rSj  st.st.
Here α ∈ {α0, α1, α2} is the slope parameter defined in equation (27).
Equation (31) illustrates the system has a characteristic memory time,
tm ∼ 1/α. At timescales much smaller than the memory time, t ≪ tm, the
entire change in S is determined by the time integral over the signalling
driving force.
Refining parameters of the dynamic model. To decrease the number
of parameters to fit, the concentrations of different protein forms and
the parameters with the concentration dimensionality, such as, the
Michaelis constants, were normalized by the conserved total protein
concentrations. Only time was left as dimensional variable (measured
in seconds) to readily interpret model simulations.
To refine the parameters of pathway interactions of our core network
inferred by BMRA, the data were split into a training set and a validation
set. The training set included the time course of TrkA and TrkB phosphorylation measured by western blot and 10 min RPPA data for the remaining signalling modules. The model-generated time courses were fitted
to these training set data with the objective function defined as the sum
of squares of deviations. A feature of our parameter refinement is that
in addition to the training dataset, we constrained the parameters using
the BMRA inferred connection coefficients within their confidence
intervals. Implicit constraints on the parameter values occur, because
the connection coefficients defined in equation (14) must be within
the confidence intervals of the BMRA inferred connections. Then, we
used a unique feature of the pyBioNetFit software, which allows adding
parameter constraints in the forms of inequalities to the parameter fitting process49. A combination of scatter search and simplex methods
and pyBioNetFit software were used to fit the model simulations to the
training dataset. Scatter search with a population size 20 was used to
obtain the initial parameter set, and the simplex algorithm was used
for the local refinement of the initial set. The validation set consisted of
45 min RPPA data for signalling modules of the core network. Fig. 4a,b
and Extended Data Figs. 6–8 show the simulated time courses with the
experimental data points imposed on the model predictions.
Equation (28) determines the DPD dynamics when a cell’s progression through the molecular dataspace is directed by the signalling
driving force and the restoring force. For the signalling driving force
we fit the coefficients, βj = rSj  st.st.
st.st  , in the ranges constrained by the
confidence intervals of the BMRA-inferred connection coefficients (rSj),
while the signalling module outputs (xj) are calculated by the model.
For the restoring force, equation (27), slope parameters {α0, α1, α2}
and stable steady state positions {S0, S1, S2} were fitted.
Model simulations. In total, the rule-based nonlinear model of the
core signalling network and cell state transitions consists of 82 species
and 405 reactions. The SBML files of the TrkA and TrkB models with all
equations and parameters can be found at https://github.com/OleksiiR/
cSTAR_Nature. The simulations of the models were run using the BioNetGen software39, which used the CVODE routine from the SUNDIALS
software package for solving ODEs. The Matplotlib Python package was
used for plotting experimental and modelling results.
STV analysis and core network reconstruction using RAF inhibitorresistant melanoma datasets. To build STV and separating hyperplane
we labelled samples from non-treated melanoma SKMEL-133 cells as
proliferation state, and samples from cells treated with a combination
of MEK and PI3K, AKT or mTOR inhibitors, which stopped proliferation and induced apoptosis, as non-proliferating, apoptotic state.
We also tested that the STV that was built using a subset of data points
from non-proliferating, apoptotic state, which corresponded to any
of these drug combinations, did not change the composition of a core
network and yielded similar DPD values for two cell states and the rest
of inhibitor perturbations.
The STV ranking for the SKMEL-133 cells is presented in Supplementary Table 9, sheet ‘full_STV’. The top STV components include IRS, the
PI3K–AKT–mTOR and ERK signalling modules and their downstream
targets, such as the cell cycle proteins, RB, CycB1 and CycD. Based on
this ranking, the core network contains ERK, AKT, mTOR, SRC, CDK4/6,
PKC, IRS and DPD modules. To analyse and predict the effects of inhibitor perturbations, the core components were removed from the STV.
Supplementary Table 9, sheet ‘reduced_STV’ presents the ranking of
components for the reduced STV.
Next, we inferred the connections between core network signalling
proteins and their influence on the DPD phenotypic module using
BMRA. The global response coefficients were calculated using equations (22 and 23). The BMRA code was run twice, for the network without
and with MYC module. The matrices of the prior and posterior networks
are presented in Supplementary Table 10.
Building a nonlinear model of RAF inhibitor-resistant melanoma.
A nonlinear dynamic model was derived based on the quantified core
signalling network topology and signalling connections to the DPD
module, using a rule-based approach39. As in the model of neuroblastoma SH-SY5Y cells, the concentrations of active and inactive protein
forms were normalized by the protein abundances. The phenotypic
variable S represents the output of the DPD module.
First, a coarse-grained model was built solely based on the inferred
core network connections that did not include the MYC module (Fig. 7a
and Supplementary Table 10, sheet ‘noMYC’). In this model, core network proteins had only two, active and inactive, states, and all pathway cross-talks were described by hyperbolic multipliers (given in
equation (24)). The only exception was IRS, which had two groups of
phosphorylation sites, activating and inhibitory. Accordingly, negative
feedback connections to the IRS module were described through IRS
phosphorylation on inhibitory sites by Michaelis–Menten equations.
This phosphorylation resulted in enhanced IRS degradation, which
correlated with the original data50,51. Therefore, the model also included
the IRS synthesis and degradation. Next, we added the MYC module to
this model based on the corresponding inferred network (Fig. 7b and
Supplementary Table 10, sheet ‘withMYC’). These simplified models
were named ‘SKMEL-133-1.bngl’ and ‘SKMEL-133-2.bngl’, respectively.
Further model refinement included a more mechanistic description
of IRS activation by insulin and IGF1 receptors and the CDK module.
To account for the measured changes in the cyclin D abundance, we
incorporated its synthesis and degradation and CDK4/6 activation by
binding cyclin D. To describe IRS activation, we introduced IGF1 and
Insulin receptors into the model. This model was named ‘SKMEL-133-3.
bngl’. Although this model can be further mechanistically detailed by
incorporating the previously developed models of IRS1–ERK–AKT
interplay through the GAB scaffold52 and RAF dimerization53, this was
not required to describe the data obtained in the original publication29.
We used the ‘SKMEL-133-3.bngl’ model to generate predictions presented in the Results.
Model parameters were refined by dividing the data29 into a training set that included only single-drug perturbations data and a validation set consisting of perturbations by drug combinations. The
model-generated dose responses were fitted to these training set data
with the objective function defined as the sum of squares of deviations.
Similarly as above, we constrained the parameters using the BMRA
inferred connection coefficients within their confidence intervals, and
used the pyBioNetFit software, which allows adding parameter constraints in the forms of inequalities to the parameter fitting process49.
A combination of scatter search and simplex methods in pyBioNetFit
software were used to fit the model simulations to the training dataset.
Scatter search with a population size 12 and 50 iterations was used to
obtain the initial parameter set, and the simplex algorithm was used for
the local refinement of the initial set. Extended Data Fig. 15a shows the
simulated dose responses with the experimental data points imposed
on the model predictions.
Estimating synergy strength for drug combinations from model
predicted DPD responses. Simulations of the developed nonlinear
dynamic model allowed predicting DPD responses to different inhibitors and their combinations. To estimate the synergy strength to move
the DPD towards apoptotic cell states we used Loewe isoboles (Fig. 7c,d
and Extended Data Fig. 15b) and the CI27,54. These criteria require much
more data points than Bliss independence criterion, and thus were applied only to computational data, which unlike experimental data can
be generated for large numbers of different doses.
Let ICZ1 and ICZ2 be the concentrations of inhibitors 1 and 2 that
produce the same effect (Z) given separately. Here, Z is an arbitrary
inhibition level, which can be, for example, 10, 20, 30, 50, 70 or 90%.
Let I1 and I2 be the concentrations of inhibitors 1 and 2 that produce the
effect Z given in a combination. The CI is defined as,
For any particular drug combination and a dose ratio, the CI defined
in equation (32) allows detecting whether the Loewe isoboles are concave or convex, corresponding to either synergy or antagonism, respectively. The CI indicates synergy54 when CI < 1 and antagonism when
CI > 1. Because the CI is a function of inhibitor doses and effects, we
have determined the minimal value of CI across dose-response plane.
This minimal CI value corresponds to the optimal ratio of drugs in a
combination. It determines the maximal synergy strength that can be
potentially achieved for a specific drug combination. These minimal CI
levels were 0.48 for a combination of MEK and MYC inhibitors, and 0.4
for a combination of PI3K and AKT, and insulin and IGF1R inhibitors,
demonstrating the higher synergy strength for a combination of PI3K
and AKT, and insulin and IGF1R inhibitors.
As there are no highly selective TrkA and TrkB inhibitors available, we
used SP600125 (Selleckchem, S1460), which inhibits both TrkA and
TrkB55. Because SP600125 also inhibits the c-Jun N-terminal Kinase
( JNK)56, we used JNK-IN-8 (Selleckchem, S4901), which targets JNK
but not the Trk receptors57, to dissect the effect of the JNK inhibition.
AKT was blocked by the AKT inhibitor IV (Merck Millipore, 124011).
To inhibit p70S6 kinase, which phosphorylates the ribosomal RPS6
protein, we used LY2584702 (Selleckchem, S7698). To perturb the
ERK pathway, we used the MEK inhibitor Trametinib (Selleckchem,
GSK1120212, S2673), which inhibits the kinase that activates ERK,
and BI-D1870 (Selleckchem, S2843), which inhibits p90RSK, a kinase
downstream of ERK. To inhibit ERBB module we used Gefitinib (Selleckchem, ZD-1839, S1025).
Antibodies. Antibodies against phospho-TrkATyr674/675/TrkBTyr706/707
(4621), total TrkA (2505), total TrkB (4603), phospho-FAKTyr397(8556),
total GAPDH (2118), as well as anti-rabbit (7074) and anti-mouse (7076)
IgG HRP-linked antibodies were from Cell Signaling Technology.
Antibodies against phospho-ERK1/2 (8159) and total ERK1/2 (5670)
were from Sigma-Aldrich. Antibody against total FAK (sc-558) was from
Santa Cruz. Mouse monoclonal anti-V5-HRP (R961-25) was from Life
Technologies.
Plasmids. To generate the pLX302/NTRK1 and pLX302/NTRK2 expression vectors, pENTR223 entry vectors containing the NTRK1 or
NTRK2 ORF (Addgene #23891 and #23883, respectively) were used
for LR recombination reaction together with the pLX302 destination
vector (Addgene #25896) according to the manufacturer’s instructions
(Gateway Cloning system, Life Technologies). The myristoylated AKT
plasmid, Myr–AKT1, was described previously15.
Generation of isogenic cell lines. The SH-SY5Y neuroblastoma cell line
was a gift from F. Westermann. F. Westermann obtained these cells from
DSMZ. The cells were validated using STR profiling. These cells have no
MYCN gene amplification and only 19 mutations according to the CCLE
and COSMIC databases, and they are genetically stable in culture6,58.
The cells were cultured in RPMI 1640 (Gibco) supplemented with 10%
FBS (Gibco), 2 mM l-glutamine (Gibco), and 1% penicillin-streptomycin
(Gibco) under standard tissue culture conditions (5% CO2). The cells
were regularly tested for mycoplasma.
To generate the SH-SY5Y/pLX302/NTRK1 (‘SY5Y-TrkA’) and SH-SY5Y/
pLX302/NTRK2 (‘SY5Y-TrkB’) cell lines, stably expressing TrkA or TrkB,
respectively, the expression vectors were transfected into SH-SY5Y cells
using the JetPrime transfection reagent as instructed by the manufacturer (Polypus). Puromycin (Sigma-Aldrich) selection (2 μg ml−1) was
initiated 48 h after transfection and continued for 2 weeks with culture
media refreshed in every two days. TrkA/B expression was confirmed
by western blotting.
Stimulation of TrkA and TrkB-expressing SH-SY5Y cells was carried
out 30 min following inhibitor addition, using 100 ng ml−1 recombinant
NGF (450-01) and BDNF (450-02), respectively (both from Peprotech).
TrkA and TrkB receptors activate very similar signalling pathways,
which include PLCγ, ERK and AKT as main effectors, and it is unclear
what particular changes in signalling and expression patterns cause
distinct TrkA and TrkB cell fate decisions7. Therefore, SH-SY5Y cells
are an ideal system to test cSTAR.
Imaging experiments and drug interaction calculations. Differentiation was assessed visually at 72 h following treatment, using the
EVOS FL Imaging System (Life Technologies). Cells with neurites >2
cell body diameters were scored as differentiated. For each treatment
condition three biological replicates were used to quantify percentage
of differentiated cells. Supplementary Table 13 represents the total
number of cells and the number of differentiated cells for each image.
Statistically significant differences were determined using unpaired
one-tailed t-test.
The phenotypic effect of drugs was assessed using the changes in
the percentage of differentiated cells calculated from imaging experiments. For each drug (Trametinib, Gefitinib or their combination), the
drug-induced differentiation effect (Y) was defined as follows,
Here, Pdrug is the percentage of differentiated TrkB cells stimulated
with BDNF and treated with the drug, PA is the percentage of differentiated TrkA cells stimulated with NGF, and it is always greater than PB,
which is the percentage of differentiated TrkB cells stimulated with
BDNF. Equation (33) shows that Y is 1 if the drug has no effect, Y is 0
if the drug drives TrkB cell differentiation to the same percentage as
observed for TrkA cells, and Y is between 0 and 1 for a partial induction of TrkB cell differentiation by the drug. The definition of the drug
effect by equation (33) allows us to calculate the Bliss synergy score for
a combination of drugs 1 and 2 using equation (4) in the Supplementary Information. The calculated synergy score between Gefitinib and
Trametinib is 51 ± 7%, demonstrating high synergy59.
Western blotting. Cells were lysed in ice-cold 10 mM Tris-HCl pH 7.5,
150 mM NaCl, 0.5% (v/v) NP-40 (Calbiochem), complemented with
COMPLETE Mini protease and PhosSTOP phosphatase inhibitor
cocktails (Roche). Lysates were cleared by centrifugation at 10,000g
for 10 min at 4 °C and adjusted to equal protein concentrations following protein quantification using the Pierce BCA Protein Assay Kit
(Thermo Scientific). SDS–PAGE (10% PAA) and western blotting were
performed using the Mini Protean Tetra system (Bio-Rad). Protein
bands were visualized using the enhanced chemiluminescence system
(GE Healthcare) by the ChemoStar Imager (INTAS Science Imaging
Instruments GmbH). Blots were quantified using the ImageJ software.
Proliferation assays. To assess cellular proliferation and viability, we
used two different assays and compared their results. For the first assay, 20,000 cells per well were seeded into Nunc F96 MicroWell White
Polystyrene Plates (Thermo Scientific 136101). Cell Proliferation was
assessed at 72 h post treatment, using the CellTiter-Glo Luminescent
Cell Viability Assay (Promega), according to manufacturer’s instructions, and the SpectraMax M3 Microplate Reader (Molecular Devices).
For the second assay, cells were plated at 20,000 cells per well into
96-well F-bottom tissue culture plates (Greiner, 655180). Proliferation
and viability of inhibitor- and control-treated cells was assayed after
72 h by CellTiter 96 Aqueous One Solution Cell Proliferation Assay
(MTS; Promega) according to manufacturer’s instructions. In both
cases, three biological replicates were performed for each condition,
the results represent the mean ± s.d. of triplicate samples, expressed
as a percentage of control.
Reverse phase protein array. We used a custom made RPPA with 115
validated antibodies (Supplementary Table 1) to measure the activities
of signalling pathways involved in TrkA/B signalling7, including MAPK
(RAS-ERK, JNK, p38), PI3K (AKT, mTORC1/2), JAK–STAT, PLCγ–PKC,
TGFβ–SMAD, WNT, cAMP, cell cycle (CDK1, cyclins, RB, p53, p21WAF),
apoptosis (BAX, BCL2, BCLx, caspase 3), transcription factor (MYC,
NFκB, JUN), and tyrosine kinase (SRC, EGFR, PDGFR, IGFR) pathways.
These antibodies detect phosphorylation sites that change protein
activities, or protein abundances.
RPPA analysis was carried out using established protocols for
nitrocellulose-based arrays60. In brief, cell lysates were prepared in
1% Triton X-100, 50 mM HEPES (pH 7.4), 150 mM sodium chloride, 1.5
mM magnesium chloride, 1 mM EGTA, 100 mM sodium fluoride, 10
mM sodium pyrophosphate, 1 mM sodium vanadate, 10% glycerol,
supplemented with COMPLETE Mini protease and PhosSTOP phosphatase inhibitor cocktails (Roche). After clearing by centrifugation at
13,300 rpm for 10 min at 4 °C the protein concentration was determined
using the Coomassie Plus Protein Assay (ThermoFisher Scientific). Protein concentrations were adjusted to a final concentration of 1mg ml−1
followed by denaturation upon addition of 4× sample buffer containing
10% β-mercaptoethanol and heating to 95°C for 5 min. A 4-step dilution
series of each sample was prepared in PBS with 10% glycerol giving final
concentrations of 0.75, 0.375, 0.1875 and 0.09375 mg ml−1. Samples
were printed onto nitrocellulose-coated slides (Grace Bio-Labs) across
multiple sub-array areas under conditions of constant 70% humidity
using an Aushon 2470 array platform (Quanterix). Printed slides were
blocked using SuperBlock (TBS) blocking buffer (ThermoFisher Scientific) and each sub-array was separately incubated with validated
primary antibodies (all diluted 1:250 in SuperBlock). Bound antibodies
were detected by incubation with anti-rabbit or anti-mouse DyLight
800-conjugated secondary antibodies (New England BioLabs). Slide
images were acquired using an InnoScan 710-IR scanner (Innopsys) with
laser power and gain settings optimized for highest readout without
saturation of the fluorescence signal. The relative fluorescence intensity
of each array feature was quantified using Mapix software (Innopsys).
The linear fit of the dilution series of each sample was verified for
each primary antibody and the median relative fluorescence intensity
from the dilution series was calculated to represent relative abundances
of total proteins and posttranslational epitopes across the sample set.
Finally, signal intensities for each sample were normalized to total
protein loading on the array slides by using the signal readout from a
fast-green (total protein) stained array.
Sample preparation for mass spectrometry experiments. Cells
were resuspended in 100 µl of ice-cold 8M urea/50 mM Tris-HCL
pH 8.0, supplemented with phosphatase and protease inhibitors
(Roche). Each sample was sonicated (Syclon Ultrasonic Homogenizer)
for 2 × 9 seconds at a power setting of 15% to disrupt the cell pellet.
The protein samples were normalized to 550 µg. Each sample was
reduced by adding 8mM dithiothreitol (DTT) and mixing (thermomixer 1,200 rpm, 30 °C) for 60 min and subsequently carboxylated
by adding 20 mM iodoacetamide and mixing (thermomixer 1,200
rpm, 30 °C) for 30 min in the dark. The solution was diluted with
50 mM Tris-HCL pH 8.0 to bring the urea concentration down to
2M. Sequencing Grade Modified Trypsin (Promega V5111) was resuspended in 50 mM Tris-HCL at a concentration of 0.5 µg µl−1 and
added to each solution. The samples were digested overnight (1:100
enzyme to protein ratio) with gentle shaking (thermomixer 850 rpm,
37 °C). The digestion was terminated by adding formic acid to 1% final
concentration and cleaned up using c18 (HyperSep SpinTip P-20,
BioBasic C18, Thermo Scientific).
Phosphopeptide enrichment was carried out with TiO2 (Titansphere
Phos-TiO Bulk 10 µm, (GL Sciences) using an adapted method previously
described61. In summary, each sample was incubated with TiO2 beads
for 30 min by rotation in 80% acetonitrile, 6% trifluoroacetic acid, 5 mM
monopotassium phosphate, 20 mg ml−1 2,5- dihydroxybenzoic acid,
this step was carried out twice. The beads were washed 5 times in 80%
acetonitrile/1% trifluoroacetic acid, before elution of the phosphopeptides with 50% acetonitrile, 7% ammonium hydroxide. The two eluents
from each sample were then pooled and dried down.
LC-MS/MS method. Samples were run on a Bruker timsTof Pro mass
spectrometer connected to a Evosep One liquid chromatography system. Tryptic peptides were resuspended in 0.1% formic acid and each
sample was loaded on to an Evosep tip. The Evosep tips were placed in
position on the Evosep One in a 96-tip box. The autosampler picks up
each tip, elutes and separates the peptides using a set chromatography
method (30 samples a day) The mass spectrometer was operated in
positive ion mode with a capillary voltage of 1,500 V, dry gas flow of
3 l min−1 and a dry temperature of 180 °C. All data were acquired with
the instrument operating in trapped ion mobility spectrometry (TIMS)
mode. Trapped ions were selected for ms/ms using parallel accumulation serial fragmentation (PASEF). A scan range of (100–1,700 m/z)
was performed at a rate of 5 PASEF MS/MS frames to 1 MS scan with a
cycle time of 1.03 s. Due to a breakdown of an MS instrument, sample
replicates were analysed on another MS instrument using identical
conditions.
Analysis of mass spectrometry data. The mass spectrometer raw
data was searched against the Homo sapiens subset of the Uniprot
Swissprot database (reviewed) using the search engine Maxquant (release 2.0.1.0) In brief, specific parameters were used (Type: TIMS DDA,
Variable mods; Phospho (STY)).
Each peptide used for protein identification met specific Maxquant
parameters, i.e., only peptide scores that corresponded to a false discovery rate (FDR) of 0.01 were accepted from the Maxquant database
search. Phospho (STY)Site intensities with localization scores >0.75
were used for relative quantitation.
Further information on research design is available in the Nature
Research Reporting Summary linked to this article.
