# Computational Systems Biology: Kholodenko/Rukhlenko Group — Comprehensive Reference
 
**Systems Biology Ireland (SBI), University College Dublin**
 
This document consolidates technical reference material for the Kholodenko/Rukhlenko computational systems biology group. It covers the group's mathematical frameworks, algorithmic implementations, biological applications, and software tools. Content prioritizes information density, technical accuracy, and standardized notation.
 
---
 
## 1. Introduction: The Quantitative Turn in Cell Biology
 
The study of cellular signaling has historically been a descriptive discipline, characterized by static pathway maps and qualitative assessments of protein interactions. However, the complexity of biological networks — defined by non-linear dynamics, feedback loops, and emergent properties — necessitates a quantitative, engineering-based approach to fully understand cell fate decisions. The Kholodenko/Rukhlenko Group, situated within Systems Biology Ireland (SBI) at University College Dublin, stands at the forefront of this paradigm shift.
 
The group's research philosophy is predicated on the concept that cellular phenotype is not determined by the status of a single molecule, but by the dynamic topology of the underlying biochemical networks. To decipher these networks, the group integrates wet-laboratory experimentation (using advanced proteomic technologies like CyTOF and RPPA) with computational modeling. This integration has led to the development of seminal methodologies — most notably **Modular Response Analysis (MRA)** and **Cell State Transition Assessment and Regulation (cSTAR)** — which solve the inverse problem of reconstructing causal network topology from perturbation data.
 
---
 
## 2. Research Group and People
 
### 2.1. Systems Biology Ireland (SBI) — Institutional Context
 
**Founded:** September 2009 under Science Foundation Ireland CSET programme; partnership between UCD and NUI Galway.
 
**Location:** UCD Belfield campus, Dublin (Conway Institute).
 
**Recognition:** Rated among the top 5 Systems Biology Institutes worldwide (SFI international review panel, November 2014).
 
**Statistics:** 70+ staff from 20+ nations; 600+ publications since 2009; 260+ team members (105 researchers, 63 PhD students, 12 clinician scientists); 150+ international collaborations; €52+ million in funding; 223+ grants.
 
**Major facilities:** CMAP (Comprehensive Molecular Analytical Platform) — €2.68M SFI Research Infrastructure (2019); mass spectrometry facilities (Agilent, Bruker systems); UCD Conway Institute Proteomics Core.
 
**Research focus:** Cellular signal transduction networks; precision oncology and systems medicine; digital twins of cancer patients; cancer types: melanoma, ovarian, pancreatic, colorectal, breast, childhood cancers; inflammatory diseases; drug resistance mechanisms.
 
**Major programmes:** Precision Oncology Ireland (POI); DevelopMed; MAGIC-I; Let's Chat Medicine; ABE Ireland.
 
**Industry partners:** HP, Servier, AstraZeneca, ARK Therapeutics, Protagen, Siemens.
 
---
 
### 2.2. Walter Kolch — Director, SBI
 
Walter Kolch is the Director of SBI and a close institutional collaborator of the Kholodenko/Rukhlenko Group. He is not formally a member of the group but co-founded SBI with Kholodenko and provides the organizational leadership and experimental infrastructure within which the group operates.
 
**Positions:** Director, Systems Biology Ireland (since 2009); Director, Conway Institute of Biomolecular and Biomedical Research (~400 researchers); Director, Precision Oncology Ireland; Programme Coordinator for DevelopMed; Fellow, Royal Society of Edinburgh (FRSE); Member, Royal Irish Academy.
 
**Education:** M.D., University of Vienna, Austria.
 
**Career:** Professor of Molecular Cell Biology, University of Glasgow (2000–2009); Director, Sir Henry Wellcome Functional Genomics Facility, Glasgow (2001–2009); Scientific Director, RASOR (£15M Interdisciplinary Research Collaboration in Proteomics Technologies, 2005–2009).
 
**Rankings:** Google Scholar #2 worldwide in precision medicine, #6 in systems medicine, #23 in signal transduction, #40 in proteomics; 44,000+ citations; 2022 SFI Mentorship Award.
 
**Expertise:** Signal transduction networks; proteomics and systems biology; precision oncology; dynamic interaction proteomics for signal transduction pathway mapping; digital twins of cancer patients; non-genetic drug resistance (biochemical memory in kinase networks).
 
**Leadership:** Co-founded SBI with Kholodenko (2009); led first clinical trial based on mathematical model of dynamic signal processing (pancreatic cancer); pan-European initiatives: CASyM, ISBE, ITFoM, ELIXIR; secured €200+ million in competitive grant funding.
 
---
 
### 2.3. The Kholodenko/Rukhlenko Group — Overview
 
The Kholodenko/Rukhlenko Group is a computational and mathematical biology research group within SBI. Co-led by Prof. Boris Kholodenko and Dr. Oleksii Rukhlenko, the group develops mechanistic modeling frameworks — most notably MRA, BMRA, and cSTAR — and applies them to cancer signaling, drug resistance, and precision medicine. The group integrates "wet" laboratory experimentation with "dry" computational modeling in a tight iterative loop: experimental data (CyTOF, RPPA, mass spectrometry) feeds into mathematical models, which in turn generate testable predictions validated in the lab.
 
**Current members:**
 
| Name | Role |
|------|------|
| Boris Kholodenko | Principal Investigator, Full Professor |
| Oleksii Rukhlenko | Principal Investigator, Associate Professor |
| Hiroaki Imoto | Postdoctoral Researcher (Senior) |
| Sorour Nemati | Postdoctoral Researcher |
| Thomas Sevrin | Postdoctoral Researcher |
| Sarah Robertson | Research Scientist |
| Anna Tuliakova | Research Assistant |
| Ciardha Carmody | PhD Student |
| Sergiy Borodin | PhD Student |
 
---
 
### 2.4. Boris N. Kholodenko — Principal Investigator
 
**Positions:** SFI Stokes Professor of Systems Biology (SBI/UCD Conway Institute); Adjunct Professor, Department of Pharmacology, Yale University School of Medicine (since 2018); Adjunct Professor, Cancer Biology, Vanderbilt University (since 2012); Royal Irish Academy Member (elected 2018); Deputy Director of SBI.
 
**Education:** M.Sc. summa cum laude, Moscow Institute of Physics and Technology (MIPT), 1971; Ph.D. Biophysics, MIPT, 1976 (artificial neural networks); D.Sc. Biophysics, Moscow State University, 1989 (Metabolic Control Analysis of Bioenergetics).
 
**Career trajectory:** Laboratory of Anatol M. Zhabotinsky (Belousov–Zhabotinsky reaction researcher) → Moscow State University (Metabolic Control Analysis contributions) → Free University of Amsterdam with Hans Westerhoff, 1992–1996 (MCA of non-ideal metabolic systems) → Thomas Jefferson University, 1997–2009 (Professor, Director of Computational Cell Biology) → UCD/SBI, 2009–present.
 
**Foundational scientific contributions:**
 
- **First EGFR pathway model** — pioneering data-driven mechanistic model of receptor tyrosine kinase signaling [Kholodenko1999].
- **Modular Response Analysis (MRA)** — network reconstruction method from perturbation data; approximately 16,000+ citations [Kholodenko2002].
- **Bistability from multisite phosphorylation** — novel paradigm for switch-like behavior in MAPK signaling [Markevich2004].
- **Spatial signaling gradients** — predicted intracellular spatial gradients of signaling molecules [Brown1999, Kholodenko2006].
- **MAPK oscillations** — predicted ultrasensitivity and negative-feedback-induced oscillations [Kholodenko2000].
- **Drug resistance from kinase dimerization** — thermodynamic modeling of allosteric inhibitor effects [Kholodenko2015].
- **cSTAR methodology** — co-developed with Rukhlenko et al. [Rukhlenko2022].
**Methodological philosophy:** Mechanistic modeling using chemical kinetic equation theory; data-driven models integrating experimental data with computational frameworks; MRA for unraveling network "wires" from perturbation responses; systems-level understanding combining biochemistry, physical chemistry, and mathematics.
 
**Metrics:** 220+ publications; approximately 16,000+ citations; H-index among the top in the field.
 
---
 
### 2.5. Oleksii S. Rukhlenko — Principal Investigator
 
**Current role:** Co-leads the Kholodenko/Rukhlenko Group; Principal Investigator and Associate Professor at SBI.
 
**Education:** M.Sc. Applied Mathematics and Physics, MIPT; Ph.D. Mathematical Modeling, MIPT, 2009–2013 (thesis: "Mathematical modelling of thrombus formation processes in intensive blood flows," Prof. Guria Lab, National Research Centre for Haematology, Moscow).
 
**Career:** Former Marie Curie Postdoctoral Fellow; joined SBI November 2015.
 
**Key contributions:**
 
- **cSTAR methodology developer** — cell State Transition Assessment and Regulation; landmark approach for mapping cell states, modeling transitions, and predicting therapeutic interventions [Rukhlenko2022].
- **RAF inhibitor resistance modeling** — structure-based dynamic models of kinase inhibitors predicting drug synergy in RAS-driven leukemia [Rukhlenko2018].
- **MRA refinements** — noise analysis, network reconstruction improvements.
**Major publications:** *Nature* 2022 (cSTAR, first author); *Science Advances* 2023 (cSTAR-TB, Boston University/Altius collaboration); *Science Advances* 2025 (cSTAR vascular biology, Yale collaboration); *Cancers* 2024 (breast cancer cSTAR, first author); *Cell Systems* 2018 (RAF inhibitor resistance); *Blood* 2024 / *bioRxiv* 2025 (RAF inhibitor combinations for RAS-mutant AML).
 
**Grants:** SFI-IRC Pathway Programme Award 2023: "Using cyber-physical network modelling to tackle RAS-driven cancers."
 
**Expertise:** Mechanistic modeling + AI/ML integration; wet-lab experiment integration with computational pipelines; signal transduction network reconstruction; blood flow/coagulation mathematical modeling (early career).
 
---
 
### 2.6. Hiroaki Imoto — Postdoctoral Researcher (Senior)
 
**Position:** Postdoctoral Researcher, Kholodenko/Rukhlenko Group; funded by JSPS Overseas Research Fellowships (April 2023–March 2025).
 
**Education:** Ph.D. Biological Sciences, University of Osaka, 2020–2023 (Supervisor: Prof. Mariko Okada; thesis: "Stratification of triple-negative breast cancers using patient-specific modeling"); JSPS Scholar at SBI September 2021–February 2022 hosted by Prof. Boris Kholodenko.
 
