# **AI-guided discovery of atypical protein assemblies**

AmirAli Toghani1 †, Benjamin A. Seager<sup>1</sup> †, Yu Sugihara1 , Lisa-Marie Roijen1 , Juan M. Azcue1 , Maián Garro1 Maryam Sargolzaei1 , Ioanna Morianou1 , Adeline Harant1 , Sam Gallop2 , Jiorgos Kourelis3 , Dan MacLean1 , Mauricio P. Contreras4,5, Sophien Kamoun1 \*, Daniel Lüdke1 \*

,

- 1. The Sainsbury Laboratory, University of East Anglia, Norwich Research Park, Norwich, UK.
  - 2. Norwich BioScience Institutes, Norwich Research Park, Norwich, UK.
  - 3. Department of Life Sciences, Imperial College, London, United Kingdom.
- 4. Department of Plant Biochemistry, Center for Plant Molecular Biology (ZMBP), Eberhard Karls University, Tübingen, Germany.
  - 5. Cluster of Excellence GreenRobust, Eberhard Karls University, Tübingen, Germany.

† Authors contributed equally to this work.

\*To whom correspondence should be addressed[: Daniel.Luedke@tsl.ac.uk](mailto:Daniel.Luedke@tsl.ac.uk) an[d Sophien.Kamoun@tsl.ac.uk](mailto:Sophien.Kamoun@tsl.ac.uk)

## **Abstract**

Artificial intelligence (AI) systems such as AlphaFold have transformed structural biology by enabling accurate prediction of protein structures. However, their capacity to uncover new classes of macromolecular assemblies remains largely untapped. We developed the Structural Novelty Index (SNI), a quantitative framework for identifying protein complexes that diverge from canonical architectures. As one implementation of SNI, we developed SNI*NRC-Hexa*, to identify unconventional resistosomes formed by nucleotide-binding, leucinerich repeat immune receptors (NLRs). We used it to analyze AlphaFold 3 models of 637 nonredundant NRC proteins from 346 genomes representing 85 plant species. This analysis identified candidates with predicted architectures distinct from the canonical hexameric resistosomes of NRC proteins. Biochemical purification and negative-stain transmission electron microscopy of NRC7 orthologs from multiple species supported the SNI prediction and revealed an unexpected undecameric (11-mer) assembly. Our results establish SNI as a scalable approach for discovering atypical protein complexes.

## **Main Text**

Most proteins function as dynamic assemblies that underpin cellular homeostasis and physiology. AI-driven structural prediction has largely solved the protein folding problem, transforming structural biology (*1*, *2*), yet its potential to discover higher-order protein assemblies remains only 5 partly realised. In particular, tools such as AlphaFold have been underused for identifying atypical or unrecognized macromolecular architectures, leaving much of the cellular assembly landscape unexplored. Here, we present an AI-guided framework to systematically identify and prioritize unexpected protein assemblies and apply it to the discovery of atypical oligomeric assemblies of nucleotide-binding leucine-rich repeat (NLR) proteins.

10 NLRs are intracellular immune receptors encoded in organisms across the tree of life, from bacteria and fungi to plants and animals (*3*–*6*). Upon activation, NLRs undergo oligomerization into supramolecular complexes—termed inflammasomes in animals and bacteria and resistosomes in plants—that function as signaling platforms or membrane channels to initiate defence responses. In plants, NLRs represent one of the most expansive and diverse protein families, roughly comprising 15 1% of plant proteomes (*7*). Phylogenetic analyses revealed multiple distinct clades that assemble into resistosomes with defined stoichiometries, including tetrameric, pentameric, hexameric, and octameric architectures (*8*–*14*). One clade of coiled-coil NLRs (CC-NLRs) comprises the NRCs (NLR required for cell death), a deep lineage of helper NLRs that function downstream of pathogendetecting receptors known as NRC-dependent sensors (NRC-S) (*15*). The NRC superclade groups 20 the helper NRCs and two sister clades of NRC-S (*16*–*18*). This lineage emerged more than 100 million years ago and extensively diversified in asterid plants, particularly in the Solanaceae, where they form complex immune receptor networks that confer resistance against a wide range of pathogens and pests (*17*–*20*). Upon activation by their cognate NRC-S partners, NRC helpers oligomerize into homohexameric resistosomes that function as calcium-permeable channels (*11*, *21*). 25 Although the cryo-EM structures of three hexameric NRCs, NbNRC2a, SlNRC3, and NbNRC4c, have been experimentally resolved, the extent to which these structures define common principles of NRC immune receptor channels remains unknown.

We previously reported that AlphaFold 3 can predict with high confidence the architecture of hexameric NRC resistosomes and related plant NLR assemblies, including accurate modeling of 30 the very N-terminal α1 helix of CC-NLRs—a structurally elusive region that has proven difficult to resolve experimentally (*11*). We reasoned that AlphaFold 3 could be deployed not only for structural prediction, but also as a discovery engine to classify NLRs into architectural categories and flag candidates with atypical assemblies (*11*, *17*, *22*). To avoid manual classification and provide a more

