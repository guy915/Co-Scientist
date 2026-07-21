"""Build corpus/sbi_ucd/catalog.json from the corpus on disk.

The catalog is what every SBI/UCD run sees: the title and abstract of the
core papers plus a title index of the rest, always in context, with the
`paper_id` the agent passes to `fetch_paper` (see paper_corpus.format_catalog).
It is committed rather than derived at runtime, and this script is what keeps
it in step with the corpus directory.

Two sources feed it, because the corpus has two kinds of paper:

  Core (15).      The group's flagship methods and findings. Their `.md`
                  files are PDF-extracted sanitized text in which only two of
                  fifteen carry a recoverable "Abstract" heading, so their
                  abstracts cannot be read off disk and are hand-verified
                  here in ``CORE``. Each abstract was confirmed against the
                  paper's own PDF; a fuzzy title match would silently attach a
                  plausible-but-wrong abstract, the worst failure mode here
                  since it is invisible downstream. Three of the fifteen are
                  not the group's own work and carry an ``attribution`` that
                  the prompt surfaces so they are not miscredited.

  Harvested (195). Every other PubMed paper with Kholodenko or Rukhlenko as
                  an author, collected by ``dev/harvest_group_pubmed.py``,
                  which writes one `.md` file per paper with a structured
                  header. Their metadata is read back out of that header
                  rather than restated here: the header is machine-written to
                  a fixed shape, so parsing it keeps a single source of truth
                  and cannot drift from the file the agent actually fetches.

The script refuses to write if the catalog and the corpus directory disagree
in either direction -- a `.md` with no entry, or an entry with no `.md` --
so an advertised `fetch_paper` can never return nothing and a fetchable paper
is never left out of the catalog.

Adding papers: run ``dev/harvest_group_pubmed.py`` to pull new work from
PubMed, then re-run this. Adding a hand-curated core paper: drop its
sanitized text into corpus/sbi_ucd/, add a ``CORE`` entry with a verified
abstract, and re-run.

Run: python app/dev/build_catalog.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Repo-relative so this runs from any checkout: app/dev/ -> repo root.
CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "sbi_ucd"

# paper_id -> (title, pmid, doi, source, attribution, abstract).
# pmid/doi are None for the one paper PubMed does not index cleanly. These
# fifteen are the injected core; their abstracts are hand-verified because
# their `.md` files are sanitized PDF text with no clean abstract to parse.
CORE: dict[str, tuple[str, str | None, str | None, str, str, str]] = {}

CORE["a-systematic-analysis-of-signaling-reactivation-and-drug-resistance"] = (
    "A systematic analysis of signaling reactivation and drug resistance",
    "34038718", "10.1016/j.celrep.2021.109157", "pubmed", "group",
    "Increasing evidence suggests that the reactivation of initially inhibited signaling pathways causes drug resistance. Here, we analyze how network topologies affect signaling responses to drug treatment. Network-dependent drug resistance is commonly attributed to negative and positive feedback loops. However, feedback loops by themselves cannot completely reactivate steady-state signaling. Newly synthesized negative feedback regulators can induce a transient overshoot but cannot fully restore output signaling. Complete signaling reactivation can only occur when at least two routes, an activating and inhibitory, connect an inhibited upstream protein to a downstream output. Irrespective of the network topology, drug-induced overexpression or increase in target dimerization can restore or even paradoxically increase downstream pathway activity. Kinase dimerization cooperates with inhibitor-mediated alleviation of negative feedback. Our findings inform drug development by considering network context and optimizing the design drug combinations. As an example, we predict and experimentally confirm specific combinations of RAF inhibitors that block mutant NRAS signaling.",
)
CORE["a-text-based-computational-framework-for-patient-specific-modeling-for-classific"] = (
    "A text-based computational framework for patient-specific modeling for classification of cancers",
    "35535207", "10.1016/j.isci.2022.103944", "pubmed", "member prior work",
    "Patient heterogeneity precludes cancer treatment and drug development; hence, development of methods for finding prognostic markers for individual treatment is urgently required. Here, we present Pasmopy (Patient-Specific Modeling in Python), a computational framework for stratification of patients using signaling dynamics. Pasmopy converts texts and sentences on biochemical systems into an executable mathematical model. Using this framework, we built a model of the ErbB receptor signaling network, trained in cultured cell lines, and performed simulation of 377 patients with breast cancer using The Cancer Genome Atlas (TCGA) transcriptome datasets. The temporal dynamics of Akt, extracellular signal-regulated kinase (ERK), and c-Myc in each patient were able to accurately predict the difference in prognosis and sensitivity to kinase inhibitors in triple-negative breast cancer (TNBC). Our model applies to any type of signaling network and facilitates the network-based use of prognostic markers and prediction of drug response.",
)
CORE["cell-state-transition-analysis-identifies-interventions-thatimprove-control-of-m"] = (
    "Cell state transition analysis identifies interventions that improve control of infection by susceptible macrophages",
    "37756395", "10.1126/sciadv.adh4119", "pubmed", "group",
    "Understanding cell state transitions and purposefully controlling them to improve therapies is a longstanding challenge in biological research and medicine. Here, we identify a transcriptional signature that distinguishes activated macrophages from the tuberculosis (TB) susceptible and resistant mice. We then apply the cSTAR (cell state transition assessment and regulation) approach to data from screening-by-RNA sequencing to identify chemical perturbations that shift the transcriptional state of tumor necrosis factor (TNF)-activated TB-susceptible macrophages toward that of TB-resistant cells, i.e., prevents their aberrant activation without suppressing beneficial TNF responses. Last, we demonstrate that the compounds identified with this approach enhance the resistance of the TB-susceptible mouse macrophages to virulent Mycobacterium tuberculosis.",
)
CORE["cell-state-transition-models-stratify-breast-cancer-cell-phenotypes-and-reveal-n"] = (
    "Cell State Transition Models Stratify Breast Cancer Cell Phenotypes and Reveal New Therapeutic Targets",
    "39001416", "10.3390/cancers16132354", "pubmed", "group",
    "Understanding signaling patterns of transformation and controlling cell phenotypes is a challenge of current biology. Here we applied a cell State Transition Assessment and Regulation (cSTAR) approach to a perturbation dataset of single cell phosphoproteomic patterns of multiple breast cancer (BC) and normal breast tissue-derived cell lines. Following a separation of luminal, basal, and normal cell states, we identified signaling nodes within core control networks, delineated causal connections, and determined the primary drivers underlying oncogenic transformation and transitions across distinct BC subtypes. Whereas cell lines within the same BC subtype have different mutational and expression profiles, the architecture of the core network was similar for all luminal BC cells, and mTOR was a main oncogenic driver. In contrast, core networks of basal BC were heterogeneous and segregated into roughly four major subclasses with distinct oncogenic and BC subtype drivers. Likewise, normal breast tissue cells were separated into two different subclasses. Based on the data and quantified network topologies, we derived mechanistic cSTAR models that serve as digital cell twins and allow the deliberate control of cell movements within a Waddington landscape across different cell states. These cSTAR models suggested strategies of normalizing phosphorylation networks of BC cell lines using small molecule inhibitors.",
)
CORE["control-of-cell-state-transitions"] = (
    "Control of cell state transitions",
    "36104561", "10.1038/s41586-022-05194-y", "pubmed", "group",
    "Understanding cell state transitions and purposefully controlling them is a longstanding challenge in biology. Here we present cell state transition assessment and regulation (cSTAR), an approach for mapping cell states, modelling transitions between them and predicting targeted interventions to convert cell fate decisions. cSTAR uses omics data as input, classifies cell states, and develops a workflow that transforms the input data into mechanistic models that identify a core signalling network, which controls cell fate transitions by influencing whole-cell networks. By integrating signalling and phenotypic data, cSTAR models how cells manoeuvre in Waddington's landscape and make decisions about which cell fate to adopt. Notably, cSTAR devises interventions to control the movement of cells in Waddington's landscape. Testing cSTAR in a cellular model of differentiation and proliferation shows a high correlation between quantitative predictions and experimental data. Applying cSTAR to different types of perturbation and omics datasets, including single-cell data, demonstrates its flexibility and scalability and provides new biological insights. The ability of cSTAR to identify targeted perturbations that interconvert cell fates will enable designer approaches for manipulating cellular development pathways and mechanistically underpinned therapeutic interventions.",
)
CORE["cstar-analysis-identifies-endothelial-cell-cycle-as-a-key-regulator-of-flow-depe"] = (
    "cSTAR analysis identifies endothelial cell cycle as a key regulator of flow-dependent artery remodeling",
    "39752487", "10.1126/sciadv.ado9970", "pubmed", "group",
    "Fluid shear stress (FSS) from blood flow sensed by vascular endothelial cells (ECs) determines vessel behavior, but regulatory mechanisms are only partially understood. We used cell state transition assessment and regulation (cSTAR), a powerful computational method, to elucidate EC transcriptomic states under low shear stress (LSS), physiological shear stress (PSS), high shear stress (HSS), and oscillatory shear stress (OSS) that induce vessel inward remodeling, stabilization, outward remodeling, or disease susceptibility, respectively. Combined with a publicly available database on EC transcriptomic responses to drug treatments, this approach inferred a regulatory network controlling EC states and made several notable predictions. Particularly, inhibiting cell cycle-dependent kinase (CDK) 2 was predicted to initiate inward remodeling and promote atherogenesis. In vitro, PSS activated CDK2 and induced late G1 cell cycle arrest. In mice, EC deletion of CDK2 triggered inward artery remodeling, pulmonary and systemic hypertension, and accelerated atherosclerosis. These results validate use of cSTAR and identify key determinants of normal and pathological artery remodeling.",
)
CORE["impact-of-measurement-noise-experimental-design-and-estimation-methods-on-modula"] = (
    "Impact of measurement noise, experimental design, and estimation methods on Modular Response Analysis based network reconstruction",
    "30385767", "10.1038/s41598-018-34353-3", "pubmed", "group",
    "Modular Response Analysis (MRA) is a method to reconstruct signalling networks from steady-state perturbation data which has frequently been used in different settings. Since these data are usually noisy due to multi-step measurement procedures and biological variability, it is important to investigate the effect of this noise onto network reconstruction. Here we present a systematic study to investigate propagation of noise from concentration measurements to network structures. Therefore, we design an in silico study of the MAPK and the p53 signalling pathways with realistic noise settings. We make use of statistical concepts and measures to evaluate accuracy and precision of individual inferred interactions and resulting network structures. Our results allow to derive clear recommendations to optimize the performance of MRA based network reconstruction: First, large perturbations are favorable in terms of accuracy even for models with non-linear steady-state response curves. Second, a single control measurement for different perturbation experiments seems to be sufficient for network reconstruction, and third, we recommend to execute the MRA workflow with the mean of different replicates for concentration measurements rather than using computationally more involved regression strategies.",
)
CORE["integrating-bayesian-variable-selection-with-modular-response-analysis-to-infer-"] = (
    "Integrating Bayesian variable selection with Modular Response Analysis to infer biochemical network topology",
    "23829771", "10.1186/1752-0509-7-57", "pubmed", "group",
    "Recent advancements in genetics and proteomics have led to the acquisition of large quantitative data sets. However, the use of these data to reverse engineer biochemical networks has remained a challenging problem. Many methods have been proposed to infer biochemical network topologies from different types of biological data. Here, we focus on unraveling network topologies from steady state responses of biochemical networks to successive experimental perturbations. We propose a computational algorithm which combines a deterministic network inference method termed Modular Response Analysis (MRA) and a statistical model selection algorithm called Bayesian Variable Selection, to infer functional interactions in cellular signaling pathways and gene regulatory networks. It can be used to identify interactions among individual molecules involved in a biochemical pathway or reveal how different functional modules of a biological network interact with each other to exchange information. In cases where not all network components are known, our method reveals functional interactions which are not direct but correspond to the interaction routes through unknown elements. Using computer simulated perturbation responses of signaling pathways and gene regulatory networks from the DREAM challenge, we demonstrate that the proposed method is robust against noise and scalable to large networks. We also show that our method can infer network topologies using incomplete perturbation datasets. Consequently, we have used this algorithm to explore the ERBB regulated G1/S transition pathway in certain breast cancer cells to understand the molecular mechanisms which cause these cells to become drug resistant. The algorithm successfully inferred many well characterized interactions of this pathway by analyzing experimentally obtained perturbation data. Additionally, it identified some molecular interactions which promote drug resistance in breast cancer cells.",
)
CORE["integrating-network-reconstruction-with-mechanistic-modeling-to-predict-cancer-t"] = (
    "Integrating network reconstruction with mechanistic modeling to predict cancer therapies",
    "27879396", "10.1126/scisignal.aae0535", "pubmed", "group",
    "Signal transduction networks are often rewired in cancer cells. Identifying these alterations will enable more effective cancer treatment. We developed a computational framework that can identify, reconstruct, and mechanistically model these rewired networks from noisy and incomplete perturbation response data and then predict potential targets for intervention. As a proof of principle, we analyzed a perturbation data set targeting epidermal growth factor receptor (EGFR) and insulin-like growth factor 1 receptor (IGF1R) pathways in a panel of colorectal cancer cells. Our computational approach predicted cell line-specific network rewiring. In particular, feedback inhibition of insulin receptor substrate 1 (IRS1) by the kinase p70S6K was predicted to confer resistance to EGFR inhibition, suggesting that disrupting this feedback may restore sensitivity to EGFR inhibitors in colorectal cancer cells. We experimentally validated this prediction with colorectal cancer cell lines in culture and in a zebrafish (Danio rerio) xenograft model.",
)
CORE["lipid-peroxidation-and-type-i-interferon-coupling-fuels-pathogenic-macrophage-ac"] = (
    "Lipid peroxidation and type I interferon coupling fuels pathogenic macrophage activation causing tuberculosis susceptibility",
    "41037321", "10.7554/eLife.106814", "pubmed", "group",
    "A quarter of the human population is infected with, but less than 10% of those infected develop pulmonary TB. We developed a genetically defined sst1-susceptible mouse model that uniquely reproduces a defining feature of human TB: the development of necrotic lung granulomas and determined that the sst1-susceptible phenotype was driven by the aberrant macrophage activation. This study demonstrates that the aberrant response of the sst1-susceptible macrophages to prolonged stimulation with TNF is primarily driven by conflicting Myc and antioxidant response pathways leading to a coordinated failure (1) to properly sequester intracellular iron and (2) to activate ferroptosis inhibitor enzymes. Consequently, iron-mediated lipid peroxidation fueled superinduction of Ifnbeta and sustained the type I interferon (IFN-I) pathway hyperactivity that locked the sst1-susceptible macrophages in a state of unresolving stress and compromised their resistance to Mtb. The accumulation of the aberrantly activated, stressed, macrophages within the granuloma microenvironment led to the local failure of anti-tuberculosis immunity and tissue necrosis. The upregulation of the Myc pathway in peripheral blood cells of human TB patients was significantly associated with poor outcomes of TB treatment. Thus, Myc dysregulation in activated macrophages results in an aberrant macrophage activation and represents a novel target for host-directed TB therapies.",
)
CORE["modular-response-analysis-of-cellular-regulatory-networks"] = (
    "Modular response analysis of cellular regulatory networks",
    "12384053", "10.1006/jtbi.2002.3096", "pubmed", "group",
    "The sheer complexity of intracellular regulatory networks, which involve signal transducing, metabolic, and genetic circuits, hampers our ability to carry out a quantitative analysis of their functions. Here, we describe an approach that greatly simplifies this type of analysis by capitalizing on the modular organization of such networks. Steady-state responses of the network as a whole are accounted for in terms of intermodular interactions between the modules alone; processes operating solely within modules need not be considered when analysing signal transfer through the entire network. The intermodular interactions are quantified through (local) response coefficients which populate an interaction map (matrix). This matrix can be derived from a biochemical or molecular biological analysis of (macro) molecular interactions that constitute the regulatory network. The approach is illustrated by two examples: (i) mitogenic signalling through the mitogen-activated protein kinase cascade in the epidermal growth factor receptor network and (ii) regulation of ammonium assimilation in Escherichia coli.",
)
CORE["modular-response-analysis-reformulated-as-a-multilinear-regression-problem"] = (
    "Modular response analysis reformulated as a multilinear regression problem",
    "37021935", "10.1093/bioinformatics/btad166", "pubmed", "external",
    "Modular response analysis (MRA) is a well-established method to infer biological networks from perturbation data. Classically, MRA requires the solution of a linear system, and results are sensitive to noise in the data and perturbation intensities. Due to noise propagation, applications to networks of 10 nodes or more are difficult. We propose a new formulation of MRA as a multilinear regression problem. This enables to integrate all the replicates and potential additional perturbations in a larger, over-determined, and more stable system of equations. More relevant confidence intervals on network parameters can be obtained, and we show competitive performance for networks of size up to 1000. Prior knowledge integration in the form of known null edges further improves these results. The R code used to obtain the presented results is available from GitHub: https://github.com/J-P-Borg/BioInformatics.",
)
CORE["reconstructing-static-and-dynamic-models-of-signaling-pathways-using-modular-res"] = (
    "Reconstructing static and dynamic models of signaling pathways using Modular Response Analysis",
    None, "10.1016/j.coisb.2018.02.003", "paper-abstract", "group",
    "In this review we discuss the origination and evolution of Modular Response Analysis (MRA), which is a physics-based method for reconstructing quantitative topological models of biochemical pathways. We first focus on the core theory of MRA, demonstrating how both the direction and the strength of local, causal connections between network modules can be precisely inferred from the global responses of the entire network to a sufficient number of perturbations, under certain conditions. Subsequently, we analyze statistical reformulations of MRA and show how MRA is used to build and calibrate mechanistic models of biological networks. We further discuss what sets MRA apart from other network reconstruction methods and outline future directions for MRA-based methods of network reconstruction.",
)
CORE["testing-and-overcoming-the-limitations-of-modular-response-analysis"] = (
    "Testing and overcoming the limitations of modular response analysis",
    "40062619", "10.1093/bib/bbaf098", "pubmed", "external",
    "Modular response analysis (MRA) is an effective method to infer biological networks from perturbation data. However, it has several limitations such as strong sensitivity to noise, need of performing independent perturbations that hit a single node at a time, and linear approximation of dependencies within the network. Previously, we addressed the sensitivity of MRA to noise by reinterpreting MRA as a multilinear regression problem. We demonstrated the advantages of this approach over the conventional MRA and other known inference methods, particularly in handling noise measurements and nonlinear networks. Here, we provide new contributions to complement this theory. First, we overcome the need of perturbations to be independent, thereby augmenting MRA applicability. Second, using analysis of variance and lack-of-fit tests, we can now assess MRA compatibility with the data and identify the primary source of errors. In cases where nonlinearity prevails, we propose extending the model to a second-order polynomial. Third, we demonstrate how to effectively use prior knowledge about a network. We validated these results using 4 networks with known dynamics (3, 4, and 6 nodes) and 40 simulated networks, ranging from 10 to 200 nodes. Finally, we incorporated these innovations into our R software package MRARegress to offer a comprehensive, extended theory for MRA and to facilitate its use by the community.",
)
CORE["untangling-the-wires-a-strategy-to-trace-functional-interactions-in-signaling-an"] = (
    "Untangling the wires: a strategy to trace functional interactions in signaling and gene networks",
    "12242336", "10.1073/pnas.192442699", "pubmed", "group",
    "Emerging technologies have enabled the acquisition of large genomics and proteomics data sets. However, current methodologies for analysis do not permit interpretation of the data in ways that unravel cellular networking. We propose a quantitative method for determining functional interactions in cellular signaling and gene networks. It can be used to explore cell systems at a mechanistic level or applied within a modular framework, which dramatically decreases the number of variables to be assayed. This method is based on a mathematical derivation that demonstrates how the topology and strength of network connections can be retrieved from experimentally measured network responses to successive perturbations of all modules. Importantly, our analysis can reveal functional interactions even when the components of the system are not all known. Under these circumstances, some connections retrieved by the analysis will not be direct but correspond to the interaction routes through unidentified elements. The method is tested and illustrated by using computer-generated responses of a modeled mitogen-activated protein kinase cascade and gene network.",
)

# The harvested header written by dev/harvest_group_pubmed.py:
#   # Title
#
#   *Journal, Year.* PMID: 12345. DOI: 10.xxxx/yyy.
#
#   ## Abstract
#   ...
_META = re.compile(
    r"^\*(?P<where>.*?)\.\*\s*(?:PMID:\s*(?P<pmid>\d+)\.)?\s*"
    r"(?:DOI:\s*(?P<doi>\S+?)\.)?\s*$"
)


def parse_harvested(path: Path) -> dict:
    """Read a harvested paper's metadata back out of its `.md` header.

    Args:
        path: The corpus markdown file.

    Returns:
        The entry's ``title``, ``abstract``, ``pmid``, ``doi``, ``year``, and
        ``journal``. Any field the header omits comes back empty.

    Raises:
        SystemExit: If the file does not open with a ``# `` title, so a
            malformed corpus file fails the build rather than shipping blank.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise SystemExit(f"corpus file has no '# ' title: {path.name}")
    title = lines[0][2:].strip()

    pmid = doi = year = journal = ""
    for line in lines[1:6]:
        match = _META.match(line.strip())
        if match:
            pmid = match.group("pmid") or ""
            doi = match.group("doi") or ""
            where = match.group("where") or ""
            parts = [p.strip() for p in where.split(",")]
            if parts and parts[-1].isdigit():
                year = parts[-1]
                journal = ", ".join(parts[:-1])
            else:
                journal = where.strip()
            break

    abstract = ""
    if "## Abstract" in lines:
        start = lines.index("## Abstract") + 1
        body: list[str] = []
        for line in lines[start:]:
            if line.startswith("## "):
                break
            body.append(line)
        abstract = "\n".join(body).strip()

    return {
        "title": title,
        "abstract": abstract,
        "pmid": pmid,
        "doi": doi,
        "year": year,
        "journal": journal,
    }