**Research focus:** Molecular mechanisms of drug resistance to targeted therapies in MAPK signaling; structure-based modeling integrating kinetic, thermodynamic, and cellular data; computational frameworks for patient-specific cancer modeling; ErbB receptor signaling pathway modeling.
 
**Software developed:**
 
- **BioMASS** — Python framework for modeling/analysis of biological signaling systems ([github.com/biomass-dev/biomass](https://github.com/biomass-dev/biomass)) [Imoto2020].
- **Pasmopy** — Patient-specific modeling in Python ([github.com/pasmopy/pasmopy](https://github.com/pasmopy/pasmopy)) [Imoto2022].
**GitHub:** [github.com/himoto](https://github.com/himoto) (14 repositories, 40 followers); ORCID: 0000-0002-6817-642X.
 
**Key publications:** *Cancers* 2020 (computational framework for cancer signaling from RNA-seq); *iScience* 2022 (text-based patient-specific modeling); *Bioinformatics Advances* 2024 (extending BioMASS with Text2Model and KEGG integration); *STAR Protocols* 2022 (TNBC stratification protocol); *Cancers* 2023 (RAF overexpression resistance).
 
---
 
### 2.7. Eugene Kashdan — Applied Mathematician
 
**Affiliation:** School of Mathematical Sciences, University College Dublin. Ph.D. Applied Mathematics, Tel Aviv University, 2004.
 
**Expertise:** Mathematical medicine; computational physics; data science; statistical machine learning; dynamical systems analysis of signaling networks; optimal experiment design.
 
**Contributions:** Co-author on *Nature* 2022 cSTAR paper (mathematical robustness analysis regarding noise); contributed to Bayesian MRA development and the theoretical underpinnings of signaling models (modularity, retroactivity); organized Mathematical Methods in Systems Biology workshop series; guest editor for *Mathematical Biosciences and Engineering* special issues.
 
---
 
### 2.8. Sorour Nemati — Postdoctoral Researcher
 
**Position:** Postdoctoral Researcher, Kholodenko/Rukhlenko Group, SBI.
 
**Education:** B.Sc. Chemical Engineering, Sahand University of Technology, Iran; M.Sc. Chemical Engineering, Sahand University of Technology; PhD, LifETIME CDT (Engineering Underpinning Medicine) Fellow.
 
**Previous research:** Tissue engineering and regenerative medicine; biomaterials and stem cell research; fibrotic glial scar formation and modulation in vitro; spinal cord injury research; polymeric nanofibers for tissue engineering applications. Notable prior publication: "Current progress in application of polymeric nanofibers to tissue engineering" (*Nano Convergence*, 2019; 270+ citations).
 
**Current research focus:** Computational systems biology of cell signaling networks; integration of experimental data with mechanistic models.
 
**Contact:** sorour.nemati@ucd.ie
 
---
 
### 2.9. Thomas Sevrin — Postdoctoral Researcher
 
**Position:** Postdoctoral Researcher, SBI; affiliated with Kholodenko/Rukhlenko Group and Kolch Group.
 
**Research focus:** Effect of RAS protein mutations on cell signaling network rewiring; impact on cell metabolism and phenotype; colon cancer and melanoma research; pancreatic cancer and RAF inhibitor combinations.
 
**Methodology:** Standard cell culture techniques for cellular phenotype assessment; affinity purification/mass spectrometry (AP-MS); proteomic data analysis for signaling pathway rewiring; computational cell-specific modeling.
 
**Key publications:** Co-author on "Cell-specific models reveal conformation-specific RAF inhibitor combinations that synergistically inhibit ERK signaling in pancreatic cancer cells" (*Cell Reports*, September 2024); co-author on whole-cell energy modeling of RAS mutant cancer cell lines.
 
**Project involvement:** DevelopMed / Precision Oncology Ireland.
 
**Contact:** thomas.sevrin@ucd.ie
 
---
 
### 2.10. Sarah Robertson — Research Scientist
 
**Position:** Research Scientist, SBI; affiliated with Halasz Group and Kholodenko/Rukhlenko Group.
 
**Research focus:** Cancer and childhood cancer research, with emphasis on neuroblastoma and related pediatric malignancies. Works within the Halasz Group, which investigates how the spatiotemporal dynamics of signal transduction networks contribute to cancer cell phenotype, heterogeneity, and resistance to treatment. The group applies this knowledge to develop novel therapeutic approaches for highly aggressive childhood cancers, with particular focus on MYCN-amplified neuroblastoma, epigenetic dysregulation, and phosphoproteomic profiling of neuroblastoma cells.
 
**Expertise:** Signaling networks and cancer cell phenotypes; therapeutic target identification; phosphoproteomic data generation and analysis for pediatric cancer models.
 
**ORCID:** [0000-0002-9967-0084](https://orcid.org/0000-0002-9967-0084)
 
**Contact:** sarah.robertson@ucd.ie
 
---
 
### 2.11. Anna Tuliakova — Research Assistant
 
**Position:** Research Assistant, Kolch Group / Kholodenko/Rukhlenko Group, SBI.
 
**Research focus:** Immuno-oncology research; breast cancer cell state transitions; cancer cell phenotyping and therapeutic target identification. Contributed to the cSTAR breast cancer study, which applied the cell State Transition Assessment and Regulation approach to phosphoproteomic data from breast cancer and normal breast tissue-derived cell lines. The study identified that luminal breast cancer cells share a core network architecture with mTOR as a main oncogenic driver, while basal breast cancer networks are heterogeneous with distinct oncogenic drivers (PKC, MEK/ERK, STAT3).
 
**Key publications:** Co-author on "Cell State Transition Models Stratify Breast Cancer Cell Phenotypes and Reveal New Therapeutic Targets" (*Cancers* 16(13):2354, 2024) [Rukhlenko2024].
 
**Project involvement:** Precision Oncology Ireland.
 
**Contact:** anna.tuliakova@ucd.ie
 
---
 
### 2.12. Ciardha Carmody — PhD Student
 
**Position:** PhD Student, SBI; affiliated with Bond Group, Kolch Group, and Kholodenko/Rukhlenko Group. Member of the SFI Centre for Research Training in Genomics Data Science.
 
**Research focus:** Mathematical and computational modeling of cancer signaling; RAS pathway modeling in acute myeloid leukemia (AML); RAF inhibitor combinations for drug-resistant cancers. Her work employs structure-based, dynamic RAS pathway models to predict RAF inhibitor (RAFi) combinations that synergistically suppress ERK signaling in RAS-mutant AML. Predictions have been validated in vitro in AML cell lines and patient samples.
 
**Key publications:** Co-author on "A structure-based modelling approach identifies effective drug combinations for RAS-mutant acute myeloid leukemia" (*Blood*, 2024; *bioRxiv*, May 2025). Lead authors: Luke Jones, Oleksii Rukhlenko. Co-authors include Tânia Dias, Kieran Wynne, Boris N. Kholodenko, and Jonathan Bond.
 
**Contact:** ciardha.carmody@ucdconnect.ie
 
---
 
### 2.13. Sergiy Borodin — PhD Student
 
**Position:** PhD Student, SBI; affiliated with Bond Group and Kholodenko/Rukhlenko Group. Supervisor: Jonathan Bond (UCD Brendan McGonnell Professor of Paediatric Molecular Haemato-Oncology).
 
**Research focus:** Cancer and childhood cancer systems biology; computational modeling of signaling networks. Works within the Bond Group, which leads a collaborative paediatric leukaemia research program between Systems Biology Ireland at UCD and the National Children's Cancer Service at Children's Health Ireland at Crumlin. The group's research focuses on understanding epigenetic modifications in paediatric acute myeloid leukaemia (AML) and developing synergistic drug combinations for children and adolescents with blood cancers.
 
**Contact:** sergiy.borodin@ucdconnect.ie
 
---
 
### 2.14. Key Collaborators
 
**Yale School of Medicine:** Anatoly Kiyatkin, PhD (co-authored EGFR pathway models, Western blotting methods); Martin A. Schwartz (cSTAR vascular biology collaboration, *Science Advances* 2025); Kholodenko holds Adjunct Professorship, Department of Pharmacology (since 2018).
 
**Boston University:** Igor Kramnik (NEIDL) — tuberculosis research; applied cSTAR to TB-susceptible macrophages (*Science Advances* 2023) [Rukhlenko2023TB].
 
**Altius Institute for Biomedical Sciences (Seattle):** Alexander A. Gimelbrant — TB research collaboration.
 
**Cancer Research UK Edinburgh Centre:** Kenneth MacLeod and Neil O. Carragher (University of Edinburgh) — RPPA data, drug discovery; co-authors on *Nature* 2022 cSTAR paper.
 
**QBI/UCSF Partnership:** 5-year MOU with UCSF Quantitative Biosciences Institute; QBI/SBI Seminar Series on molecular networks.
 
**Other notable collaborators:** Hans Westerhoff (Amsterdam/Manchester); Eduardo Sontag (Northeastern); Marc Birtwistle (Clemson); Melinda Halasz (UCD); Vadim Zhernovkov (UCD).
 
---
 
## 3. cSTAR Methodology
 
### 3.1. Overview
 
**cSTAR (cell State Transition Assessment and Regulation)** is a hybrid computational framework published in *Nature* (2022) by Rukhlenko et al. [Rukhlenko2022]; extended in *Cancers* (2024) for breast cancer [Rukhlenko2024]. It maps cell states, models transitions between them, and predicts targeted interventions to convert cell fate decisions by integrating ML classification with mechanistic ODE modeling in a Waddington landscape framework.
 
**Core concept:** Each cell state is represented as a point in molecular-response space (e.g., phosphoprotein levels). cSTAR defines quantitative descriptors of the transition between states and uses a combination of SVM classification, network inference, and ODE modeling to predict interventions that drive cells across state boundaries.
 
**Patent protection:** UK patent GB202107576D0 (2021); European patent EP4348652A1 (2022); US patent US20240274226A1 (2022); WIPO WO2022248728A1 (2022). Inventors: Rukhlenko, Zhernovkov, Kolch, Kholodenko.
 
---
 
### 3.2. State Transition Vectors (STV)
 
**Definition:** A unit-length vector characterizing each molecule's contribution to differences between cell states; determines the direction of cell state transitions.
 
**Mathematical formulation:** The STV is the normal vector $\mathbf{n}_s$ to the maximum-margin separating hyperplane constructed by an SVM with linear kernel:
 
$$
\mathbf{x} \cdot \mathbf{n}_s = h_s
$$
 
where $\mathbf{x}$ is a data point in molecular feature space (e.g., phosphoproteomic measurements), $\mathbf{n}_s$ is the State Transition Vector (unit normal to the hyperplane), and $h_s$ is a scalar offset determining hyperplane position. This hyperplane represents the "ridge" in Waddington's landscape separating two basins of attraction.
 
Geometrically, the STV connects the centroids of the point clouds representing two distinct cell states:
 
$$
\mathrm{STV} \propto \bar{\mathbf{x}}^B - \bar{\mathbf{x}}^A
$$
 
**Calculation procedure:**
 
1. Input omics data (RPPA, CyTOF, phosphoproteomics).
2. Apply SVM with linear kernel to separate cell state classes.
3. Extract separating hyperplane parameters.
4. Normal vector to the hyperplane becomes the STV.
**Interpretation:** The absolute values of STV components directly rank individual proteins by importance in switching cell states. High-ranked components constitute the **core signaling network** controlling whole-cell network transitions. This dimensionality reduction is based on biological causality rather than variance (as in PCA).
 
**Multiple STVs:** For multiple state transitions, separate STVs are computed (e.g., $\mathrm{STV}_{\mathrm{onc}}$: normal → cancer; $\mathrm{STV}_{\mathrm{L\text{-}B}}$: luminal → basal).
 
---
 
### 3.3. Dynamic Phenotype Descriptors (DPD)
 
**Definition:** A signed distance function from a data point to the separating hyperplane; determines when quantitative signaling changes result in qualitative cell state changes.
 
**Formula:**
 
$$
\mathrm{DPD}_s^i = -\bigl(h_s - \mathbf{x}_i \cdot \mathbf{n}_s\bigr)
$$
 
where $\mathrm{DPD}_s^i$ is the DPD score for data point $\mathbf{x}_i$, $\mathbf{n}_s$ is the corresponding STV (unit vector), and $h_s$ is the hyperplane offset. Equivalently, using the dot-product formulation:
 
$$
\mathrm{DPD}(t) = \mathrm{STV} \cdot \bigl(\mathbf{x}(t) - \mathbf{x}^*\bigr)
$$
 
where $\mathbf{x}^*$ is a reference baseline (e.g., untreated state).
 
**Properties:**
 
- **Sign:** Indicates whether the direction from the data point to the hyperplane is parallel or antiparallel to the STV. A value of 0 places the cell on the "tipping point."
- **Absolute value:** Distance to the separating hyperplane; quantifies proximity to the cell state boundary.
- **Zero crossing:** Describes when small quantitative changes trigger a qualitative state change.
- The DPD serves as a single monitorable variable summarizing the state of the entire cellular network — analogous to a reaction coordinate on a Waddington landscape.
**Theoretical basis:** Non-equilibrium thermodynamics (systems behave similarly near critical states); SVM interpretation (distance to hyperplane determines when small changes trigger state transitions).
 
**STV vs DPD distinction:**
 
| Feature | STV | DPD |
|---------|-----|-----|
| Type | Unit vector | Scalar value |
| Role | Direction of state transition | Position in state space |
| Use | Component ranking for core network | Connection to phenotype/landscape |
| Output | Core network components | Cell state trajectory |
 
---
 
### 3.4. Waddington's Epigenetic Landscape
 
**Original concept (Conrad Waddington, 1957):** An inclined surface with branching valleys (stable cell fates/attractors) and ridges (barriers); a cell as a ball rolling through the landscape; development progressively restricts potential.
 
**Mathematical implementation in cSTAR:**
 
The **potential function** $U(S)$ has two minima corresponding to stable steady states characterized by DPD scores $S_0$ (e.g., normal or luminal state, negative DPD) and $S_1$ (e.g., oncogenic or basal state, positive DPD), with an unstable point at the boundary between attractor regions.
 
**Restoring force** $f(S)$ — the gradient force returning the cell to a stable attractor:
 
$$
f(S) = -\frac{dU}{dS}
$$
 
**Piece-wise linear approximation:**
 
$$
f(S) = \begin{cases}
-\alpha_0\,(S - S_0), & S < \frac{3S_0 + S_1}{4} \\[4pt]
\alpha_0\!\left(S - \frac{S_0 + S_1}{2}\right), & \frac{3S_0 + S_1}{4} < S < \frac{S_0 + S_1}{2} \\[4pt]
\alpha_1\!\left(S - \frac{S_0 + S_1}{2}\right), & \frac{S_0 + S_1}{2} < S < \frac{S_0 + 3S_1}{4} \\[4pt]
-\alpha_1\,(S - S_1), & S > \frac{S_0 + 3S_1}{4}
\end{cases}
$$
 
where $\alpha_0, \alpha_1$ are slope parameters fitted from data.
 
**Signaling force** $\sigma(t)$ — the drive provided by the activity of core signaling kinases:
 
$$
\sigma(t) = \sum_j r_{Sj} \cdot \frac{S_{\mathrm{ss}}}{x_j^{\mathrm{ss}}} \cdot x_j(t)
$$
 
where $r_{Sj}$ is the BMRA-inferred connection coefficient from module $j$ to the DPD, $x_j(t)$ is the activation dynamics of signaling module $j$, $S_{\mathrm{ss}}$ is the initial steady-state value of $S$, and $x_j^{\mathrm{ss}}$ is the initial steady-state value of $x_j$.
 
**DPD trajectory equation:**
 
$$
\frac{dS}{dt} = f(S) + \sigma(t) = -\frac{dU}{dS} + \sum_j r_{Sj} \cdot \frac{S_{\mathrm{ss}}}{x_j^{\mathrm{ss}}} \cdot x_j(t)
$$
 
This formulation allows prediction of the specific perturbations (drugs) required to generate a signaling force strong enough to overcome the restoring force and push the cell across the hyperplane into a new state (e.g., reverting a cancer cell to a normal-like state).
 
**Evolving Waddington landscape** $W$:
 
$$
W = U - \sum_j r_{Sj} \cdot \frac{S_{\mathrm{ss}}}{x_j^{\mathrm{ss}}} \cdot x_j(t) \cdot S(t)
$$
 
---
 
### 3.5. Machine Learning Integration
 
**SVM with linear kernel:** Best performer when data dimensionality greatly exceeds the number of observations (typical for omics data). The SVM not only separates states but yields feature weights for core network identification.
 
**Validation:** 8-fold cross-validation demonstrated 96% precision for cancer vs. non-cancer classification; robust to in-silico perturbations (removing individual analytes); robust to artificial noise (up to 50% noise level).
 
**ML + Mechanistic ODE integration pipeline:**
 
1. **ML Classification (SVM)** → Defines state boundaries and STVs.
2. **Network Reconstruction (BMRA)** → Identifies causal connections.
3. **ODE Modeling** → Predicts dynamic responses and interventions.
---
 
### 3.6. Core Network Identification
 
**Module selection criteria:**
 
1. STV component ranking (high absolute values).
2. Perturbation data availability.
3. Prior knowledge (bioinformatic enrichment, literature).
4. Desired granularity (trade-off: detail vs. data requirements).
**Typical signaling modules:** EGFR/ERBB, MEK/ERK, PI3K/AKT, mTOR/S6K, PKC, STAT3, JNK/MKK4. Each module can be a single protein or an entire pathway with a representative protein output.
 
---
 
### 3.7. Complete cSTAR Workflow
 
**Step 1 — Data input and preprocessing:** Omics data (RPPA, CyTOF, MS); normalization; batch correction; time-series/perturbation organization.
 
**Step 2 — Cell state classification (SVM):** Train SVM with linear kernel; extract hyperplane; construct STV(s); validate with cross-validation.
 
**Step 3 — Core network selection:** Rank analytes by STV component values; select top-ranked based on available perturbations; define modules.
 
**Step 4 — DPD calculation:** Calculate DPD scores; remove core network proteins from dataset; recalculate DPD for phenotypic module. The DPD is included as a distinct "node" in the network, capturing how signaling nodes influence the global cell state and reciprocally how the cell state exerts feedback on signaling nodes.
 
**Step 5 — Network reconstruction (BMRA):** Construct global response matrix from perturbation data; apply BMRA with prior topology; obtain connection coefficients with confidence intervals; separate early vs. late timepoints.
 
**Step 6 — Mechanistic model construction:** Build nonlinear ODE models using PySB; incorporate BMRA-inferred connections; parameterize with hyperbolic multipliers for crosstalk.
 
**Step 7 — Model parameterization:** Fit to time-course data; use differential evolution optimization; estimate Waddington landscape parameters ($\alpha_0$, $\alpha_1$, $S_0$, $S_1$, $\beta_j$).
 
**Step 8 — Prediction and validation:** Simulate drug responses; calculate DPD trajectories; generate Waddington landscape visualizations; predict synergistic combinations (Loewe isoboles).
 
---
 
### 3.8. Digital Twin Concept
 
In cSTAR, a **digital twin** is a calibrated computational model representing a particular cell line or phenotype. The twin encodes both the quantitative network (from MRA-like inference) and the mapping to phenotypic space (via STV/DPD). It can predict how untested combinations of inhibitors will move the cell in state-space. The breast cancer cSTAR models suggest specific multi-drug combinations that could "normalize" cancer cells — termed **phenotypic reversion**, an alternative to cytotoxicity where therapy attempts to reprogram the cell rather than kill it [Rukhlenko2024].
 
---
 
### 3.9. Variable Names and Notation Summary
 
| Variable | Description |
|----------|-------------|
| $\mathbf{x}$ | Data point in molecular feature space |
| $\mathbf{n}_s$ | State Transition Vector (unit normal) |
| $h_s$ | Hyperplane offset |
| $\mathrm{DPD}_s^i$ | Dynamic Phenotype Descriptor for point $i$ |
| $r_{ij}$ | Local response (connection coefficient) from $j$ to $i$ |
| $R_{ij}$ | Global response matrix elements |
| $U(S)$ | Potential function |
| $f(S)$ | Restoring force |
| $\sigma(t)$ | Signaling force |
| $W$ | Waddington landscape |
| $\alpha_0, \alpha_1$ | Slope parameters for restoring force |
| $S_0, S_1$ | Stable steady-state DPD values |
| $\beta_j$ | Signaling coupling coefficient $= r_{Sj} \cdot S_{\mathrm{ss}} / x_j^{\mathrm{ss}}$ |
 
---
 
## 4. Modular Response Analysis (MRA)
 
### 4.1. Overview
 
**MRA** is a physics-based method for reconstructing quantitative topological models of biochemical networks from steady-state perturbation data. Introduced by Kholodenko et al. [Kholodenko2002] ("Untangling the wires"), it has accumulated approximately 16,000+ citations.
 
**Key features:** Infers direction and strength of causal connections; distinguishes direct (local) from indirect (global) interactions; enables ODE model development; applicable to signaling, gene regulatory, and metabolic systems. MRA resolves the fundamental problem that in a highly interconnected system, a perturbation to one node propagates throughout the entire network, making it difficult to discern whether a change in node $i$ is caused directly by node $j$ or via an intermediate node $k$.
 
---
 
### 4.2. Mathematical Formulation
 
**Fundamental assumptions:**
 
1. System described by a dynamical system: $d\mathbf{x}/dt = \mathbf{f}(\mathbf{x}, \mathbf{p})$.
2. System at steady state: $d\mathbf{x}/dt = 0 \implies \mathbf{f}(\bar{\mathbf{x}}, \mathbf{p}) = 0$.
3. The function $\mathbf{f}$ exists but need not be known explicitly.
**Local Response Coefficients** $r_{ij}$ — the direct (isolated) influence of module $j$ on module $i$:
 
$$
r_{ij} = \left.\frac{\partial \ln \bar{x}_i}{\partial \ln \bar{x}_j}\right|_{\bar{x}_k = \mathrm{const},\; k \neq i,j}
= \frac{\bar{x}_j}{\bar{x}_i} \cdot \left.\frac{\partial \bar{x}_i}{\partial \bar{x}_j}\right|_{\bar{x}_k = \mathrm{const},\; k \neq i,j}
$$
 
**Interpretation:**
 
- $r_{ij} > 0$: Module $j$ activates module $i$.
- $r_{ij} < 0$: Module $j$ inhibits module $i$.
- $r_{ij} = 0$: No direct interaction.
- $|r_{ij}|$: Interaction strength.
**Relationship to Jacobian:** For an ODE model $\dot{\mathbf{x}} = \mathbf{f}(\mathbf{x}, \mathbf{p})$ at steady state, the Jacobian $J_{ij} = \partial f_i / \partial x_j$ satisfies:
 
$$
r_{ij} = -\frac{J_{ij}}{J_{ii}} \cdot \frac{\bar{x}_j}{\bar{x}_i}\bigg|_{\mathrm{ss}} \quad \text{for } i \neq j
$$
 
**Convention:** $r_{ii} = -1$ (self-regulation, representing normalized self-decay).
 
**Global Response Coefficients** $R_{ij}$ — the total system-wide change when module $k$ is perturbed:
 
$$
R_{ik} = \frac{d(\ln \bar{x}_i)}{dp_k} = \frac{1}{\bar{x}_i} \cdot \frac{d\bar{x}_i}{dp_k}
$$
 
**Experimental estimation:**
 
$$
\tilde{R}_{ij} \approx 2 \cdot \frac{\bar{x}_i^j - \bar{x}_i^0}{\bar{x}_i^j + \bar{x}_i^0}
$$
 
For DPD modules:
 
$$
R_{ij} = \frac{\mathrm{DPD}_s^1 - \mathrm{DPD}_s^0}{\mathrm{DPD}_s^0}
$$
 
---
 
### 4.3. Core MRA Equations
 
**Homogeneous equation** ($i \neq k$):
 
$$
\sum_{\substack{j=1 \\ j \neq i}}^{n} r_{ij} \cdot R_{jk} = R_{ik}
$$
 
**Inhomogeneous equation** ($i = k$):
 
$$
\sum_{\substack{j=1 \\ j \neq i}}^{n} r_{ij} \cdot R_{ji} = R_{ii} - P_{ii}
$$
 
**Matrix form:**
 
$$
\mathbf{r} \cdot \mathbf{R} = \mathbf{P}
$$
 
**Solution:**
 
$$
\mathbf{r} = \mathbf{P} \cdot \mathbf{R}^{-1} = -\mathrm{diag}\!\left\{\frac{1}{(\mathbf{R}^{-1})_{ii}}\right\} \cdot \mathbf{R}^{-1}
$$
 
This equation is profound because it demonstrates that the topology and interaction strengths of a biological network can be reconstructed *ab initio* from steady-state perturbation data, without knowledge of the specific kinetic rate laws (e.g., Michaelis–Menten vs. mass action) governing the reactions [Kholodenko2002].
 
Equivalently, one can write the identity $(\mathbf{I} - \mathbf{r})^{-1} = \mathbf{I} + \mathbf{R}$, leading to $\mathbf{r} = \mathbf{I} - (\mathbf{R} + \mathbf{I})^{-1}$.
 
---
 
### 4.4. Connection Coefficients
 
**Definition:** Elements $r_{ij}$ of the local response matrix.
 
**Biological interpretation:** Functional interactions (not just physical binding); regulatory influence (activation/inhibition); for signaling: phosphorylation/dephosphorylation relationships.
 
**Network topology extraction:** Non-zero elements = directed edges; magnitude = strength; sign = activation (+) / inhibition (−).
 
---
 
### 4.5. Perturbation Design Requirements
 
**Essential:** $N$ perturbation experiments for $N$ modules (minimum); each perturbation specifically affects one module; system reaches steady state after perturbation; all module activities are measurable.
 
**Perturbation types:** Knockdowns (shRNA, siRNA, 50–80%); knockouts (CRISPR/Cas9); inhibitors (small molecule, antibody); overexpression; kinase/phosphatase inhibitors.
 
**Optimization** (Thomaseth et al. [Thomaseth2018]): Large perturbations preferred (reduces noise sensitivity despite bias); single control sufficient; minimum 3 replicates; use mean of GRC replicates.
 
**Workflow:** Measure baseline $x_i^0$; for each $j$ apply perturbation and measure $x_i^j$; compute $R_{ij} = (\ln x_i^j - \ln x_i^0)/(\ln p_j^j - \ln p_j^0)$; solve for $r_{ij}$.
 
---
 
### 4.6. Bayesian MRA (BMRA)
 
**Motivation:** Classical MRA requires $N$ perturbations for $N$ modules, is sensitive to noise, and provides no mechanism for incorporating prior knowledge.
 
**BMRA features** (Santra et al. [Santra2013]):
 
- Combines MRA with Bayesian Variable Selection (BVS).
- Incorporates prior network knowledge as informative priors.
- Handles incomplete perturbation data.
- Provides probability distributions over connection coefficients.
- Generates confidence intervals.
**Probabilistic formulation:** The core equation $\mathbf{r} \cdot \mathbf{R} = \mathbf{P}$ is treated as a regression model with an error term. The algorithm uses a likelihood function:
 
$$
\mathcal{L}(\mathbf{R} \mid \mathbf{r}, \mathbf{A}, \boldsymbol{\sigma}) \propto \exp\!\left(-\frac{1}{2\sigma^2}\|\mathbf{R} - \mathbf{r} \cdot \mathbf{R}\|^2\right)
$$
 
where $\mathbf{A}$ is a binary adjacency matrix representing the network topology ($A_{ij} = 1$ for interaction, $0$ for no interaction) and $\boldsymbol{\sigma}$ captures experimental noise.
 
**Prior knowledge integration:** Prior distributions $P(A_{ij})$ enforce sparsity or bias the search toward interactions known from literature (e.g., KEGG, STRING). BMRA employs Gibbs sampling or other MCMC techniques to explore possible network topologies, calculating the marginal posterior probability for each edge — effectively providing a "confidence score" for every inferred interaction.
 
**BMRA advantages:**
 
1. Fewer perturbations required (can operate when perturbations < modules).
2. Noise tolerance through probabilistic framework.
3. Prior knowledge integration improves accuracy.
4. Confidence intervals on inferred connections.
5. Nearly perfect topology recovery even with 50% inaccurate priors.
**Other MRA extensions:** Maximum Likelihood MRA (ML-MRA); Total Least Squares MRA (TLS-MRA); Monte Carlo MRA; MLMSMRA; Multilinear Regression MRA.
 
---
 
### 4.7. Assumptions and Limitations
 
**Assumptions:** Steady-state; linearity approximation (first-order Taylor); perturbation specificity; module insulation; measurability; no bifurcations.
 
**Limitations:** Noise sensitivity → statistical variants; heavy-tailed LRC distributions → robust estimation; linearization bias → trade-off analysis; $N$ perturbations required → Bayesian MRA; sequestration effects → extended methods.
 
**When MRA may fail:** Sustained oscillations; bistable systems crossing bifurcations; shared components between modules; very high noise; incomplete perturbation coverage.
 
---
 
## 5. Signaling Biology Reference
 
### 5.1. MAPK/ERK Pathway
 
**Architecture:** Growth factor → RTK → RAS → RAF (ARAF, BRAF, CRAF) → MEK1/2 → ERK1/2 → downstream targets (ELK, ETS1, AP1, cell motility). This is a three-tiered kinase amplifier module.
 
**RAF isoforms:** ARAF, BRAF, CRAF (RAF1). BRAF is the most potent; CRAF is the most common drug resistance mechanism.
 
**Negative feedback loops:**
 
1. **ERK → RAF:** Strong; confers robustness to protein level variations.
2. **ERK → SOS:** Phosphorylation reduces Ras activation.
3. **ERK → MEK:** Shapes temporal ERK activity profile.
4. **Transcriptional:** Induces DUSP family phosphatases (MKPs) to dephosphorylate ERK.
**Systems properties (Kholodenko findings):** The MAPK cascade functions as a Negative Feedback Amplifier (NFA); converts switch-like to graded linear responses; confers robustness to rate changes; stabilizes outputs against drug perturbations.
 
**ERK dynamics and cell fate:**
 
- **Transient activation:** Promotes proliferation (e.g., EGF response in PC12/epithelial cells).
- **Sustained activation:** Promotes differentiation (e.g., NGF response via TrkA).
- Frequency modulation rewires cell fate decisions.
---
 
### 5.2. PI3K/AKT/mTOR Pathway
 
**Components:**
 
- **PI3K:** Lipid kinase converting PIP$_2$ → PIP$_3$.
- **PDK1:** Phosphorylates AKT at T308.
- **mTORC2:** Phosphorylates AKT at S473.
- **AKT (PKB):** Central effector (cell cycling, survival, growth); phosphorylates and inhibits TSC2, thereby activating mTORC1; inactivates pro-apoptotic factors (BAD, FOXO).
- **mTORC1:** Contains mTOR, Raptor, mLST8, PRAS40, DEPTOR.
- **Downstream:** S6K, 4EBP1 (protein synthesis, ribosomal translation).
**Negative regulators:** PTEN (PIP$_3$ → PIP$_2$); PP2A, PHLPP phosphatases; TSC1/2 complex. Negative feedback: S6K phosphorylates IRS1, inhibiting upstream RTK signaling.
 
**Oncogenic alterations:** PIK3CA mutations (14% pan-cancer; exons 9, 20); PTEN loss (9% mutated, 7% deleted); AKT amplification (3%); mTOR amplification (4%).
 
**Crosstalk with MAPK:** Ras can activate PI3K directly; AKT can phosphorylate and inhibit RAF; mTOR inhibition upregulates MEK/ERK; dual inhibition overcomes single-agent resistance; multiple feedback loops create redundancy.
 
---
 
### 5.3. STAT3 Signaling
 
**Activation:** Phosphorylation at Y705 (by JAK family kinases, RTKs, Src); dimerization; nuclear translocation.
 
**Targets:** BCL-XL, survivin, MCL1 (anti-apoptotic); CCND1, MYC (proliferation); VEGF (angiogenesis).
 
**Role in cancer:** Constitutively active in many cancers; promotes survival, proliferation, invasion, and immunosuppression. Activity is countered by phosphatases (SHP2) and inhibitors (SOCS3).
 
---
 
### 5.4. Receptor Tyrosine Kinases
 
**EGFR (ERBB1/HER1):** Ligands: EGF, TGF-α, amphiregulin. Activates MAPK, PI3K, PLCγ pathways. Mutations: exon 19 deletions, L858R (sensitizing); T790M (resistance). Upon ligand binding, recruits Grb2/SOS (for Ras activation), Gab1 (for PI3K), and PLCγ.
 
**HER2/ERBB2:** No known direct ligand (heterodimerizes with EGFR/ErbB3). Amplified in ~15–20% of breast cancers. Targets: trastuzumab, pertuzumab, lapatinib.
 
**TrkA (NTRK1):** Ligand: NGF (nerve growth factor). Induces neuronal differentiation; favorable prognosis in neuroblastoma. Activates MAPK, PI3K-AKT.
 
**TrkB (NTRK2):** Ligands: BDNF, NT-4. Promotes aggressive phenotype: chemoresistance, invasion, angiogenesis. Associated with MYCN amplification. Autocrine survival loop.
 
---
 
### 5.5. Phosphorylation Notation
 
| Notation | Meaning |
|----------|---------|
| pERK | Phosphorylated ERK (mono-phosphorylated) |
| ppERK | Doubly phosphorylated ERK (fully active, T202/Y204) |
| pAKT(S473) | AKT phosphorylated at Serine 473 |
| pAKT(T308) | AKT phosphorylated at Threonine 308 |
| pS6 | Phosphorylated ribosomal protein S6 (mTORC1 readout) |
| p-p90RSK | Phosphorylated p90 ribosomal S6 kinase |
| pSTAT3 | STAT3 phosphorylated at Y705 |
 
**Dual phosphorylation requirement:** ERK requires both T202/Y204 (TEY motif) phosphorylation for full activity.
 
---
 
### 5.6. Feedback Loop Mechanisms
 
**Negative feedback examples:** ERK → SOS (reduces Ras activation); ERK → RAF (reduces RAF activation); S6K → IRS1 (reduces PI3K activation); mTORC1 → IRS1 (feedback inhibition); DUSP/MKP induction by ERK.
 
**Positive feedback examples:** ERK → EGFR ligand production; RAS-RAF-MEK → positive amplification via RAF dimerization; active ERK can stimulate autocrine growth factor release.
 
**Systems-level effects:** Ultrasensitivity; bistability (hysteresis); oscillations; robustness.
 
---
 
### 5.7. Cell Fate Decisions
 
**Proliferation determinants:** Transient ERK activation; high AKT/mTOR activity; cyclin D1 induction; CDK4/6 activation.
 
**Differentiation determinants:** Sustained ERK activation; transcription factor (AP-1, CREB) activation; cell cycle arrest genes.
 
**Molecular switches:** Multisite phosphorylation creates ultrasensitivity; competing kinase/phosphatase activities; feedback loops convert graded inputs to switch-like outputs.
 
**Pathway crosstalk:** Signaling pathways interact at multiple points. Ras activates both MAPK and PI3K. AKT can phosphorylate and inhibit RAF. PLCγ from RTKs generates PKC activation, which can modulate MAPK. In cancer, such crosstalk enables compensation: e.g., MEK inhibition often relieves feedback and hyperactivates PI3K/AKT.
 
---
 
## 6. Cancer Biology Reference
 
### 6.1. Oncogenic Transformation
 
**Hallmarks:** Sustained proliferative signaling; evading growth suppressors; resisting cell death; enabling replicative immortality; inducing angiogenesis; activating invasion/metastasis; deregulating cellular energetics; avoiding immune destruction; genome instability; tumor-promoting inflammation.
 
**Common oncogenic drivers:**
 
- **RAS mutations:** KRAS G12D/V/C, NRAS Q61L/K (20–30% of all cancers) — lock Ras in GTP-bound active state.
- **RAF mutations:** BRAF V600E (melanoma, colorectal, thyroid) — constitutive MAPK signaling.
- **PIK3CA mutations:** E545K, H1047R (breast, colorectal).
- **PTEN loss:** Tumor suppressor; disinhibits PI3K.
- **TP53 mutations:** Most common tumor suppressor mutation (>50% of cancers).
---
 
### 6.2. Breast Cancer Subtypes
 
**Luminal A (~40%):** ER+/PR+, HER2-negative, Ki-67 <20%. Best prognosis, low relapse rate. High response to hormone therapy. Bone metastasis common. Limited chemotherapy benefit. Key markers: ESR1, GATA3.
 
**Luminal B (~15–20%):** ER+, may express PR and/or HER2. Ki-67 >20% (high proliferation). Higher grade and recurrence rate than Luminal A. May require chemotherapy. Upregulated: v-MYB, GGH, LAPTMB4, NSEP1, CCNE1.
 
**HER2-Enriched:** ER−/PR−, HER2 overexpression (ERBB2 amplified). Aggressive phenotype. Benefits from trastuzumab, pertuzumab. High proliferation index.
 
**Basal-Like/Triple-Negative (TNBC):** ER−/PR−/HER2−. Most aggressive subtype, poor prognosis. High genomic instability. Four subtypes: BL1, BL2, Mesenchymal (M), Luminal AR (LAR). PIK3CA mutations less prevalent (~10%); BRCA1/2 mutations common. Chemotherapy is main treatment; immunotherapy emerging.
 
**cSTAR findings** [Rukhlenko2024]:
 
- **Luminal BC:** mTOR identified as main oncogenic driver; STAT3 maintains luminal subtype.
- **Basal BC:** Heterogeneous, ~4 subclasses: mTOR-driven (11 lines), MEK/ERK-driven (5 lines), STAT3-driven (1 line), PKC-driven (9 lines).
- The STV analysis revealed that luminal and basal subtypes are distinguished not just by receptor expression but by distinct wiring of the PI3K-mTOR axis.
---
 
### 6.3. Neuroblastoma
 
**TrkA vs TrkB biology:**
 
| Feature | TrkA (favorable) | TrkB (aggressive) |
|---------|-----------------|------------------|
| Ligand | NGF | BDNF, NT-4 |
| Phenotype | Differentiation | Proliferation |
| MYCN | Not amplified | Often amplified |
| Stage | Low-stage tumors | High-stage tumors |
| Outcome | Spontaneous regression | Chemoresistance |
| Mechanism | MAPK/PI3K → differentiation | Autocrine survival loop |
 
**SH-SY5Y cell model:** Human neuroblastoma from SK-N-SH metastatic bone marrow biopsy. Subcloning: SK-N-SH → SH-SY → SH-SY5 → SH-SY5Y. Adrenergic/dopaminergic phenotype; near-triploid karyotype; two morphologies: N-type (neuroblast), S-type (epithelial).
 
**Differentiation protocols:** Retinoic acid (10 µM, 1% serum); BDNF; NGF; phorbol esters (TPA); combined RA+BDNF (extensive neurite outgrowth).
 
**cSTAR analysis of neuroblastoma** [Rukhlenko2022]: Applied to RPPA data from cells stimulated with NGF (TrkA ligand) or BDNF (TrkB ligand). The STV identified JNK, ERK, AKT, and ribosomal protein S6 as the critical discriminators between differentiation and proliferation. The model predicted that combining **Trametinib** (MEK inhibitor) and **Gefitinib** (EGFR inhibitor) could convert the aggressive TrkB state to a benign TrkA-like state. EGFR signaling provided necessary background crosstalk — inhibiting it alongside MEK shifted the DPD toward the differentiated state. Experimental validation confirmed a synergy score of $51\% \pm 7\%$.
 
---
 
### 6.4. Macrophage Plasticity and Tuberculosis
 
Demonstrating the versatility of cSTAR, the group applied it to immunology [Rukhlenko2023TB]. In tuberculosis, the host macrophage response determines susceptibility. Macrophages exhibit plasticity between M1 (pro-inflammatory/microbicidal) and M2 (anti-inflammatory/repair) states. cSTAR analyzed RNA-seq data to define "Susceptible" vs. "Resistant" macrophage states. The model identified a core transcriptional network driven by lipid peroxidation and Type I interferon signaling as drivers of the susceptible state, and predicted that inhibiting specific nodes could shift the DPD of a susceptible macrophage toward that of a resistant one, restoring the cell's ability to control *Mycobacterium tuberculosis* infection.
 
---
 
### 6.5. Drug Resistance Mechanisms
 
**RAF dimerization and paradoxical activation:** Type I/I½ RAF inhibitors promote dimerization in RAS-active cells. Drug binds one protomer, transactivates drug-free partner. Results in paradoxical ERK activation in BRAF wild-type; causes secondary malignancies in patients with RAS mutations. RAF dimer interface: RKTR motif in αC-helix; NtA-region of dimer partner.
 
**Strategies to overcome:**
 
1. Paradox breakers (PLX8394, PLX7904).
2. Type II pan-RAF inhibitors (DFG-out conformation).
3. Type IV inhibitors (block dimerization).
4. Combination with MEKi (reduces paradox-induced tumors from 19% to 2–7%).
**Acquired resistance mechanisms:** RAF amplification/truncation; p61BRAF(V600E) splice variants; RTK upregulation; RAS mutations; mTOR activity increase; EGFR ligand upregulation.
 
**Adaptive resistance (feedback relief):** mTOR inhibition → MEK/ERK activation; MEK inhibition → PI3K/AKT activation; single-pathway inhibition → compensatory kinome reprogramming.
 
**Key finding** [Kholodenko2021]: Feedback loops alone cannot completely reactivate steady-state signaling. Complete reactivation requires either (1) network topology with two routes connecting the inhibited protein to the output, or (2) drug-induced kinase dimerization.
 
---
 
### 6.6. Key Cell Lines
 
| Cell Line | Subtype | Key Features |
|-----------|---------|-------------|
| MCF7 | Luminal A | ER+/PR+/HER2−; non-invasive; estrogen-dependent; wild-type p53 |
| MDA-MB-231 | TNBC/Basal | ER−/PR−/HER2−; highly invasive; mesenchymal; mutant p53 |
| T47D | Luminal | ER+, high PR |
| BT-474 | HER2+ | ER+/HER2+ |
| SKBR3 | HER2+ | ER−/HER2+ |
| HCC2157 | Basal | STAT3-driven |
| MDA-MB-468 | Basal | mTOR+PKC driven |
| SH-SY5Y | Neuroblastoma | Adrenergic/dopaminergic; TrkA/TrkB model |
| MEL-JUSO | Melanoma | NRAS Q61L/WT, HRAS G13D/G13D |
| A375 | Melanoma | BRAF V600E |
| HCC70 | Normal breast | Used as bridge control in CyTOF batches |
 
---
 
## 7. Computational Methods
 
### 7.1. ODE Modeling of Biochemical Networks
 
**General form:**
 
$$
\frac{dx_i}{dt} = f_i(\mathbf{x}, \mathbf{p}, t)
$$
 
where $\mathbf{x}$ = concentrations, $\mathbf{p}$ = parameters, $t$ = time.
 
**Mass action kinetics:**
 
$$
A + B \to C: \quad \frac{d[C]}{dt} = k\,[A]\,[B]
$$
 
**Michaelis–Menten kinetics:**
 
$$
v = \frac{V_{\max}[S]}{K_M + [S]}
$$
 
**Hill kinetics (cooperativity):**
 
$$
v = \frac{V_{\max}[S]^n}{K_{0.5}^n + [S]^n}
$$
 
where $n$ is the Hill coefficient ($n > 1$: positive cooperativity; $n < 1$: negative cooperativity). Software like PySB/BioNetGen can generate such ODEs automatically from reaction rules.
 
---
 
### 7.2. Steady-State Analysis
 
**Definition:** $dx_i/dt = 0$ for all species.
 
**Methods:** Newton–Raphson iteration; continuation methods (AUTO, PyDSTool); bifurcation analysis.
 
**Stability analysis:** Eigenvalues of the Jacobian matrix $J_{ij} = \partial f_i / \partial x_j$. Negative real parts → stable; positive → unstable.
 
---
 
### 7.3. Parameter Estimation
 
**Differential evolution:** Population-based stochastic optimization; mutation, crossover, selection operators; robust for high-dimensional parameter spaces.
 
**Objective function:** Sum of squared residuals between model and data; weighted by measurement uncertainty.
 
**Typical workflow:** Define parameter bounds → initialize population → iterate until convergence → validate with held-out data. The group sometimes runs thousands of DE iterations or hybrid global/local schemes. Python's `scipy.optimize.differential_evolution` is commonly used.
 
---
 
### 7.4. Bifurcation Analysis
 
**Saddle-node bifurcation:** Two fixed points (stable + unstable) collide and annihilate as a parameter changes; creates switch-like behavior and hysteresis.
 
**Bistability:** Two stable steady states separated by an unstable state; hysteresis in dose-response; requires positive feedback or double-negative feedback.
 
**Hopf bifurcation:** Eigenvalue crossing $\pm i\omega$ indicates onset of oscillations.
 
**Tools:** AUTO, XPPAUT, PyDSTool.
 
---
 
### 7.5. Drug Synergy Quantification
 
**Loewe additivity:**
 
$$
\frac{d_A}{D_A} + \frac{d_B}{D_B} = 1
$$
 
where $d_A, d_B$ = doses in combination; $D_A, D_B$ = doses for same effect alone.
 
**Isobole analysis:** Plot iso-effect curves; concave → synergy; convex → antagonism; linear → additivity.
 
**Bliss independence:**
 
$$
E_{AB} = E_A + E_B - E_A \cdot E_B
$$
 
where $E$ is fractional inhibition. Synergy if observed effect > $E_{AB}$.
 
**Combination Index (CI):** $\mathrm{CI} < 1$ synergistic; $\mathrm{CI} = 1$ additive; $\mathrm{CI} > 1$ antagonistic.
 
---
 
### 7.6. Sensitivity Analysis
 
**Local sensitivity:**
 
$$
S_i = \frac{\partial y}{\partial p_i} \cdot \frac{p_i}{y}
$$
 
**Global sensitivity:** Monte Carlo sampling; Sobol indices; Morris method (screening).
 
**Applications:** Identify critical parameters; guide experimental validation; assess model robustness. Sensitivity of DPD to rate constants highlights which reactions most control cell-state switching.
 
---
 
## 8. Technical Stack and Tools
 
### 8.1. Primary Languages
 
**Python:** Primary language; scientific stack (NumPy, SciPy, scikit-learn, matplotlib, seaborn); used for BioMASS, Pasmopy, and analysis workflows.
 
**MATLAB:** Legacy code; some BMRA implementations; older optimization routines.
 
**Java:** Used for low-level optimizations, performance-critical components, and some third-party tools (COPASI, SBML simulators).
 
---
 
### 8.2. PySB — Rule-Based Modeling Framework
 
**Repository:** [github.com/pysb/pysb](https://github.com/pysb/pysb)
 
**Purpose:** Build rule-based models of biochemical systems as Python programs, handling combinatorial complexity (e.g., multi-site phosphorylation, multi-partner binding).
 
**Key developers:** Lopez Lab (Vanderbilt), Sorger Lab (Harvard).
 
**Core concepts:** **Monomer** (molecular species with binding sites); **Parameter** (numerical values); **Initial** (starting conditions); **Rule** (reaction patterns, use `|` for reversible); **Observable** (quantities to track).
 
**Example:**
 
```python
from pysb import *
Model()
 
Monomer('L', ['s'])  # Ligand
Monomer('R', ['s'])  # Receptor
 
Parameter('L_0', 100)
Parameter('R_0', 200)
Parameter('kf', 1e-3)
Parameter('kr', 1e-3)
 
Initial(L(s=None), L_0)
Initial(R(s=None), R_0)
 
Rule('L_binds_R', L(s=None) + R(s=None) | L(s=1) % R(s=1), kf, kr)
Observable('LR', L(s=1) % R(s=1))
```
 
**BioNetGen integration:** Converts Python code to BNGL; enables network generation and simulation.
 
---
 
### 8.3. BioMASS
 
**Repository:** [github.com/biomass-dev/biomass](https://github.com/biomass-dev/biomass)
 
**Purpose:** Modeling and analysis of biological signaling systems [Imoto2020].
 
**Features:** Numerical simulation; parameter estimation (differential evolution); network analysis; result visualization; Text2Model (natural language → executable models); Morris method and Sobol index sensitivity analysis.
 
**Installation:** `pip install biomass` (Python 3.10+)
 
**Architecture:** Enforces a modular structure — `model.py` (defines ODEs and species), `parameters.py` (defines search space for rate constants), `set_search_param.py` (configures optimization boundaries). This separation allows rapid swapping of datasets or network topologies.
 
**Ensemble modeling:** Instead of seeking a single best-fit parameter set, BioMASS generates distributions of parameters that fit data equally well, capturing uncertainty and enabling probabilistic predictions.
 
**Typical workflow:**
 
```python
from biomass import create_model, optimize, run_simulation
 
model = create_model("model_name")
optimize(model, x_id=1, options={"maxiter": 10000})
run_simulation(model, viz_type="average")
```
 
---
 
### 8.4. Pasmopy
 
**Repository:** [github.com/pasmopy/pasmopy](https://github.com/pasmopy/pasmopy)
 
**Purpose:** Patient-specific modeling in Python; identify prognostic factors from personalized kinetic models [Imoto2022].
 
**Features:** Model construction from text; model personalization with patient transcriptome; outcome prediction from signaling dynamics; sensitivity analysis; BioMASS compatibility.
 
**Installation:** `pip install pasmopy` (Python 3.8+)
 
**Text2Model parser:**
 
```python
from pasmopy import Text2Model
 
reactions = """
E + S ⇄ ES | kf=0.003, kr=0.001 | E=100, S=50
ES → E + P | kf=0.002
"""
 
Text2Model("model.txt").convert()
```
 
**Reaction types supported:** Binding, dissociation, phosphorylation, dephosphorylation, transcription, translation, synthesis, degradation, translocation (14 types).
 
**Patient personalization strategy:** A "Reference Model" is first trained on a diverse panel of cell lines. To create a patient-specific model, the topology and kinetic rate constants are preserved from the Reference Model, but initial protein concentrations are scaled based on the patient's RNA-seq data (e.g., from TCGA):
 
$$
[X_i]_{\text{patient}} = [X_i]_{\text{ref}} \cdot \frac{\text{RNA}_{\text{patient},i}}{\text{RNA}_{\text{ref},i}}
$$
 
This assumes that while the physics of interaction (rates) is conserved, the abundance of components varies between patients, driving heterogeneity in drug response.
 
---
 
### 8.5. Development Environment
 
**Cursor:** Primary IDE. **Jupyter notebooks:** Analysis workflows, visualization, interactive exploration. **UCD servers:** HPC compute infrastructure (Linux-based, SLURM batch scheduler) for large-scale analysis. **Version control:** Git/GitHub.
 
---
 
### 8.6. Scientific Python Stack
 
| Package | Purpose |
|---------|---------|
| NumPy | Arrays, numerical operations |
| SciPy | ODE solvers, optimization, statistics |
| SymPy | Symbolic mathematics |
| scikit-learn | Machine learning (SVM for cSTAR) |
| matplotlib | Visualization |
| seaborn | Statistical visualization |
| pandas | Data manipulation |
 
---
 
## 9. Data Types and Sources
 
### 9.1. Mass Cytometry (CyTOF)
 
**Principle:** Antibodies labeled with heavy metal isotopes (lanthanide series); cells ionized by inductively coupled argon plasma; mass-to-charge separation by time-of-flight MS; single-cell resolution.
 
**Parameters:** ~135 theoretically possible; typically 40+ markers simultaneously.
 
**Advantages:** No spectral overlap; minimal autofluorescence; high-parameter; barcoding enables multiplexing.
 
**Applications:** Phospho-CyTOF for signaling; phenotypic profiling; drug response; tumor heterogeneity.
 
**Data in cSTAR:** 29 analytes typical; used for EMT analysis (Py2T cells); 62 breast cancer cell lines under five kinase inhibitors [Rukhlenko2024].
 
**Normalization strategy:** Equilibration beads containing known masses of isotopes are spiked into samples; the Normalizer software (Nolan lab) corrects for instrument signal drift over time.
 
**Batch correction:** For large-scale studies, a "bridge control" (typically HCC70 or a pooled sample) is included in every batch. Signal intensities are normalized relative to this control to eliminate batch effects.
 
**Gating:** Data is gated (e.g., FlowJo) to remove doublets, debris, and dead cells (cisplatin intercalation) before computational analysis.
 
---
 
### 9.2. RPPA (Reverse Phase Protein Array)
 
**Principle:** Cell lysates spotted on nitrocellulose; probed with validated antibodies; ~100s of analytes.
 
**Characteristics:** High reproducibility; sensitive for clinically significant phosphosites; antibody-dependent. Provides robust population-average data essential for calibrating ODE models.
 
**Comparison with MS:** RPPA: more standardized, fewer analytes. MS: comprehensive (10,000+ phosphosites), higher variability.
 
---
 
### 9.3. Mass Spectrometry Proteomics
 
**Applications:** Global phosphoproteomics; 7,995 proteins quantified in breast cancer cSTAR study.
 
**Preprocessing:** Peptide identification, intensity normalization (maxLFQ), log2 transformation.
 
**Data repositories:** PRIDE database (PXD accessions).
 
---
 
### 9.4. Single-Cell RNA-seq
 
**Analysis methods:** Trajectory inference; pseudotime ordering; RNA velocity. Quality filtering (mitochondrial gene content), normalization, dimensionality reduction (PCA/UMAP), clustering (Louvain).
 
**cSTAR applications:** EMT transitions (A549, DU145, MCF7, OVCA420 cells).
 
---
 
### 9.5. Public Databases
 
| Database | Content |
|----------|---------|
| PRIDE | Proteomics data (PXD028943 for cSTAR) |
| GEO | Gene expression (GSE accessions) |
| CCLE | Cancer Cell Line Encyclopedia |
| PharmacoDB / CTRP / PRISM | Drug sensitivity data |
| KEGG | Pathway information |
| STRING | Protein–protein interactions |
| Reactome | Pathway annotations |
| TCGA | The Cancer Genome Atlas |
| Pathway Commons | PPI lookup (edges and weights) |
| OmniPath | Integrated interaction resource |
 
**Scale:** 30,000+ gene interactions processed in cSTAR applications. A STRING network may have ~25,000 protein–protein interactions; CyTOF datasets can have millions of cell measurements (30–40 markers each).
 
---
 
## 10. Experimental Context
 
### 10.1. Kinase Inhibitors Used
 
**MEK inhibitors:** Trametinib (GSK1120212); Selumetinib (AZD6244); PD0325901; Pimasertib; Binimetinib.
 
**mTOR inhibitors:** Rapamycin/Sirolimus (allosteric mTORC1); Everolimus; Temsirolimus; Sapanisertib/MLN0128/TAK-228 (catalytic mTORC1/2); AZD8055; AZD2014.
 
**PI3K inhibitors:** Alpelisib (PI3Kα); GDC-0941 (pan-PI3K); NVP-BEZ235 (dual PI3K/mTOR); Idelalisib, Duvelisib, Copanlisib (PI3Kδ).
 
**AKT inhibitors:** MK-2206 (allosteric); Capivasertib (ATP-competitive); Ipatasertib.
 
**RAF inhibitors:** Type I½: Vemurafenib, Dabrafenib, PLX4720 (BRAF V600E selective). Paradox breakers: PLX8394, PLX7904. Type I: Encorafenib. Type II pan-RAF: Ponatinib, LY3009120.
 
**PKC inhibitors:** Staurosporine; K252a.
 
**Trk inhibitors:** CEP-701 (lestaurtinib); Larotrectinib (Vitrakvi, pan-Trk).
 
---
 
### 10.2. Growth Factor Stimulation
 
**NGF:** TrkA activation; differentiation induction. **BDNF:** TrkB activation; proliferation/survival. **EGF:** EGFR activation; transient ERK response.
 
**Protocols:** Time-course (minutes to hours); pulsed stimulation (3'/10', 3'/20', 3'/60'); dose-response matrices. Cells are typically serum-starved before stimulation.
 
---
 
### 10.3. Time-Course Design
 
**Early timepoints:** 7–17 minutes — acute signaling responses; proximal pathway activation.
 
**Late timepoints:** 40–60 minutes — feedback engagement; phenotypic pathway connections.
 
**Rationale:** Early = direct signaling; Late = network adaptation + phenotype determination. cSTAR typically models steady-state perturbations, but time-courses verify dynamics.
 
---
 
## 11. Key Publications (2002–2025)
 
### 11.1. Foundational
 
**Kholodenko BN et al., PNAS 2002** — "Untangling the wires: A strategy to trace functional interactions in signaling and gene networks." Introduced MRA. ~16,000+ citations. [Kholodenko2002]
 
### 11.2. Major Works (2015–2025)
 
| Year | Journal | Title / Topic | Key Contribution |
|------|---------|---------------|------------------|
| 2015 | Cell Reports | Drug Resistance from Kinase Dimerization | Thermodynamic modeling of allosteric inhibitor effects |
| 2015 | Sci Signal | Signaling pathway models as biomarkers | Patient-specific JNK simulations predict neuroblastoma survival |
| 2016 | Sci Signal | Integrating network reconstruction with mechanistic modeling | BMRA integration for cancer therapy prediction |
| 2018 | Cell Systems | Dissecting RAF Inhibitor Resistance | Rule-based structural modeling; predicted Type I½ + Type II RAF inhibitor synergy |
| 2018 | Sci Rep / PLOS Comp Biol | Impact of noise and experimental design on MRA | Optimization recommendations for perturbation experiments |
| 2020 | eLife | RhoGTPase waves in cell migration | Periodic wave coordination of leading/trailing edge dynamics |
| 2020 | Cancers | Computational framework for cancer signaling | BioMASS framework for RNA-seq-based signaling prediction |
| 2021 | Cell Reports | Systematic analysis of signaling reactivation | Proved feedback loops alone cannot fully reactivate signaling |
| **2022** | ***Nature*** | **Control of cell state transitions** | **cSTAR methodology; 84+ citations, 34k+ accesses** |
| 2022 | iScience | Text-based patient-specific modeling | Pasmopy framework for patient-specific ODE models |
| 2023 | Sci Advances | cSTAR for tuberculosis | TB-susceptible vs. resistant macrophage states |
| 2023 | Trends Cell Biol | Reversing pathological cell states (Review) | cSTAR methodology review |
| 2023 | Cancers | RAF overexpression resistance | Conformation-specific RAF inhibitor combinations |
| 2024 | Cancers | Breast cancer cell state models | cSTAR applied to BC subtypes; identified mTOR, PKC, STAT3 drivers |
| 2024 | Bioinform Adv | Extending BioMASS | Text2Model and KEGG integration for automated model construction |
| 2024 | Cell Reports | Pancreatic cancer RAF inhibitors | Cell-specific models; KRAS mutation-specific therapies |
| 2025 | Sci Advances | cSTAR vascular remodeling | Endothelial cell cycle regulates artery remodeling (Yale collaboration) |
 
---
 
## 12. Terminology Glossary
 
### 12.1. Acronyms
 
| Acronym | Definition |
|---------|------------|
| AKT | Protein Kinase B (PKB) |
| BDNF | Brain-Derived Neurotrophic Factor |
| BMRA | Bayesian Modular Response Analysis |
| BNGL | BioNetGen Language |
| cSTAR | cell State Transition Assessment and Regulation |
| CyTOF | Cytometry by Time-of-Flight |
| DPD | Dynamic Phenotype Descriptor |
| DUSP | Dual-Specificity Phosphatase |
| EGF | Epidermal Growth Factor |
| EGFR | Epidermal Growth Factor Receptor |
| EMT | Epithelial–Mesenchymal Transition |
| ER | Estrogen Receptor |
| ERBB | Erythroblastic Leukemia Viral Oncogene Homolog |
| ERK | Extracellular Signal-Regulated Kinase |
| GRC | Global Response Coefficient |
| HER2 | Human Epidermal Growth Factor Receptor 2 |
| LRC | Local Response Coefficient |
| MAPK | Mitogen-Activated Protein Kinase |
| MCA | Metabolic Control Analysis |
| MEK | MAPK/ERK Kinase |
| MRA | Modular Response Analysis |
| mTOR | Mechanistic Target of Rapamycin |
| mTORC1/2 | mTOR Complex 1/2 |
| NGF | Nerve Growth Factor |
| ODE | Ordinary Differential Equation |
| PCA | Principal Component Analysis |
| PI3K | Phosphoinositide 3-Kinase |
| PIP$_2$/PIP$_3$ | Phosphatidylinositol (4,5)-bisphosphate / (3,4,5)-trisphosphate |
| PKC | Protein Kinase C |
| PR | Progesterone Receptor |
| PTEN | Phosphatase and Tensin Homolog |
| RAF | Rapidly Accelerated Fibrosarcoma kinase |
| RAS | Rat Sarcoma viral oncogene homolog |
| RPPA | Reverse Phase Protein Array |
| RTK | Receptor Tyrosine Kinase |
| S6K | S6 Kinase |
| SBI | Systems Biology Ireland |
| STAT3 | Signal Transducer and Activator of Transcription 3 |
| STV | State Transition Vector |
| SVM | Support Vector Machine |
| TNBC | Triple-Negative Breast Cancer |
| Trk | Tropomyosin receptor kinase |
| UCD | University College Dublin |
 
### 12.2. Technical Terms
 
**Attractor:** Stable steady state in dynamical systems; represents a stable cell phenotype in the Waddington landscape.
 
**Bistability:** Existence of two stable steady states for the same parameter values; enables switch-like behavior; requires positive feedback or double-negative feedback. Transition requires crossing a threshold.
 
**Connection coefficient:** Element $r_{ij}$ of the MRA local response matrix; quantifies direct causal influence of module $j$ on module $i$.
 
**Core network:** Subset of signaling modules with highest STV component values; controls cell-wide network transitions.
 
**Digital twin:** A personalized computational model replicating a biological cell or patient system; enables in-silico prediction of interventions. In cSTAR, each calibrated ODE model + STV yields a digital twin.
 
**Feedback amplifier:** Circuit topology where output feeds back to input; negative feedback confers robustness and linearity.
 
**Global response:** Total (system-wide) change in module activity when another module is perturbed; includes direct and indirect effects.
 
**Hyperplane:** Decision boundary in SVM; separates cell states in feature space.
 
**Isobole:** Line of equal effect in drug combination space; shape indicates synergy (concave) or antagonism (convex).
 
**Jacobian matrix:** Matrix of partial derivatives $J_{ij} = \partial f_i / \partial x_j$ of an ODE system; eigenvalues determine stability.
 
**Local response:** Direct (isolated) change in module activity when an effector module changes; all other modules held constant.
 
**Module:** Functional unit in network; can be single protein or pathway; defined by measurable output.
 
**Order parameter:** Variable distinguishing phases in a phase transition; the DPD serves as an order parameter for cell states.
 
**Paradoxical activation:** ERK activation by RAF inhibitors in RAS-mutant cells due to drug-induced RAF dimerization.
 
**Perturbation specificity:** Requirement that an experimental perturbation affects only one network module.
 
**Phosphosite:** Specific amino acid residue that can be phosphorylated (Ser, Thr, Tyr).
 
**Potential function:** Mathematical function whose gradient gives the restoring force; minima correspond to stable states.
 
**Restoring force:** Force returning the system toward a stable steady state; derived from the potential function.
 
**Saddle-node bifurcation:** Bifurcation where two fixed points collide and disappear; creates switch-like behavior and hysteresis.
 
**Signaling force:** Force driving the system away from its current state; determined by upstream signaling dynamics.
 
**Steady state:** Condition where all concentrations are constant ($dx_i/dt = 0$ for all species).
 
**Ultrasensitivity:** Response steeper than Michaelis–Menten; Hill coefficient $n > 1$; approaches switch-like behavior.
 
---
 
## 13. GitHub Repositories
 
| Repository | URL | Purpose |
|------------|-----|---------|
| cSTAR | [github.com/OleksiiR/cSTAR_Nature](https://github.com/OleksiiR/cSTAR_Nature) | *Nature* 2022 cSTAR code |
| BioMASS | [github.com/biomass-dev/biomass](https://github.com/biomass-dev/biomass) | Signaling system modeling |
| Pasmopy | [github.com/pasmopy/pasmopy](https://github.com/pasmopy/pasmopy) | Patient-specific modeling |
| PySB | [github.com/pysb/pysb](https://github.com/pysb/pysb) | Rule-based modeling |
| BioNetGen | [github.com/RuleWorld/bionetgen](https://github.com/RuleWorld/bionetgen) | Network generation |
| Hiroaki Imoto | [github.com/himoto](https://github.com/himoto) | Personal repositories |
| hillfit | [github.com/himoto/hillfit](https://github.com/himoto/hillfit) | Hill equation fitting |
 
---
 
## 14. Data Availability
 
**cSTAR Nature 2022:** Mass spec data: PRIDE PXD028943; Code: [github.com/OleksiiR/cSTAR_Nature](https://github.com/OleksiiR/cSTAR_Nature).
 
**Key datasets used:** SH-SY5Y neuroblastoma phosphoproteomics; SKMEL-133 melanoma RPPA; scRNA-seq EMT (A549, DU145, MCF7, OVCA420); CyTOF EMT (Py2T); Breast cancer CyTOF (29 analytes, 62 cell lines); Breast cancer MS proteomics (7,995 proteins).
 
---
 
## 15. Funding Sources
 
- **Science Foundation Ireland (SFI):** CSET programme, Investigator grants, Research Infrastructure.
- **National Institutes of Health (NIH):** R01CA244660, various grants (2009–2028).
- **European Union:** NanoCommons (731032), Horizon 2020, FP7.
- **Irish Research Council (IRC):** GOIPG/2020/1361, Pathway programme.
- **Cancer Research UK / Brain Tumour Charity:** C42454/A28596.
- **Children's Health Foundation.**
- **JSPS:** Overseas Research Fellowships (Imoto).
---
 
## 16. Future Outlook
 
The research trajectory of the group represents a coherent move toward the clinical realization of digital twins. By creating mathematical replicas of patient-specific signaling networks (via Pasmopy) and defining disease states geometrically rather than linguistically (via cSTAR), they offer a roadmap for rational polypharmacology.
 
Current efforts are expanding these frameworks to include **spatiotemporal dynamics**. Kholodenko has long argued that the spatial distribution of signaling molecules (gradients) encodes positional information essential for cell fate. Future iterations of cSTAR and BioMASS are expected to integrate reaction-diffusion equations to model how spatial localization of kinases (e.g., membrane vs. nucleus) influences the DPD.
 
Furthermore, the integration of **deep learning** with mechanistic modeling is an active frontier. While cSTAR currently uses SVMs for classification, the core dynamics remain ODE-based. Hybrid models using neural networks to approximate unknown kinetic terms (Neural ODEs) represent the next logical step, potentially allowing simulation of entire tissues or tumor microenvironments.
 
---
 
## References
 
[Brown1999] Brown GC, Kholodenko BN. "Spatial gradients of cellular phospho-proteins." *FEBS Letters* 457:452, 1999.
 
[Imoto2020] Imoto H, et al. "A Computational Framework for Prediction and Analysis of Cancer Signaling Dynamics from RNA Sequencing Data." *Cancers* 12:2878, 2020. [github.com/biomass-dev/biomass](https://github.com/biomass-dev/biomass)
 
[Imoto2022] Imoto H, et al. "A text-based computational framework for patient-specific modeling for classification of cancers." *iScience* 25:103944, 2022. [PubMed: 35535207](https://pubmed.ncbi.nlm.nih.gov/35535207/)
 
[Imoto2024] Imoto H, et al. "Extending BioMASS to construct mathematical models from external knowledge." *Bioinformatics Advances* 2024. [PubMed: 38606187](https://pubmed.ncbi.nlm.nih.gov/38606187/)
 
[Kholodenko1999] Kholodenko BN, et al. *J Biol Chem* 274:30169, 1999.
 
[Kholodenko2000] Kholodenko BN. "Negative feedback and ultrasensitivity can bring about oscillations in the mitogen-activated protein kinase cascades." *Eur J Biochem* 267:1583, 2000.
 
[Kholodenko2002] Kholodenko BN, et al. "Untangling the wires: A strategy to trace functional interactions in signaling and gene networks." *PNAS* 99:12841, 2002. [doi.org/10.1073/pnas.192442699](https://www.pnas.org/doi/10.1073/pnas.192442699)
 
[Kholodenko2006] Kholodenko BN. "Cell-signalling dynamics in time and space." *Nat Rev Mol Cell Biol* 7:165, 2006.
 
[Kholodenko2015] Kholodenko BN, et al. "Drug Resistance Resulting from Kinase Dimerization." *Cell Reports* 12:1939, 2015.
 
[Kholodenko2021] Kholodenko BN, et al. "A systematic analysis of signaling reactivation and drug resistance." *Cell Reports* 35:109157, 2021.
 
[Markevich2004] Markevich NI, et al. "Signaling switches and bistability arising from multisite phosphorylation." *J Cell Biol* 164:353, 2004.
 
[Rukhlenko2018] Rukhlenko OS, et al. "Dissecting RAF Inhibitor Resistance by Structure-based Modeling." *Cell Systems* 7:161–179, 2018.
 
[Rukhlenko2022] Rukhlenko OS, et al. "Control of cell state transitions." *Nature* 609:975–985, 2022. [doi.org/10.1038/s41586-022-05194-y](https://www.nature.com/articles/s41586-022-05194-y) — [github.com/OleksiiR/cSTAR_Nature](https://github.com/OleksiiR/cSTAR_Nature)
 
[Rukhlenko2023TB] Rukhlenko OS, et al. "Cell state transition analysis identifies interventions that improve control of *M. tuberculosis* infection by susceptible macrophages." *Science Advances* 2023.
 
[Rukhlenko2024] Rukhlenko OS, et al. "Cell State Transition Models Stratify Breast Cancer Cell Phenotypes and Reveal New Therapeutic Targets." *Cancers* 16(13):2354, 2024. [doi.org/10.3390/cancers16132354](https://www.mdpi.com/2072-6694/16/13/2354)
 
[Rukhlenko2025] Rukhlenko OS, et al. "cSTAR vascular remodeling." *Science Advances* 2025 (Yale collaboration).
 
[Santra2013] Santra T, et al. "Integrating Bayesian variable selection with Modular Response Analysis to infer biochemical network topology." *BMC Systems Biology* 7:57, 2013. [PubMed: 23829771](https://pubmed.ncbi.nlm.nih.gov/23829771/)
 
[Thomaseth2018] Thomaseth C, et al. "Impact of measurement noise, experimental design, and estimation methods on Modular Response Analysis based network reconstruction." *PLOS Computational Biology* 2018. [PMC6212399](https://pmc.ncbi.nlm.nih.gov/articles/PMC6212399/)
 
---
 
**Patents:** UK GB202107576D0 (2021); EU EP4348652A1 (2022); US US20240274226A1 (2022); WIPO WO2022248728A1 (2022).
 
---
 
*This reference document consolidates information for AI-assisted computational systems biology research at the Kholodenko/Rukhlenko Group, Systems Biology Ireland, University College Dublin. Last updated: February 2026.*