scalable, less subjective approach, we developed the Structural Novelty Index (SNI), a quantitative 35 metric that distinguishes unconventional from canonical protein complexes based on prior knowledge. Here, we tested this concept by developing and implementing a specific SNI, SNI*NRC-Hexa*, aimed at evaluating AlphaFold 3 models of NRC hexamers.

### **SNI can distinguish canonical NRC hexamers from unconventional assemblies**

40 To define the SNI*NRC-Hexa* parameters and capture the properties of hexameric NLR resistosomes, we combined features defined by human experts with features generated by the AI system co-scientist (*23*) (Figure S1; Data S1). We retained 11 parameters that assess model confidences and interprotomer interfaces (ipTM*LCB*, ∑*CONTACTS*, BSA*INTER-PROTO*), resistosome ring symmetry (D*APEX*, σ*<sup>θ</sup> ROT*, S*PROTO*), distance between MHD and P-loop motifs (D*MHD-P*), CC-domain hydrophobicity (H*ABS*), N-45 terminal α1-helix length (L*APEX*), angle (φ*APEX*), and amphipathic moment (µ*H*) (Figure S1; Data S1).

We benchmarked SNI*NRC-Hexa*, based on the prior knowledge that NRC helper proteins assemble into hexameric resistosomes, but their phylogenetically related NRC-S fail to do so (*17*, *24*, *25*). To this end, we put together a benchmark dataset consisting of i) known hexameric NRCs: NbNRC2a, SlNRC3, and NbNRC4c and their orthologs from the Solanaceae (nightshade) family, and 50 ii) NRC-S proteins selected from across the phylogenetic clade (*14*, *26*, *27*). We used AlphaFold 3 to model this set of 18 proteins as hexamers with 25 oleic acids as a stand-in for the plasma membrane, generating three replicates per sequence. All structural predictions of the nine helper proteins aligned with their respective cryo-EM structures with RMSDs below 1 Å (Figure S2), confirming the high accuracy of AlphaFold 3 in modeling NRC resistosomes.

55 Next, we computed the SNI*NRC-Hexa* parameters for the 18 structural models and performed hierarchical clustering based on the SNI*NRC-Hexa* parameters (Figure 1A). This resulted in two distinct clusters clearly separating the NRCs from NRC-S proteins. We conclude that SNI*NRC-Hexa* can distinguish AlphaFold 3 models of NRC hexamers from unconventional assemblies.

#### 60 Figure 1. The Structural Novelty Index discriminates between NRC helper vs. sensor predictions.

(A) Quantification of structural divergence via the tailored Structural Novelty Index (SNI*NRC-Hexa*) for hexameric NRC resistosomes. The parameters assess model confidences and inter-protomer interfaces (ipTM*LCB*, ∑*CONTACTS*, BSA*INTER-PROTO*), resistosome ring symmetry (D*APEX*, σ*<sup>θ</sup> ROT*, S*PROTO*), MHD-P-loop motif distance (D*MHD-P*), hydrophobicity of CCdomain (H*ABS*), and N-terminal α1-helix length (L*APEX*), angle (φ*APEX*), and amphipathic moment (µ*H*). Source of the 65 parameters is indicated on the right. SNI*NRC-Hexa* calculated for three NRCs with experimentally resolved resistosome structures (NRC2, NRC3, and NRC4c; highlighted red) and two orthologs from each phylogenetic clade. Nine NRC-S NLRs were used as outgroups. Hierarchical clustering of z-score normalized SNI*NRC-Hexa* values for the 18 predicted hexamers show a clear distinction between NRC resistosomes and NRC-S hexamers. LbNRC4 and NRC-S, lacking a detectable MADA motif, could not be scored for α1-helix-dependent metrics. In NbNRC4c and NtNRC4, the α1 helix 70 collapsed inward despite the NB-ARC domain forming a high-confidence resistosome ring (Figure S3), leading to higher

D*APEX* values. All proteins were modeled in three replicates with 25 oleic acids as a stand-in for the plasma membrane. Nb: *Nicotiana benthamiana*, Nt: *Nicotiana tabacum*, Sl: *Solanum lycopersicum*, Ca: *Capsicum annuum*, Lb: *Lycium barbarum*. (B) AlphaFold3-predicted hexameric resistosome complexes for representative helper and sensor NLRs. While helper NLR predictions showed resistosome-like ring structures, sensor NLRs were predicted with low confidence and no meaningful 75 structure. RMSD values for helper structures are against their respective cryo-EM structures (NbNRC2a: 9FP6; SlNRC3: 9RI9). Structures were aligned with the ChimeraX matchmaker command (*28*). Pruned RMSD scores are reported (model with seed = 1 is visualized).

### **SNI predicts NRC proteins with unconventional assemblies**

