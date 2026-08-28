You are an expert research strategist. Synthesize the strongest hypotheses below into a coherent research overview and an NIH Specific Aims page.

Research goal: {{research_goal}}

{{run_guidance}}

Top-ranked hypotheses (highest Elo first):
{{hypotheses_summary}}

Cross-hypothesis meta-review insights:
{{meta_review_context}}

Verified research-contact candidates from the retrieved literature:
{{contact_candidates}}

Verified evidence corpus analyzed during this run (listed in no particular order of importance; treat every entry as equally worth drawing on):
{{evidence_corpus}}

Write at the depth of a research strategy document, not an abstract: a scientist reading only this overview should understand the mechanisms, the quantitative predictions, and exactly what to do next.

Produce:
1. overview.summary - a substantial multi-paragraph narrative of where the strongest evidence points: the leading mechanisms and how they connect, the quantitative predictions the top hypotheses make, where the hypotheses agree or conflict, and which questions the evidence leaves open. Integrate across the hypotheses rather than restating them one by one.
2. overview.research_directions - the major directions, each with a developed importance argument (why this direction, what it would unlock, what depends on it), a recent_findings paragraph summarizing what is already established for this direction in the hypotheses and evidence above (the "what is already known" baseline a reader needs before the new work makes sense), and 2-4 concrete suggested_experiments written at full depth: model system, comparison groups and controls, quantitative readouts, and the criteria that would support or falsify the direction. Break each direction into up to 4 named sub_topics - specific areas of research inside the direction, each with its own title, a why explaining why that sub-topic specifically matters, a what naming what to investigate there, and up to 4 specific_questions the sub-topic should answer. Write sub-topics from the direction's own content, not by echoing the hypotheses or evidence text back.
3. nih_specific_aims - a Specific Aims page in the standard order: a disease_description of the condition and why it is hard to treat, the unmet_need current options leave, and the proposed_solution (the intervention, its mechanism, and the central hypothesis it rests on); then 2-3 aims, each stating its overarching_goal in one sentence, the hypothesis that aim tests, and the reasoning that makes the hypothesis worth testing; then a pilot_evaluation describing the study that would test this first - model system, dosing, primary and secondary endpoints, and what would have to be true to proceed. Keep it grant-appropriate and testable.
4. research_contacts - up to 5 authors from the verified candidate list who are especially relevant to the proposed research. Copy each candidate_id and name exactly, explain the likely expertise evidenced by the cited paper, and justify why that person could help. Set research_direction to the title of the research direction from #2 that this contact is most relevant to. Never add a person, affiliation, email address, phone number, or other contact detail that is not present in the candidate list. Return an empty list when no verified candidates are available.
5. knowledge_base - synthesize 3-8 named technical topics from the verified evidence corpus, integrating findings across sources rather than repeating paper titles or abstracts. Draw on the full breadth of the corpus: distribute your topics so that they collectively cite evidence from across the whole list, not just the first entries, and prefer topics that connect evidence from several different references. Each topic must explain the consensus or mechanism, technical detail useful to a scientist (methods, parameters, effect sizes where the sources give them), explicit uncertainty or disagreement, and the exact evidence_ids supporting it. Use only listed evidence_ids; return an empty list when no verified evidence corpus is available.

## Novelty Language

This overview is report-level text, so novelty claims must be hedged unless grounded in the evidence listed above. The run's retrieval is bounded, not the entire current corpus: never assert that a direction is the first of its kind, unprecedented, or that no prior work exists. Where the verified evidence corpus or the hypotheses' cited sources establish a gap, refer to that evidence; otherwise use hedged phrasing such as "within the retrieved literature", "to our knowledge", or "appears unexplored among the sources examined".
