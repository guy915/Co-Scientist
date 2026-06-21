<!--
SOURCE (canonical, verbatim): references/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.5.3 "Examples of co-scientist generated Specific Aims with expert evaluation" / Figures A.28-A.29 (lines 1509-1597).
PARALLEL SOURCE: references/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 4.1.2 "Example 2: Selinexor monotherapy for colon cancer" (lines 195-257). NOTE: the Nature SI prose differs slightly
  (e.g. it titles the example "Selinexor monotherapy…" and elsewhere reports 9 raters / avg 6.7 yrs experience vs. the arXiv's
  6 raters / 8 yrs); the per-axis Expert-rating list below is reproduced verbatim from the arXiv report, the canonical source here.
CASE STUDY: Drug repurposing — Specific Aims (colon adenocarcinoma / COAD). ARTIFACT: a Co-Scientist hypothesis reformatted by the
  Meta-review agent into the NIH "Specific Aims Page" format, one of the THREE worked examples the paper presents at A.26-A.31, and one
  of the two (Selinexor, Lapatinib) that carry a full 15-axis "Expert rating" block against the A.5.2 rubric. (Givosiran, A.26-A.27, has
  no rating block and is extracted separately under outputs/drug-repurposing-aml/03-givosiran-specific-aims-nih-format.md.)
VERBATIM extract. The 15 numbered Expert-rating items below map to the A.5.2 rubric (5 "Significance and innovation" + 10 "Rigor and feasibility").
-->

# Drug-repurposing Specific Aims — Selinexor for colon cancer (NIH format, with expert rating)

## Selinexor for colon cancer

#### Disease Description

Colon adenocarcinoma (COAD) is a significant public health concern, with an estimated incidence rate of over 1.9 million new cases and 935,000 deaths globally in 2020. COAD arises from the epithelial lining of the colon and is driven by a complex interplay of genetic mutations (e.g., APC, KRAS, BRAF, TP53) and epigenetic alterations, leading to uncontrolled cell proliferation, impaired apoptosis, and chronic inflammation. These molecular changes disrupt crucial cellular pathways like Wnt/β-catenin signaling, cell cycle control, and DNA damage repair, ultimately driving tumor progression. COAD typically progresses through stages, from localized polyps to invasive tumors with potential for metastasis. Current standard of care involves surgery, chemotherapy, radiation therapy, and targeted therapies, but treatment resistance and recurrence remain major challenges, highlighting the need for new therapeutic approaches.

#### Unmet Need

Current COAD treatments have limitations, including acquired resistance to chemotherapy, significant toxicities, and incomplete responses in advanced disease. Patients often experience diminished quality of life due to treatment side effects and disease burden. High recurrence rates and limited effective treatment options after progression contribute to poor long-term outcomes. This unmet need underscores the urgency for novel therapeutic strategies that can overcome resistance, improve response rates, and minimize toxicity, ultimately extending survival and enhancing quality of life for COAD patients.

#### Proposed Solution

Selinexor, a first-in-class selective inhibitor of nuclear export (SINE), is currently approved for the treatment of multiple myeloma and diffuse large B-cell lymphoma. It specifically targets XPO1 (Exportin 1), a key protein responsible for the nuclear export of tumor suppressor proteins, oncoproteins, and RNA. By binding to XPO1, Selinexor blocks the nuclear export of these molecules, leading to their accumulation in the nucleus and restoration of tumor suppressor function, cell cycle arrest, and apoptosis induction.

Repurposing Selinexor for COAD is rationally supported by its mechanism of action and the molecular characteristics of the disease. Overexpression of XPO1 is common in various cancers, including COAD [1, 2, 6]. Selinexor inhibits XPO1, preventing the nuclear export and restoring the function of key tumor suppressors (p53, RB, FOXO, APC) frequently dysregulated in COAD [2, 3, 4, 5]. Furthermore, Selinexor can suppress constitutively activated NF-κB signaling, a driver of chronic inflammation and tumor progression in COAD, by blocking IκB export and increasing its nuclear accumulation [7, 8]. These mechanisms align with key aspects of COAD pathogenesis and offer opportunities for therapeutic intervention.