80 To identify unconventional NRC resistosomes, we expanded our analysis to all available NRC protein sequences in the Solanaceae family. We reannotated 346 Solanaceae genomes from 85 species and extracted 197,834 NLR proteins from a total of 15,079,126 proteins (*29*). From this dataset, 2,658 sequences belonged to the well-defined NRC phylogenetic clade, which we further reduced to 637 non-redundant sequences spread over 18 distinct phylogenetic clades (Data S3). We 85 used AlphaFold 3 to model these NRC sequences as hexamers, in three replicates and with 25 oleic acid molecules as a proxy for the plasma membrane (*30*). We calculated SNI*NRC-Hexa* for all 637 predicted structures (Figure S4; Data S4). To minimize intra-clade variability, we computed a penalized mean score for each NRC clade (Data S5). The resulting matrix was normalized using Zscores, followed by hierarchical clustering to identify divergent NRC clades based on SNI*NRC-Hexa*.

90 The NRC2, NRC3, and NRC4other phylogenetic clades—each containing sequences with empirical hexameric structures—formed a core cluster encompassing 13 of the 18 NRC clades. These clades generally exhibited high mean ipTM scores and similar resistosome geometry profiles (Figure 2A). The remaining five clades diverged from the core cluster for several parameters. Among these, NRC4u and NRC7 showed the lowest mean ipTM scores (Figure 2A; Data S5) and 95 displayed a markedly reduced number of inter-protomer contacts within these clades (Figure 2B). Inspection of representative models from the two most divergent clades with low ipTM scores (NRC4u and NRC7) revealed contrasting patterns. NRC4u clade sequences did not exhibit resistosome-like assemblies (Figure 2C). In contrast, despite similarly low ipTM scores, NRC7 clade models exhibited resistosome-like assemblies (Figure 2C). Notably, members of the adjacent 100 NRC6 clade—closely related to NRC7 both phylogenetically and by hierarchical clustering generally modeled with higher confidence and displayed canonical hexameric resistosome architectures, albeit with an inwardly collapsed α1 helix (Figure 2B & 2C).

Figure 2. SNI predicts NRC proteins with unconventional assemblies.

105 (A) A hierarchical clustering of NRC clades based on the specialized SNI*NRC-Hexa*. This framework uses a combination of scientist-defined and AI-generated parameters to prioritize assemblies that deviate from canonical architectures. The parameters assess model confidences and inter-protomer interfaces (ipTM*LCB*, ∑*CONTACTS*, BSA*INTER-PROTO*), resistosome ring symmetry (D*APEX*, σ*<sup>θ</sup> ROT*, S*PROTO*), MHD-P-loop motifs distance (D*MHD-P*), hydrophobicity of CC-domain (H*ABS*), and N-

terminal α1-helix length (L*APEX*), angle (φ*APEX*), and amphipathic moment (µ*H*). Values are Z-scored by clade mean, with 110 red indicating higher and blue indicating lower relative scores. Hierarchical clustering was applied to NRC clades. NRC clades with empirical structures form a core cluster (highlighted grey) with similar resistosome geometry and confidence profile. Five clades clustered outside of the core cluster with NRC4u and NRC7 having the lowest confidence scores (ipTM*LCB*). NRC clades with empirical structures are in highlighted red. (B) Stacked bar chart of inter-protomer contact counts for each resistosome, shown on the phylogenetic tree of NB-ARC sequences from 637 NRC sequences. Numbers 115 next to the nodes indicate bootstrap values. Contacts classified by interaction type: hydrogen bonds, salt bridges, hydrophobic interactions, disulfide bonds, and van der Waals contacts. NRC7 and NRC4u clade NLRs show very low contact numbers compared to other NRC clades. (C) Representative structures from NRC2, NRC4u, NRC6, and NRC7 clades (seed = 1, with 25 oleic acids as a stand-in for the plasma membrane). AlphaFold 3 failed to predict resistosome-like structures for NRC4u clade NLRs.

### **Activated NRC7 proteins form an undecameric (11-mer) resistosome**

120

SNI*NRC-Hexa* analysis identified NRC7 as the largest clade predicted to be structurally unconventional. We therefore hypothesized that NRC7 proteins assemble into a complex distinct from the canonical hexameric NRC resistosome. To test whether potato NRC7 (*Solanum tuberosum*; StNRC7) can 125 trigger immune cell death, we introduced a point mutation in the MHD motif (D498V, hereafter StNRC7DV), a substitution known to confer autoactivity (*31*)(Figure 3A and 3B). Transient expression of StNRC7DV, but not wild-type StNRC7, in leaves of the model plant *Nicotiana benthamiana* induced a cell death response comparable to that triggered by the previously described autoactive SlNRC3DV (Figure 3C) (*14*).

