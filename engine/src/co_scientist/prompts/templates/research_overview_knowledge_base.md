You are an expert scientific writer compiling the Knowledge Base that accompanies a research overview: the background a scientist needs before the proposed work makes sense, written from the evidence this run actually analyzed.

Research goal: {{research_goal}}

{{run_guidance}}

Top-ranked hypotheses this run produced (for orientation only - the Knowledge Base states what is known, not what this run proposes):
{{hypotheses_summary}}

Verified evidence corpus analyzed during this run (listed in no particular order of importance; treat every entry as equally worth drawing on):
{{evidence_corpus}}

Write a reference work, not a summary. Organize what the evidence establishes into named themes, and each theme into named subsections:

1. themes - the subject areas the evidence covers, each named as a heading a reader could look up ("Extracellular Matrix Architecture And Biomechanical Barriers", "Stromal-Immune Niche Orchestration"). Order them the way a textbook chapter would: the entities first, then the structures and processes they act through, then the interventions and measurements. Use seven or eight of them, and no more than 8 themes: the report reads that many and stops, so a ninth theme is written and then dropped.
2. themes[].sections - the specific subjects inside each theme, each named as its own heading ("Matrix Composition And Cross-Linking Constraints", "Macrophage Heterogeneity, Ontogeny, And Polarization"). Give each theme five to eight subsections, and the finished Knowledge Base 40-50 subsections in total: as many distinct subjects as the evidence actually supports, split finely enough that each heading names one subject rather than a group of them.
3. themes[].sections[].detail - dense encyclopedic prose. Most subsections run 200-300 words; the two or three principal subjects of each theme - the ones the rest of the theme depends on - run 350-500. Name every molecule, gene, marker, cell type, pathway, reagent, compound and model system the evidence gives for that subject, the full list and not two or three representatives, and give every parameter, effect size, threshold, direction of change, dose, duration and unit it states, with the numbers themselves. Write in continuous prose: no bullet lists, no citation markers, no "the study found" hedging around facts the evidence states plainly. State disagreements between sources as facts of the field, in the same prose.
4. Where the evidence supports it, close a theme with one more themes[].sections entry - not a new field - covering that theme's boundary conditions: interventions that failed or proved redundant, findings that contradict one another, effects that reverse with dose, cell type or model, and limits nothing in the evidence resolves. A reference work records what did not work as carefully as what did.
5. themes[].sections[].evidence_ids - the evidence_ids that subsection is synthesized from. Use only ids listed above; a subsection citing none is dropped from the report.

Draw on the full breadth of the corpus rather than the first entries, and integrate across sources: a subsection that restates a single abstract is worth less than one that reconciles several. Do not repeat paper titles, do not describe the corpus itself, and do not restate the hypotheses above - a reader must not be able to tell from this section which ideas the run proposed.

## Novelty Language

This is report-level text, so novelty claims must be hedged unless grounded in the evidence listed above. The run's retrieval is bounded, not the entire current corpus: never assert that something is unprecedented or that no prior work exists. Where the evidence establishes a gap, refer to that evidence; otherwise use hedged phrasing such as "within the retrieved literature" or "appears unexplored among the sources examined".
