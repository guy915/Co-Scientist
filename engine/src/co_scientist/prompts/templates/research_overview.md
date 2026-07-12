You are an expert research strategist. Synthesize the strongest hypotheses below into a coherent research overview and an NIH Specific Aims page.

Research goal: {{research_goal}}

{{run_guidance}}

Top-ranked hypotheses (highest Elo first):
{{hypotheses_summary}}

Cross-hypothesis meta-review insights:
{{meta_review_context}}

Verified research-contact candidates from the retrieved literature:
{{contact_candidates}}

Produce:
1. overview.summary - a concise narrative of where the strongest evidence points.
2. overview.research_directions - the major directions, each with its importance and 2-4 concrete suggested_experiments.
3. nih_specific_aims - an introduction (significance + gap), 2-3 aims (each with aim, rationale, approach), and an impact statement. Keep it grant-appropriate and testable.
4. research_contacts - up to 5 authors from the verified candidate list who are especially relevant to the proposed research. Copy each candidate_id and name exactly, explain the likely expertise evidenced by the cited paper, and justify why that person could help. Never add a person, affiliation, email address, phone number, or other contact detail that is not present in the candidate list. Return an empty list when no verified candidates are available.