To enable purification of the autoactive StNRC7DV 130 mutant for structural analysis, we introduced additional mutations in the MADA motif (L20E, L24E, L28E) of the N-terminal α1 helix, which have previously been used to abolish NRC-mediated cell death without disrupting resistosome assembly (*24*, *32*) (Figure 3B and 3C). We expressed StNRC7EEE+DV protein in leaves of *N. benthamiana* and subjected it to a previously described immunoprecipitation-electron 135 microscopy (IP-EM) workflow (*26*). We harvested leaves 2 days after infiltration, and purified StNRC7EEE+DV by strep-tag affinity purification before assessment by negative-stain electron microscopy (nsEM). The nsEM micrographs revealed distinct ring-shaped particles of ~250 Å in diameter, substantially larger than the ~150 Å diameter expected for a canonical hexameric resistosome (Figure 3D). Two-dimensional (2D) classification resolved a clear ring-shaped 140 structure with features consistent with a resistosome. Counting the peripheral densities, which

likely correspond to the LRR domains, identified the complex as an atypical assembly composed of 11 protomers (Figure 3D & 3E).

Figure 3. Activated NRC7 proteins form 11-mer resistosome complexes.

(A) Schematic of the agroinfiltration assay used to test NRC7-triggered cell death. Potato NRC7 (*Solanum*  145 *tuberosum*; StNRC7) was cloned into a binary expression vector and transiently expressed in *N. benthamiana* leaves by Agrobacterium-mediated transformation. (B) Schematic of StNRC7 showing a tripartite domain structure. The positions of the MADA and MHD motifs, and the mutant variants generated to produce an activated protein that no longer induces cell death are indicated. (C) Cell death induced by the autoactive StNRC7DV is abolished by additional mutations in the MADA motif (StNRC7EEE+DV). Agrobacterium strains 150 carrying the indicated constructs were infiltrated into leaves of 4-week-old *N. benthamiana* plants at OD600 of 0.3. SlNRC3DV was used as a positive control for cell death. Spots with cell death have red circles. Photographs were taken 5 days post infiltration. (D) Negative-stain electron micrograph of StNRC7EEE+DV showing large ring-shaped particles (white arrows). (E) Negative-stain 2D class average of StNRC7EEE+DV revealing an 11 protomer assembly. Scale bar, 60 Å.

### 155 Additional members of the NRC7 clade form 11-mer assemblies

To determine whether the atypical 11-protomer architecture of the StNRC7 resistosome is a broader feature of the NRC7 clade, we examined NRC7 orthologs from tomato (*Solanum lycopersicum*, SlNRC7) and *N. benthamiana* (NbNRC7), which represent distinct branches of this clade (Figure 4). We expressed and purified MADA-mutated autoactive variants of SlNRC7 and NbNRC7 (SlNRC7EEE+DV and NbNRC7EEE+DV 160 , respectively) from *N. benthamiana* leaves and analyzed them by negative-stain electron microscopy. Like StNRC7, both SlNRC7 and NbNRC7 formed resistosomelike 11-mer assemblies (Figure 4). These findings indicate that 11-protomer resistosomes are a conserved structural feature of the NRC7 clade, in marked contrast to the canonical hexameric resistosomes formed by NbNRC2a, SlNRC3, and NbNRC4c.

### **Co-scientist complements human-defined SNI parameters**

165

The SNI framework provides an objective pipeline for discovering atypical protein assemblies and should be scalable across a broad range of protein complexes (Figure 5). Incorporating the AI system co-scientist (*23*) may further enhance this scalability and accelerate analysis. Human experts 170 defined eight SNI parameters, whereas co-scientist proposed seven, four of which overlapped with the expert-defined set and three of which were unique (Figure 1A & S1). To assess how informative the analysis would have been using AI-generated features alone, we directly compared the humandefined and co-scientist-derived parameter sets and performed hierarchical clustering with each set independently (Figure S5 & S6). In the benchmark analysis, neither parameter set matched the 175 performance of the combined SNI*NRC-Hexa*, which perfectly separated NRC and NRC-S models into distinct clusters (Figure 1A & S5). Using either parameter set alone led to one misclassification: NbNRC4c with the human-defined parameters and Rpa1 with the co-scientist-derived parameters. In the full dataset of 637 NRC proteins, both analyses identified NRC7 as atypical (Figure S6). However, whereas the human-defined parameters placed only three proteins outside the "hexamer" 180 cluster containing NRC2, NRC3, and NRC4, the co-scientist-derived analysis provided greater granularity and identified four clades as unconventional (Figure S6). Although future experimental work will be needed to determine how many of these candidates are truly non-canonical, these results indicate that the co-scientist-derived parameters alone would have been sufficient to flag NRC7 as distinct from the core hexameric resistosome architecture.

Figure 4. Additional NRC7 clade proteins form 11-mer resistosome assemblies.