We hypothesize that Selinexor will effectively inhibit COAD cell growth and enhance apoptosis by restoring tumor suppressor function and modulating crucial signaling pathways. Selinexor has shown anti-tumor activity in solid tumors in a Phase I trial [3], with observations of nuclear accumulation of tumor suppressor proteins [3, 6]. While not specific to COAD, these findings, coupled with evidence of Selinexor's efficacy in other cancers driven by XPO1 overexpression [3, 6], suggest that a similar mechanism could be effective in COAD. Further supporting our hypothesis, XPO1 overexpression has been linked to NF-κB activation and increased proliferation in COAD [7]. Overall, our goal is: to demonstrate that Selinexor's XPO1 inhibitory activity can effectively target key oncogenic drivers and restore tumor suppressor functions in COAD, ultimately leading to tumor growth inhibition and improved patient outcomes.

### Specific Aims 1

#### Overarching goal:

Determine the in vitro efficacy of Selinexor in inhibiting COAD cell growth and inducing apoptosis.

#### Hypothesis:

Selinexor treatment will significantly reduce the viability and increase apoptosis in a panel of COAD cell lines, including those with varying genetic backgrounds (e.g., APC, KRAS, TP53 mutations).

#### Reasoning:

Selinexor's inhibition of XPO1 leads to nuclear accumulation of tumor suppressors like p53, a key regulator of apoptosis [2, 6]. Restoration of p53 function and suppression of NF-κB, a pro-survival pathway [7, 8], are expected to induce apoptosis in COAD cells. We will evaluate this hypothesis using cell viability and apoptosis assays in diverse COAD cell lines to assess the impact of genetic background on Selinexor's efficacy.

### Specific Aims 2

#### Overarching goal:

Elucidate the mechanisms by which Selinexor inhibits COAD cell growth, focusing on XPO1-mediated restoration of tumor suppressor function.

#### Hypothesis:

Selinexor treatment will increase nuclear accumulation of p53, RB, and FOXO proteins and decrease nuclear export of IκB, leading to cell cycle arrest and decreased NF-κB activity in COAD cells.

#### Reasoning:

Selinexor blocks XPO1, preventing nuclear export of key tumor suppressors (p53, RB, FOXO) [2, 4, 5] and the NF-κB inhibitor IκB [7, 8]. Increased nuclear localization of these proteins should restore their growth regulatory functions, leading to cell cycle arrest and reduced NF-κB-driven proliferation. We will evaluate this hypothesis using immunofluorescence and western blotting to assess protein localization and activity.

### Specific Aims 3

#### Overarching goal:

Characterize the potential synergistic effects of Selinexor in combination with standard-of-care chemotherapies for COAD.

#### Hypothesis:

Combination treatment with Selinexor and 5-fluorouracil (5-FU) will synergistically reduce COAD cell viability compared to either treatment alone.

#### Reasoning:

XPO1 inhibition can sensitize cancer cells to chemotherapy [9]. Combining Selinexor with 5-FU, a common COAD chemotherapy, may enhance cellular stress and improve treatment response. We will test this hypothesis using cell viability assays and investigate the underlying mechanisms of synergy.

#### Pilot Evaluation

A pilot study will evaluate Selinexor's efficacy in a patient-derived xenograft (PDX) model of COAD. The primary objective is to determine the effect of Selinexor on tumor growth. The study will utilize an open-label, single-arm design with escalating Selinexor doses in established COAD PDX models. Inclusion criteria: established COAD PDX models. Exclusion criteria: none. Primary endpoint: tumor volume change. Secondary endpoints: changes in biomarkers (p53, Ki67, NF-κB) within the tumor. Selinexor's established safety profile in other cancers provides a basis for evaluating its safety in this new indication. Potential for expedited review through existing regulatory pathways will be explored.

#### Expert rating

- 1. Strongly Agree (unmet clinical needs)
- 2. Agree (bridges therapeutic gap)
- 3. Strongly Agree (scientifically rigorous rationale)
- 4. Agree (integrates prior studies)
- 5. Agree (avoids over-extrapolation)
- 6. Strongly Agree (clear hypotheses and methods)
- 7. Strongly Agree (clearly stated aims)
- 8. Agree (path to clinical application)
- 9. Agree (well-defined endpoints)
- 10. Agree (meaningful pre-clinical experiments)
- 11. Agree (translational component)
- 12. Strongly Agree (avoids inaccuracies)
- 13. Strongly Agree (evidence-based assumptions)
- 14. Agree (originality and terminology)
- 15. Strongly Agree (clear writing and organization)