def build() -> list[dict]:
    """Assemble every catalog entry from the core table and the corpus files."""
    entries: list[dict] = []
    files = {path.stem for path in CORPUS.glob("*.md")}

    missing = set(CORE) - files
    if missing:
        raise SystemExit(f"core entries with no corpus file: {sorted(missing)}")

    for stem in sorted(files):
        if stem in CORE:
            title, pmid, doi, source, attribution, abstract = CORE[stem]
            entry = {
                "paper_id": stem,
                "title": title,
                "abstract": abstract,
                "source": source,
                "core": True,
                "attribution": attribution,
            }
            if pmid:
                entry["pmid"] = pmid
            if doi:
                entry["doi"] = doi
            entries.append(entry)
            continue

        meta = parse_harvested(CORPUS / f"{stem}.md")
        entry = {
            "paper_id": stem,
            "title": meta["title"],
            "abstract": meta["abstract"],
            "source": "pubmed",
            "core": False,
            "attribution": "group",
            "year": meta["year"],
            "journal": meta["journal"],
        }
        if meta["pmid"]:
            entry["pmid"] = meta["pmid"]
        if meta["doi"]:
            entry["doi"] = meta["doi"]
        entries.append(entry)

    # Core first, then by year then title, for a stable, review-friendly file.
    entries.sort(
        key=lambda e: (not e["core"], e.get("year", ""), e["title"])
    )
    return entries


def main() -> int:
    entries = build()
    out = CORPUS / "catalog.json"
    out.write_text(
        json.dumps({"papers": entries}, indent=2) + "\n", encoding="utf-8"
    )
    core = [e for e in entries if e["core"]]
    words = sum(len(e["abstract"].split()) for e in core)
    print(f"wrote {out} with {len(entries)} papers ({len(core)} core)")
    print(f"injected core abstracts: {words} words (~{int(words * 1.4)} tokens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