(A) Phylogeny of the NRC7 clade, with NRC2, NRC3 and NRC4 included as outgroups. Outgroups and genera are coloured accordingly. The scale bar represents 0.1 substitutions per site, and numbers on branches indicate bootstrap support values. The ipTM score for each AlphaFold3 hexamer model (seed = 1) is shown at the tips of the phylogeny (B) Negative-stain 2D class averages of StNRC7EEE+DV 190 (from Figure 3E), SlNRC7EEE+DV, and NbNRC7EEE+DV, showing similar 11-mer oligomeric states. The hexameric resistosome SlNRC3EEE, activated by the NRC-S protein Rx in response to *Potato virus X* coat protein (CP) (*14*), is included for comparison as an outgroup assembly. Scale bar, 60 Å, in all images.

185

## **Discussion**

This work shows how integrating AI-driven structural prediction with electron microscopy can accelerate the classification of complex protein families and reveal atypical macromolecular assemblies. To avoid manual classification and establish a more scalable, less subjective approach, 200 we developed the Structural Novelty Index (SNI), a quantitative metric that distinguishes unconventional from canonical protein complexes on the basis of prior knowledge. This AI-guided framework enables the systematic discovery of previously unrecognized assembly architectures and provides a general strategy for identifying atypical protein assemblies (Figure 5).

Applying a bespoke SNI to AlphaFold 3 predictions spanning the expanded phylogenetic 205 diversity of the NRC family uncovered previously unrecognized structural variation within this wellstudied class of plant immune receptors (Figures 3 and 4). Because cryo-EM analyses had shown that three NRC family members form hexameric resistosomes (*11*, *12*, *14*), it would have been natural to infer that the same architecture extends across the family. Instead, SNI highlighted candidate atypical NRCs and guided the experiments that uncovered the unexpected 11-mer resistosome 210 stoichiometry of NRC7 proteins.

Although predictive workflows often prioritize high-confidence models for structural interpretation, our findings show that low-confidence predictions can also be informative by flagging candidates that deviate from canonical assemblies and warrant experimental investigation. This emphasis on successful predictions can create a form of survivorship bias, whereby low-215 confidence or failed models are overlooked even though they may carry biological meaning. NRC7 clade members consistently failed to produce confident hexameric models, and modeling across alternative oligomeric states from 5-mers to 11-mers likewise did not yield confident assemblies (Figure S7). Rather than treating such models as disposable failures, they can highlight outliers to prioritize candidates for experimental structural analysis, thereby countering this bias in 220 conventional modeling workflows. More broadly, SNI extends beyond low-confidence predictions by quantitatively and objectively flagging structural models that diverge from canonical assemblies across multiple parameters.

The undecameric NRC7 resistosome was unexpected. So far, plant CC-NLR resistosomes that have been functionally characterized appear to act as calcium-permeable channels (*11*, *21*, *33*). 225 Whether the NRC7 11-mer retains this activity or whether its larger assembly state channels other ions or small molecules is an open question. Future work will determine the properties of this complex and test the extent to which the structural expansion of the NRC7 resistosome is linked to functional innovation.

Co-scientist independently recovered several structural parameters identified by human 230 experts and contributed additional features that enhanced the granularity of the analysis. Together, these findings point to a near-term future in which agentic AI systems complement expert researchers to accelerate the development of bespoke SNI frameworks for diverse protein assemblies. This complementarity could also broaden access to structural discovery by enabling teams without extensive in-house structural biology expertise to generate and benchmark useful 235 parameter sets more efficiently.

Figure 5. AI-guided discovery of unconventional protein assemblies.

Schematic overview of the five-step pipeline for identification of atypical macromolecular architectures, applied here to the NRC family of plant immune receptors. Step 1: Large-scale genome mining and phylogenomics to extract and curate a 240 non-redundant set of candidate protein sequences. Step 2: AlphaFold 3 modeling of all candidates in a defined reference assembly state. Step 3: A Structural Novelty Index (SNI) is constructed by integrating parameters from both human experts and the AI co-scientist system to quantitatively distinguish canonical from unconventional assemblies. Step 4: SNI-based clustering to classify candidates as canonical or atypical, flagging outliers that deviate from the expected assembly geometry. Step 5: Top candidates are subjected to experimental validation through recombinant expression, 245 affinity purification, and electron microscopy to enable the discovery of previously unrecognized assembly architectures.

## **Author contributions**

Conceptualization: D.L., S.K., A.T., B.S.

Methodology: A.T., B.S., D.L.

Data curation: A.T., B.S., Y.S., D.L.

250 Formal analysis: A.T., B.S., D.L.

Investigation: A.T., B.S., D.L., L.-M.R., J.M. A., M.G., I.M., M.P.C., M.S., A.H.

Resources: S.G., D.M., Y.S., M.P.C., J.K.

Writing—original draft: A.T., S.K., D.L., B.S.

Writing—review and editing: A.T., S.K., D.L., B.S., M.P.C., D.M., J.K., Y.S.

255 Visualization: A.T., B.S., D.L.

Supervision: S.K., D.L., B.S.

Project administration: S.K., D.L.

Funding acquisition: S.K.

## <sup>260</sup> **Competing interests**

