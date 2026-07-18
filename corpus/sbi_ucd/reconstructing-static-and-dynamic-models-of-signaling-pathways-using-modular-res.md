# Reconstructing static and dynamic models of signaling pathways using Modular Response Analysis

Available online at www.sciencedirect.com
Reconstructing static and dynamic models of
signaling pathways using Modular Response Analysis
Tapesh Santra1,†, Oleksii Rukhlenko1,†,
Vadim Zhernovkov1 and Boris N. Kholodenko1,2,3
In this review we discuss the origination and evolution of
Modular Response Analysis (MRA), which is a physics-based
method for reconstructing quantitative topological models of
biochemical pathways. We first focus on the core theory of
MRA, demonstrating how both the direction and the strength of
local, causal connections between network modules can be
precisely inferred from the global responses of the entire
network to a sufficient number of perturbations, under certain
conditions. Subsequently, we analyze statistical reformulations
of MRA and show how MRA is used to build and calibrate
mechanistic models of biological networks. We further discuss
what sets MRA apart from other network reconstruction
methods and outline future directions for MRA-based methods
of network reconstruction.
Systems Biology Ireland, University College Dublin, Belfield, Dublin 4,
Conway Institute of Biomolecular and Biomedical Research, University College Dublin, Belfield, Dublin 4, Ireland
School of Medicine and Medical Science, University College Dublin,
Belfield, Dublin 4, Ireland
Corresponding author: Kholodenko, Boris N. (boris.kholodenko@ucd.ie)
Equal contribution.
This review comes from a themed issue on Mathematical modelling
Edited by Leah Edelstein-Keshet and William Holmes
For a complete overview see the Issue and the Editorial
Available online 22 February 2018
https://doi.org/10.1016/j.coisb.2018.02.003
2452-3100/© 2018 Elsevier Ltd. All rights reserved.
Understanding how biological molecules interact with
each other is a formidable challenge, because causative
interactions cannot be directly captured by widely used
experimental techniques. However, the concentrations
of these molecules in their active and inactive states can
be experimentally measured. Often the resulting data
are noisy and incomplete, and efforts to reconstruct
networks of biochemical interactions by analyzing these
data had limited success. A host of statistical methods
has been developed to reverse engineer cellular signal
transduction network (STNs) by numerous research
groups, but the majority reconstructs static networks
and struggles to distinguish direct from indirect interactions [1,2]. The simplest network reconstruction
algorithms measure correlation [3,4] or mutual information (MI) [5] between pairs of molecules (network
nodes), and assume that molecules that have high correlation or MI interact with each other. While directly
interacting molecules will have high positive or negative
correlation or MI measures, the converse statement is
untrue. For instance, two non-interacting molecules
which are regulated by a third one may also have high
correlation or MI. This issue is addressed by partial
correlation [6,7] and network deconvolution [8]
methods, which remove the effects of potential coregulators from these pairwise association measures.
However, the pairwise association based methods do not
account for combinatorial regulation where several
molecules simultaneously influence the activity of
another molecule.
Linear regression based methods [9e11] address
combinatorial regulation by assuming that the activity of
each molecule is linearly dependent on the concentration
of many others. Clearly, this assumption is an oversimplification. Non-parametric regression methods such
as regression trees [12,13] do not impose assumptions
about the mathematical nature of relationships between
different biochemical molecules. However, it remains
challenging to identify direct interactions, because
different interactions patterns can explain the data about
equally well. Bayesian algorithms [14e17] incorporate
existing knowledge of biochemical interactions which
reduces the number of possible interaction patterns that
fit the observed data, thereby increasing the accuracy of
the reconstructed networks. Physics and engineering
approaches have been developed to infer the relationships between the variables of nonlinear dynamic systems based on the time-course evolution of a single or
only few systems variables [18]. However, biological data
sets do not usually satisfy the condition required for
applicability of these methods.
Networks reconstructed by the above algorithms often
evade mechanistic or biological interpretation. For
instance, many statistical methods provide only a score/
probability for each interaction, which says little about
the interaction strength and its nature. We introduced a
physics-based method, termed Modular Response
12 Mathematical modelling
Analysis (MRA), which reconstitutes and quantifies
connections between network modules from measured
responses of the entire network to systematic perturbations [1,19e22]. Networks obtained using MRA
reconstruction can be interpreted in terms of direct
interactions between modules, and further molecularly
interpreted by detailing processes inside the modules.
However, MRA requires as many perturbations as there
are modules and also struggles with noise. To address
this critical deficiency, statistical reformulations of MRA
have been developed, which include the total least
squares, maximum likelihood, Monte Carlo simulation
based and Bayesian formulations of MRA [14,17,23e
28]. These algorithms relax some stringent requirements of MRA. While total-least square and
Monte-Carlo simulation based methods primarily focus
on dealing with the noisy nature of perturbation data,
the maximum likelihood and Bayesian MRA formulation
also handles insufficient number of perturbations. The
Bayesian MRA algorithms can also incorporate prior
knowledge of the network into the MRA-based formulation to mitigate the increased uncertainty arising from
noisy and incomplete perturbation data [14,17,24,28].
Here we review the original MRA framework and how it
evolved over the last decade to meet emerging
challenges.
MRA-based approaches to network reconstruction
stemmed from the earlier work on quantification of
direct molecular interactions between nodes and the
global responses of an entire network to external signals
or perturbations to its components [29e31]. A node can
be a single gene or protein, or a module, such as a gene
cluster or a group of proteins. Module outputs are
termed communicating species, whereas the other
module components (if any) participate in reactions
internal to this module. Only communicating species
can directly affect other modules. Thus, MRA can
consider connections between single genes/proteins or
between pathways.
We denote each node concentration or activity by xi. If a
node is a module, then xi is concentration or activity of
the communicating species. The connection coefficient
(rij) between two nodes i and j is determined by the local
response (Dxi/xi) of node i to the ensuing activity change
(Dxj/xj) of node j, provided the activities of all other
nodes (xk, k s i,j) remain fixed, while node j is allowed
to relax to its steady state [19,30]. A mathematical
definition requires the changes (Dx/x) to be infinitesimally small, resulting in log to log derivatives,
Positive and negative connection coefficients indicate
activation and inhibition, respectively, whereas zero
value shows that there is no direct connection. A positive
rij < 1 means that (small) fractional changes in module j
output are attenuated in module i, whereas rij > 1 means
that these fractional changes are amplified by the factor
rij (referred to as “ultrasensitivity” of module i to module j
for protein phosphorylation cascades [29,32]). Although
Eq. (1) uses the dimensionless connection coefficients
given by the logarithmic derivatives, MRA can also use
the absolute connection coefficient values (cij), given by
the derivatives, cij = vxi/xj [1].
The dynamics of the network under consideration can
commonly be described by an ordinary differential
equation (ODE) system,
¼ fi ðx1 ; .; xn ; pÞ; i ¼ 1; .; n
Here the functions fi describe how the rate of change of
xi depends on the activities of network species, and the
parameters pi 2 Р represent any external or internal
condition maintained constant, as, e.g., external concentrations, conserved protein abundances, rate constants, pH, temperature, etc.
Instructively, the connection coefficients given by Eq.
(1) can be expressed in terms of the elements of the
Jacobian matrix (vfi/vxj). At a steady state (ss),
fi(x1 ; .; xn , p)=0, and therefore dfi(x1 ; .; xn , p)=0.
Using a chain rule for this differential, we obtain,
Following the definition of the connection coefficients,
if all but the ith and jjh nodes of the network are kept
fixed then the above equation reduces to the following
expression,
vxi  ¼ 0;
yielding,
Multiplying both sides of Eq. (4) by (xj/xi) yields,
Importantly, Eq. (5) shows that the diagonal elements
(rii) of the connection coefficients matrix (r) have values
of minus one, rii = 1. This formal result has a clear
intuitive interpretation. Indeed, the coefficient, rii, corresponds to the steady-state response of node, xi, to a
transient change in the same node at time zero. Assuming
the steady state is stable, xi will return to its initial steadystate level, since system parameters and all of the other
modules are kept unchanged. Consequently, the steadystate change in xi will be equal to the negative value of the
initial change. Therefore, to quantify the network
interaction map, MRA needs to infer n,(n1) connection
coefficients of the matrix r, Eq. (5). Clearly, the
connection coefficients expressed in terms of the Jacobian elements will depend on the steady state under
consideration, and thus on particular values of the systems parameters. If a network has multiple steady states
[33], the connection coefficients, rij, will generally have
different values for distinct steady states.
Importantly, the local responses that quantify connections between nodes j and i cannot be directly measured,
because a perturbation to an individual network
component propagates through the entire network,
causing widespread global changes and masking direct
connections between nodes. Only the global responses
can be measured following the relaxation of the network
to a new steady state. Following a change (Dpj) in a
parameter (pj) that directly affects node j, the global
responses (Rij) to this perturbation can be measured for
every network node (xi),
For networks of any size and complexity, MRA has
solved the problem of finding the local, direct links
between components through the global responses
[19,34,35]. To illustrate this solution, we conceptually
divide the entire network into n subnetworks, each
containing only edges directed to a particular node (i),
see Figure 1. To determine the connection coefficients
ri = {rik} for all xk (k s i) that may affect node i, MRA
uses a specific experimental design of perturbing n - 1
independent parameters pj (j = 1, ., n1), none of
which can directly influence node i, whereas any other
A subnetwork containing only edges directed to a particular node i.
Activating and inhibiting interactions are shown by black and red,
respectively.
node k (ksi) is affected by at least one of these parameters pj. Formally, for each xi (i = 1, ., n), we choose
a subset Р i of n1 parameters pj known to have the
property that the function fi for node i in Eq. (2) does not
explicitly depend upon pj, whereas each of the remaining nodes k (ksi) is perturbed by at least one pj 2 Р I.
This condition is described as follows,
This prior information about the system is far less
restrictive than it may first appear. Indeed, it is usually
the case that biological information is available, for
instance, telling us that a certain protein has no direct
influence on an unrelated biochemical interaction, or a
certain inhibitor of a membrane kinase has no direct influence on a cytoplasmic phosphatase, and so on. At a
steady state, fi(x1 ; .; xn , p)=0, and taking the full derivative of the function fi in Eq. (2) with respect to pj
under the condition of Eq. (7), we obtain,
rik Rkj ¼ 0;
¼ 1;.;n  1;
Since rii = 1, there are n1 unknown connection coefficients rik in Eq. (8). We conclude that from the data
on the global responses Rkj to n1 perturbations of parameters pj from a subset Р i, the vector ri = {rik} of the
14 Mathematical modelling
connection coefficients from all nodes xk (k s i) to node
xi can be inferred by solving Eq. (8) [1,Kholodenko,
2002 #20,23]. Repeating this procedure for all subnetworks, the entire network is reconstructed.
Evolution of MRA-based approaches
Figure 2 summarizes the progression of MRA-based
methods, as discussed in detail below.
are experimentally measured. Andrec et al. [23] proposed to use the Total Least Square (TLS) method,
which assumes that Eq. (8) is not exactly satisfied due
to noise in the measured values (Rkj) of global responses
coefficients. It then simultaneously estimates the potential noise-free global responses (R0kj ), which are
closest in the mean squared sense to the noisy global
responses, and the corresponding local responses (rik0 )
that satisfy the following equation exactly,
Optimal solutions of MRA equations using Total Least
The solutions of original MRA equations (Eq. (8)) are
sensitive to noise in the global response coefficients that
rik0 R0kj ¼ 0;
i ¼ 1; .; n; j ¼ 1; .; m>n  1
Noisy incomplete Global Response Matrix
(number of perturba ons can be < N
Santra et. al., 2013 , Halasz et. al. 2016, Santra, T. 2017
Noisy incomplete Global Response Matrix
(number of perturba ons can be < N
Calibrated mechanis c model
Evolution of MRA-based methods. Original MRA considered noise-free global responses to a complete set of N-1 independent perturbations. TLSMRA (Total Least Squares – MRA) considers a noisy, over-determined dataset. LM-ML-MRA (Levenberg–Marquardt Maximum Likelihood – MRA) and
Bayesian MRA (BMRA) allow incorporating prior knowledge about network circuitry to handle incompleteness in input data as well as noise in it. BMM
algorithm allows to calibrate ODE models based on the probability distributions for local response matrices generated by BMRA-based methods.
To preserve the notations of the original paper [23], we
transpose the vector-row r 0i to vector-column r 0T
global responses (R0 ¼ R0kj ) to R0T ¼ R0jk . In this
matrix form, Eq. (9) reads,
The TLS estimation of the connection coefficients is
obtained as follows:
Step 1: For each node i, assemble a transposed global
response matrix m  n, R⊥i
mn , which contains the global
responses of n network nodes to m (where m > n  1)
perturbations that do not directly affect node i. According
mn is perpendicular to the column vector r i
whose ith element (rii ) is  1. Therefore, if Rmn was
noise free, it would have had a rank of n  1. But due to
mn has the full rank (n). Therefore, the noise
free global response matrix R0T is the n  1 rank matrix
that has the least sum of squared distance from R⊥i .
Step 2: To calculate R0T we first perform singular value
decomposition (SVD) [36,37] of R⊥i
form:
Pm  n and n  n orthonormal matrices,
is an n  n non-negative diagonal
matrix whose diagonal elements si ðs1  s2  .  sn Þ are
called singular values. According to the Eckart-Young
Matrix Approximation Theorem [38,39] the matrix R0T of
rank N  1 that provides the best approximation of the
mn (in terms of the least-squares, i.e., P
norm) is calculated by setting the least singular value in
(sn ) to zero and then multiplying the modified S with U
connection coefficients, calculated using the TLS
method (Figure 3). Each kinase of the MAPK pathway
(RAF, MEK and ERK) was perturbed in multiple replicates, using siRNAs. The data from replicate experiments were used to calculate probability distributions of
the global responses of the RAF, MEK and ERK kinases.
These distributions were used to randomly sample a
large number of global response matrices Rkj . Subsequently, using each of these matrices, a local response
matrix rik0 , containing connections between RAF, MEK
and ERK, was calculated using TLS [23]. This resulted
in many realizations of the local response matrices rik0 ,
which were used to estimate their mean and confidence
intervals. Using this approach, Santos et al. revealed that
epidermal and neuronal growth factors induce proliferation and differentiation via topologically different
MAPK pathways in PC12 cells [26].
Handling insufficient data using the maximum
likelihood and nonlinear regression methods
TLS-based methods require the number of perturbations to be equal or exceeding the number of network
nodes. This is not always possible to achieve, due to the
lack of specific inhibitors or siRNAs and other constraints. Klinger et al. [25] formulated a likelihood
function, which quantifies the likelihood of a global
response matrix, R ¼ fRik ; i; k ¼ 1; .; ng, given a
Step 3: Since the nth singular value of R0T is zero, the
product of R0T and the nth column of V T is also zero.
Therefore, the nth column (V n ) of V T provides the solution to Eq. (9). Since the ith element of the connec0T
i is  1, r i can be obtained from the
last column (V ) of V by dividing it on the negative of
its ith element (V in ), i.e.
Estimating confidence intervals of the local response
coefficients using Monte Carlo simulations
Santos et al. [26] used Monte-Carlo simulations to estimate confidence intervals for the optimal values of
Overview of MC-TLS-MRA (Monte Carlo – Total Least Squares –
MRA) algorithm. Noisy input data can provide estimates of the probability
distribution for input data (matrix R). Monte Carlo sampling and TLS-MRA
are used to estimate the probability distribution for the local response
(connection coefficient) matrix (r).
16 Mathematical modelling
connection coefficient matrix, r ¼ frik ; i; k ¼ 1; .; ng.
The LevenbergeMarquardt optimization was used to
find an optimal connection coefficient matrix that
maximizes the likelihood of the measured global
response coefficients. This method was used to find
connections between eight key proteins of the ERK and
AKT pathways in five genetically different colon cancer
cell lines [25]. The perturbation data were generated by
treating each cell line with four different inhibitors
followed by epidermal growth factor receptor (EGFR)
and insulin-like growth factor 1 receptor (IGF1R)
stimulation [25]. The maximum likelihood-based
approach [25] successfully revealed different wiring of
the ERK and AKT pathways among different cell lines,
suggesting that this method can reconstruct networks
using smaller number of perturbation experiments than
required by the original and TLS-based MRA methods.
However, this maximum likelihood method is computationally intensive and does not scale well to larger
networks (e.g., for n > 20) [17].
Estimation of connection coefficients from noisy and
insufficient data using Bayesian statistics
We developed a Bayesian reformulation of MRA, termed
BMRA [14,17]. BMRA allowed us to estimate the nonzero connection coefficients, using smaller number of
perturbation experiments than required by the original
and TLS-based MRA methods, by using prior knowledge about network circuitry. Overview of network
reconstruction procedure using BMRA is presented in
Figure 4.
First, we rewrote the original MRA equation (Eq. (8)),
as follows:
Here, Aik are binary variables; Aik = 1 if rik s 0, and
Aik = 0 if rik = 0; εij is the imbalance in the original MRA
Overview of BMRA algorithm. Perturbation datasets and prior network topology are used to infer the connection coefficient matrix of a regulatory
network.
equation (Eq. (8)) caused by noise, i.e. an error variable.
The binary variables Aik, i,k = 1, ., n form a n  n
matrix, known as the adjacency matrix of a network. The
i th row of the adjacency matrix, i.e. the vector Ai = {Ai1,
Ai2, ., Ain}, indicates which of the network nodes
directly influence node i. The error variables are
assumed to be independently and identically distributed Gaussian random variables with 0 mean and unknown variance s2 , i.e. εik wN ð0; s2 Þ. Since an exact
value of the error variance (s2 ) in unknown, we assumed
that it is a random variable with inverse Gamma distribution, i.e. s2 wIGða; bÞ, where a and b are the location
and scale parameters. Following common practice, we
chose a ¼ 1, b ¼ 1. In further equations, we refer to
this distribution as Pðs2 Þ.
Bayesian statistics is applied to update prior estimates of
the binary vector Ai = {Aik}, k = 1, ., n and the vector
of connection coefficients ri = {rik}, k = 1, ., n to
obtain posterior estimates of these variables using the
experimental data, namely, the global response matrix
R ¼ Rik (Eq. (6)),
P Rjr i ; A i ; s2 P r i jA i ; s2 PðA i ÞP s2
Here, PðRjr i ; A i ; s2 Þ is the likelihood function of the
global response matrix R, given a connection coefficient
vector r i and a binary vector Ai. Pðr i jAi ; s2 Þ and PðAi Þ
are the prior distributions of r i and Ai , respectively. The
denominator PðRÞ is defined as follows,
PðRÞ ¼ ∭ P Rjr i ; A i ; s2 P r i jA i ; s2 PðA i ÞP s2 d r i d A i d s2
A key to the BMRA methods is that the likelihood
function for the observed global response matrix R is
derived from MRA equations (Eq. (14)),
P Rjr i ; A i ; s2 ¼ N Ri RT
;
Here, Ri ¼ fRik ; ksig is the global response of node xi
to perturbations that do not directly affect xi , RT
global response matrix of the nodes (xj ; jsi) which
directly regulate node xi (i.e. xj ;jsi : Aij ¼ 1, and r  ¼
frij : Aij ¼ 1; jsig. N ðRi RT
ip r ; s I Þ designates the
normal distribution for Ri where the mean equals RT
and the variance s I .
The prior probability distribution PðA i Þ is obtained
using prior knowledge of biochemical pathways that is
gathered from the literature and databases, e.g. KEGG
(http://www.genome.jp/kegg/pathway.html),
REACTOME (http://reactome.org/), which store generic topological models of many pathways. These literaturebased topologies indicate which nodes likely regulate a
certain node i, thereby suggesting the potential configurations of Ai, and therefore non-zero coefficients r i . If
the prior knowledge tells us that the circuitry of connections directed towards node i is best described by the
vector A0i , then the prior probability of Ai can be given,
for instance, as PðAi Þfexpð  c$dH ðAi ; A 0i ÞÞ, where
dH ðAi ; A0i Þ is the Hamming distance between network
Ai and the reference network A 0i , c is a constant. Then,
the network circuitries that are consistent with the
reference network A0i built according the current
knowledge will have higher prior probabilities than the
circuitries that deviate from it. The prior probability
distribution Pðr i jA i ; s2 Þ of the connection strengths,
r i ¼ rij ; j ¼ 1; .; n, depends on the subnetwork circuitry (Ai ). If Aij = 0, the corresponding connection
coefficient rij is given zero value, and if Aij = 1, we
assume the Gaussian prior for rij that has the zero mean
and the variance that is determined using MRA equations (Eq. (8)) by the global responses of the nodes that
affect node i [14].
The denominator in Eq. (15) (see Eq. (16)) that normalizes the probability Pðr i ; A i ; s2 jRÞ cannot be obtained analytically. The posteriors were estimated using
Markov Chain Monte Carlo (MCMC) algorithm, which
iteratively explores different prior configurations of Ai
and r i and for each configuration calculates the nonnormalized posteriors in Eq. (15). The proportionality
constants are then estimated by summing over the nonnormalized posteriors (Eq. (15)) of all configurations of
Ai and r i visited by the MCMC algorithm after its
convergence. The posterior probability of Ai provides a
quantitative measure of how well a certain configuration
of Ai is supported by both prior knowledge and experimental data. The values and confidence intervals for the
corresponding connection coefficients are obtained from
the posterior probability of r i [14,17].
We used this method to study the ERK and AKT
pathways in five colon cancer cell lines, using the data
from Klinger et al. [25]. These data comprised measurements of phosphorylation changes in eight key
signaling proteins (AKT Ser473, ERK2 Thr185/Tyr187,
MEK1 Ser217/Ser221, p70S6K Thr421/Ser424, IGF1R
Tyr1131, GSK3a/b Ser21/Ser9, IkBa Ser32/Ser36, and IRS1 Ser636/Ser639) in response to separate treatments by
four inhibitor drugs (targeting MEK, PI3K, IKK and
GSK3a/b kinases) followed by stimulation with TGFa
(a ligand of EGFR) and IGF1 (a ligand of IGF1R).
Because the number of network nodes exceeded the
number of perturbations, we applied BMRA. To obtain
the prior probability distributions PðAi Þ, we used a
literature-based generic signaling network for EGFR
and IGF1R pathways that included all known
18 Mathematical modelling
interactions [14]. Using Eq. (15), the perturbation data
and the MCMC algorithm, we reconstructed 10 individual signaling networks activated in five CRC cell
lines (HCT116, HT-29, LIM1215, SW403, SW480) by
TGFa or IGF1. Each connection in these cell-specific
networks had a posterior probability distribution for its
strength (rik ) and existence (i.e., being negative or
positive, Aik s 0), from which the mean values and
confidence intervals were drawn. We found substantial
distinctions between BMRA-inferred networks for five
CRC cell lines, specifically in terms of the cross talks
between the ERK and AKT pathways and feedback
loops. For instance, p70S6K can induce a negative
feedback loop that inhibits IRS1 by phosphorylating its
inhibitory sites (Ser636 and Ser639). In cells stimulated
with either TGFa or IGF1, this negative feedback loop
was strongest in the networks reconstructed for
SW480 cells, slightly weaker in HCT116 cells and
almost negligible in other cell lines. Subsequent experiments corroborated these results, showing that the
p70S6K to IRS1 negative feedback was most prominent
in HCT116 and SW480 cells, but much weaker or nonexistent in HT29 and HKE3 cells. Both HCT116 and
SW480 have oncogenic KRAS mutations and are resistant to EGFR inhibitor drugs, which prompted us to
build mechanistic ODE models of CRC cells to explore
how this resistance can be potentially overcome, as
described in the next section.
The LevenbergeMarquardt Maximum Likelihood
MRA (LM-ML-MRA) and BMRA have a goal similar to
a main goal of compressed sensing methods in data
science e an efficient signal reconstruction using
underdetermined linear systems. These goals are
achieved by different means. For example, one formulation of BMRA [17] exploits the hypothesis of natural
sparsity of biological networks, similarly to a compressed
sensing approach. But a more recent implementation of
BMRA [14] uses the more precise, literature-based
knowledge about the network structure to handle
incompleteness of data.
Summarizing, BMRA requires smaller number of observations than the standard Bayesian inference
methods, because BMRA uses the data likelihood
function (Eq. (17)), which is based on the MRA equations (Eq. (14)). The network representation derived in
terms of the connection coefficients and the MRAbased likelihood function are key elements of BMRA
that determine efficiency of BMRA. The BMRA method
is computationally efficient due to two reasons: (a) the
direct regulators of each node are inferred separately,
allowing using multi-core computers, (b) the MCMC
algorithm efficiently explores most likely configurations
of Ai and ri without visiting all possible configurations of
these vector-variables. Benchmarking the BMRA algorithm [14,17] has shown it has higher accuracy and
robustness against noise, as well as better handling low
numbers of replicates and perturbation data than other
methods, based on Lasso regression [40,41], linear
matrix inequality [42] and the maximum likelihood
[25].
ODE model building using MRA and BMRA
Connection coefficients capture interactions between
network modules and indicate the type (activating or
inhibitory) and strength of these interactions. Because
MRA is designed to provide not merely correlational,
but causative links between network nodes, it enables
the derivation of ODE models for the network dynamics
[14]. However, calibrating model parameters using
steady state perturbation response data is not always
straightforward. In order to calibrate the model, one
needs to simulate as many perturbation experiments, as
given by the data [14]. These simulations are often
computationally intensive. A direct link between
connection coefficients and the ODE model allows us to
calibrate the model using these coefficients without
direct simulation of perturbation experiments [43]. The
link arises from the fact that the connection coefficients
(vxi/vxj) are essentially the elements of the Jacobian
matrix “normalized” by its diagonal elements, see Eq.
(5). Given the model equations, the connection coefficients can be calculated analytically or numerically
by differentiating the rate functions of the ODE system,
without simulating perturbation experiments. The
model parameters are then fitted to minimize the
discrepancy between the calculated and the MRAinferred connection coefficients. Thus, a nonlinear
ODE model can be developed, based on the MRA
output. The kinetics of many enzymatic reactions can
be described by nonlinear MichaeliseMenten expression, and calibrating parameters of these model equations amounts to finding MichaeliseMenten parameter
values, resulting in the same connection coefficients
matrix as inferred from perturbation data. For instance,
based on the BMRA-inferred signaling networks, we
developed mechanistic models of the EGFR and IGF1R
networks in HCT116 cells [14]. The model parameters
were fitted using a Bayesian mechanistic modelling algorithm (BMM) that iteratively compared the simulated connection coefficients among IGFR, IRS, AKT,
MEK, ERK, and p70S6K with those estimated by the
BMRA algorithm. BMM generated an ensemble of ODE
models, each of which was fitted with parameter values
sampled from the corresponding posterior distribution.
We then used the average and standard deviation of the
ensemble simulations to represent simulation results
and the corresponding confidence intervals. Our models
predicted and experiments in HCT116 cells confirmed
that a moderate inhibition of p70S6K which decreases
the strength of the negative feedback from p70S6K to
IRS1 restored the sensitivity of phosphorylated and
active AKT to EGFR inhibitors [14]. In addition to CRC
cell line, this a bit surprising prediction was
experimentally validated in a zebrafish (Danio rerio)
xenograft model [14].
If a module contains more than a single protein or gene,
the ODE model will include equations for intermediate
species, intrinsic to this module. For such a module i, we
designate its communicating species by xi and other
independent intermediate species in this module by yik,
k = 1, ., mi. Then the ODE model takes the form,
dxi =dt ¼ 4i x1 ; .; xn ; yi1 ; .; yimi ; p
dyik =dt ¼ mik x1 ; .; xn ; yi1 ; .; yimi ; p
Because yi ¼ yik are internal species to module i, yik do
not participate in reactions that belong to the other
modules. Differentiating mik ðx1 ; .; xn ; yi1 ; .; yimi ; pÞ ¼
0 at the steady state with respect to xj, we obtain,
vmik x1 ; .; xn ; yi1 ; .; yimi ; p
,
¼ 0; i ¼ 1; .; n;
This is a linear system of m1 þ . þ mn equations for
vyil =vxj which we substitute in the following equations:
vfi x1 ; .; xn ; yi1 ; .; yimi ; p