S.K. receives funding from industry for NLR biology and has co-founded a start-up company (Resurrect Bio Ltd.) related to NLR biology. B.S., M.P.C., J.K., and S.K. have filed patents on NLR biology.

# <sup>265</sup> **Data and materials availability**

Additional supplementary material and scripts are available at

[https://github.com/amiralito/SolNRCH\\_foldome.](https://github.com/amiralito/SolNRCH_foldome) Genome annotations and sequence data are available at<https://doi.org/10.5281/zenodo.19855162> (*29*). Predicted structures are available at <https://doi.org/10.5281/zenodo.19860917> (*30*).

# **Acknowledgements**

270

We thank Andrés Posbeyikian (TSL) for comments and input on the analysis, Jake Richardson for support with electron microscopy, Hsuan Pai for her plant schematic drawings in figure 3, and all TSL support staff and Horticultural Services for preparing and providing plants and media. D.L. 275 thanks Nigel Tufnel for inspiration.

## **Funding**

We acknowledge funding from the Gatsby Charitable Foundation, Biotechnology and Biological 280 Sciences Research Council (BBSRC) BB/P012574 (Plant Health ISP), BBSRC BBS/E/J/000PR9795 (Plant Health ISP - Recognition), BBSRC BBS/E/J/000PR9796 (Plant Health ISP - Response), BBSRC BBS/E/J/000PR9797 (Plant Health ISP – Susceptibility), BBSRC BBS/E/J/000PR9798 (Plant Health ISP – Evolution), European Research Council (ERC) 743165, Engineering and Physical Sciences Research Council EP/Y032187/1 and Google.org (Bifrost). Y.S. and S.K. acknowledge 285 funding from The Khalifa Center for Genetic Engineering and Biotechnology. M.P.C. acknowledges support by the state of Baden-Württemberg through bwHPC Helix (RV [bw25K002\)](https://zas.bwhpc.de/shib/info_rv.php?p_acronym=bw25K002) and the German Research Foundation (DFG) through grant INST 35/1597-1 FUGG.

# **References**

- 290 1. J. Jumper, R. Evans, A. Pritzel, T. Green, M. Figurnov, O. Ronneberger, K. Tunyasuvunakool, R. Bates, A. Žídek, A. Potapenko, A. Bridgland, C. Meyer, S. A. A. Kohl, A. J. Ballard, A. Cowie, B. Romera-Paredes, S. Nikolov, R. Jain, J. Adler, T. Back, S. Petersen, D. Reiman, E. Clancy, M. Zielinski, M. Steinegger, M. Pacholska, T. Berghammer, S. Bodenstein, D. Silver, O. Vinyals, A. W. Senior, K. Kavukcuoglu, P. Kohli, D. Hassabis, Highly accurate protein structure prediction 295 with AlphaFold. *Nature 2021 596:7873* 596, 583–589 (2021).
- 2. J. Abramson, J. Adler, J. Dunger, R. Evans, T. Green, A. Pritzel, O. Ronneberger, L. Willmore, A. J. Ballard, J. Bambrick, S. W. Bodenstein, D. A. Evans, C.-C. Hung, M. O'Neill, D. Reiman, K. Tunyasuvunakool, Z. Wu, A. Žemgulytė, E. Arvaniti, C. Beattie, O. Bertolli, A. Bridgland, A. Cherepanov, M. Congreve, A. I. Cowen-Rivers, A. Cowie, M. Figurnov, F. B. Fuchs, H. Gladman, 300 R. Jain, Y. A. Khan, C. M. R. Low, K. Perlin, A. Potapenko, P. Savy, S. Singh, A. Stecula, A. Thillaisundaram, C. Tong, S. Yakneen, E. D. Zhong, M. Zielinski, A. Žídek, V. Bapst, P. Kohli, M. Jaderberg, D. Hassabis, J. M. Jumper, Accurate structure prediction of biomolecular interactions with AlphaFold 3. *Nature*, 1–3 (2024).
- 3. M. P. Contreras, D. Lüdke, H. Pai, A. Toghani, S. Kamoun, NLR receptors in plant immunity: 305 making sense of the alphabet soup. *EMBO reports* 24, e57495 (2023).
  - 4. Z. Hu, J. Chai, Assembly and Architecture of NLR Resistosomes and Inflammasomes. *Annual Review of Biophysics* 52, 207–228 (2023).
- 5. Z. Duxbury, C. Wu, P. Ding, A Comparative Overview of the Intracellular Guardians of Plants and Animals: NLRs in Innate Immunity and Beyond. *Annual Review of Plant Biology* 72, 155–184 310 (2021).
  - 6. B. Sundaram, R. E. Tweedell, S. P. Kumar, T.-D. Kanneganti, The NLR family of innate immune and cell death sensors. *Immunity* 57, 674–699 (2024).
  - 7. A. Toghani, S. Kamoun, Functional annotation of 180 RefSeq reference plant proteomes reveals a dataset of 113,684 NLR proteins, Zenodo (2024); https://doi.org/10.5281/zenodo.13627395.
- 315 8. J. Wang, M. Hu, J. Wang, J. Qi, Z. Han, G. Wang, Y. Qi, H. W. Wang, J. M. Zhou, J. Chai, Reconstitution and structure of a plant NLR resistosome conferring immunity. *Science* 364 (2019).
- 9. S. Ma, D. Lapin, L. Liu, Y. Sun, W. Song, X. Zhang, E. Logemann, D. Yu, J. Wang, J. Jirschitzka, Z. Han, P. Schulze-Lefert, J. E. Parker, J. Chai, Direct pathogen-induced assembly of an NLR 320 immune receptor complex to form a holoenzyme. *Science* 370 (2020).
  - 10. A. Förderer, E. Li, A. W. Lawson, Y. Deng, Y. Sun, E. Logemann, X. Zhang, J. Wen, Z. Han, J. Chang, Y. Chen, P. Schulze-Lefert, J. Chai, A wheat resistosome defines common principles of immune receptor channels. *Nature*, 1–8 (2022).
- 11. J. Madhuprakash, A. Toghani, M. P. Contreras, A. Posbeyikian, J. Richardson, J. Kourelis, T. O. 325 Bozkurt, M. W. Webster, S. Kamoun, A disease resistance protein triggers oligomerization of its NLR helper into a hexameric resistosome to mediate innate immunity. *Science Advances* 10, eadr2594 (2024).

- 12. F. Liu, Z. Yang, C. Wang, R. Martin, W. Qiao, J. E. Carette, S. Luan, E. Nogales, B. Staskawicz, The activated plant NRC4 immune receptor forms a hexameric resistosome. bioRxiv [Preprint] 330 (2023). https://doi.org/10.1101/2023.12.18.571367.
  - 13. G. Guo, H. Zhao, K. Bai, Q. Wu, L. Dong, L. Lu, Y. Chen, Y. Hou, J. Lu, P. Lu, M. Li, H. Zhang, G. Wang, K. Zhu, B. Huang, X. Cui, H. Fu, C. Hu, Z. Chu, X. Lyu, S. Kamoun, C. Wang, Z. Liu, M. Selvaraj, J. D. Jones, An activated wheat CCG10-NLR immune receptor forms an octameric resistosome. bioRxiv [Preprint] (2025). https://doi.org/10.1101/2025.08.26.672026.
- 335 14. B. A. Seager, A. Harant, M. P. Contreras, L.-Y. Hou, C.-H. Wu, S. Kamoun, J. Madhuprakash, A plant pathogen effector blocks stepwise assembly of a helper NLR resistosome. bioRxiv [Preprint] (2025). https://doi.org/10.1101/2025.07.14.664264.
- 15. C.-H. Wu, A. Abd-El-Haliem, T. O. Bozkurt, K. Belhaj, R. Terauchi, J. H. Vossen, S. Kamoun, NLR network mediates immunity to diverse plant pathogens. *Proceedings of the National*  340 *Academy of Sciences* 114, 8113–8118 (2017).
  - 16. K. Seong, E. Seo, K. Witek, M. Li, B. Staskawicz, Evolution of NLR resistance genes with noncanonical N-terminal domains in wild tomato species. *New Phytologist* 227, 1530–1543 (2020).
- 17. H. Pai, T. Sakai, A. Posbeyikian, R. Frijters, Y. Sugihara, M. P. Contreras, J. Kourelis, H. Adachi, 345 S. Kamoun, A. Toghani, A hierarchical immune receptor network in lettuce reveals contrasting patterns of evolution in sensor and helper NLRs. bioRxiv [Preprint] (2025). https://doi.org/10.1101/2025.02.25.639832.
- 18. D. Lüdke, T. Sakai, J. Kourelis, A. Toghani, H. Adachi, A. Posbeyikian, R. Frijters, H. Pai, A. Harant, J. C. Lopez-Agudelo, B. Tang, K. Ernst, M. Ganal, A. Verhage, C.-H. Wu, S. Kamoun, A 350 root-specific NLR network mediates immune signaling of resistance genes against plant parasitic nematodes. *Plant Cell* 37 (2025).
  - 19. F.-J. Goh, C.-Y. Huang, L. Derevnina, C.-H. Wu, NRC immune receptor networks show diversified hierarchical genetic architecture across plant lineages. *The Plant Cell*, koae179 (2024).
- 20. D. Lüdke, H. Pai, A. Toghani, A. Harant, C.-H. Wu, S. Kamoun, The autoactivity of tomato helper 355 NLR immune proteins of the NRC clade is unaltered in *Nicotiana benthamiana prf* mutants. *Plant Physiology* 199, kiaf506 (2025).
  - 21. F. Liu, Z. Yang, C. Wang, Z. You, R. Martin, W. Qiao, J. Huang, P. Jacob, J. L. Dangl, J. E. Carette, S. Luan, E. Nogales, B. J. Staskawicz, Activation of the helper NRC4 immune receptor forms a hexameric resistosome. *Cell*, S0092867424007736 (2024).
- 360 22. A. Toghani, R. Frijters, T. O. Bozkurt, R. Terauchi, S. Kamoun, Y. Sugihara, Can AI modeling of protein structures distinguish between sensor and helper NLR immune receptors? *New Phytologist* 248, 17–23 (2025).
- 23. J. Gottweis, W.-H. Weng, A. Daryin, T. Tu, A. Palepu, P. Sirkovic, A. Myaskovsky, F. Weissenberger, K. Rong, R. Tanno, K. Saab, D. Popovici, J. Blum, F. Zhang, K. Chou, A. 365 Hassidim, B. Gokturk, A. Vahdat, P. Kohli, Y. Matias, A. Carroll, K. Kulkarni, N. Tomasev, Y. Guan, V. Dhillon, E. D. Vaishnav, B. Lee, T. R. D. Costa, J. R. Penadés, G. Peltz, Y. Xu, A.

- Pawlosky, A. Karthikesalingam, V. Natarajan, Towards an AI co-scientist. arXiv arXiv:2502.18864 [Preprint] (2025). https://doi.org/10.48550/arXiv.2502.18864.
- 24. M. P. Contreras, H. Pai, Y. Tumtas, C. Duggan, E. L. H. Yuen, A. V. Cruces, J. Kourelis, H. Ahn, 370 K. Lee, C. Wu, T. O. Bozkurt, L. Derevnina, S. Kamoun, Sensor NLR immune proteins activate oligomerization of their NRC helpers in response to plant pathogens. *EMBO J* 42, EMBJ2022111519 (2022).
- 25. H.-K. Ahn, X. Lin, A. C. Olave-Achury, L. Derevnina, M. P. Contreras, J. Kourelis, C.-H. Wu, S. Kamoun, J. D. G. Jones, Effector-dependent activation and oligomerization of plant NRC class 375 helper NLRs by sensor NLR immune receptors Rpi-amr3 and Rpi-amr1. *The EMBO Journal*, e111484 (2023).
- 26. M. Selvaraj, A. Toghani, H. Pai, Y. Sugihara, J. Kourelis, E. L. H. Yuen, T. Ibrahim, H. Zhao, R. Xie, A. Maqbool, J. C. D. la Concepcion, M. J. Banfield, L. Derevnina, B. Petre, D. M. Lawson, T. O. Bozkurt, C.-H. Wu, S. Kamoun, M. P. Contreras, Activation of plant immunity through 380 conversion of a helper NLR homodimer into a resistosome. *PLOS Biology* 22, e3002868 (2024).
  - 27. Y. Sugihara, J. Kourelis, M. P. Contreras, H. Pai, M. Selvaraj, A. Toghani, C. Martínez-Anaya, S. Kamoun, Helper NLR immune protein NRC3 evolved to evade inhibition by a cyst nematode virulence effector. bioRxiv [Preprint] (2024). https://doi.org/10.1101/2024.06.16.598756.
- 28. E. F. Pettersen, T. D. Goddard, C. C. Huang, E. C. Meng, G. S. Couch, T. I. Croll, J. H. Morris, T. 385 E. Ferrin, UCSF ChimeraX: Structure visualization for researchers, educators, and developers. *Protein Science* 30, 70–82 (2021).
  - 29. A. Toghani, Y. Sugihara, S. Kamoun, Harmonized genome annotation of 346 Solanaceae species reveals 197,834 NLR immune receptors, Zenodo (2026); https://doi.org/10.5281/zenodo.19855163.
- 30. A. Toghani, B. Seager, D. Lüdke, S. Kamoun, AlphaFold 3 hexameric resistosome models for 637 390 NRC-clade NLR proteins from Solanaceae, Zenodo (2026); https://doi.org/10.5281/zenodo.19860918.
  - 31. A. Bendahmane, G. Farnham, P. Moffett, D. C. Baulcombe, Constitutive gain-of-function mutants in a nucleotide binding site–leucine rich repeat protein encoded at the Rx locus of potato. *The Plant Journal* 32, 195–204 (2002).
- 395 32. H. Adachi, M. Contreras, A. Harant, C. H. Wu, L. Derevnina, T. Sakai, C. Duggan, E. Moratto, T. O. Bozkurt, A. Maqbool, J. Win, S. Kamoun, An N-terminal motif in NLR immune receptors is functionally conserved across distantly related plant species. *eLife* 8 (2019).
- 33. T. Ibrahim, F. J. King, A. Toghani, L. Wang, S. Jenkins, E. L. H. Yuen, H.-Y. Wang, C. Vuolo, N. Eilmann, V. Adamkova, K.-S. Chia, B. Castel, J. D. G. Jones, P. Carella, C.-H. Wu, J. Kourelis, S. 400 Kamoun, T. O. Bozkurt, A helper NLR channels organellar calcium to trigger plant immunity. *Science* 392, 499–505 (2026).