{{domain_context}}

You are an expert scientist generating hypotheses from an ITERATIVE ASSUMPTION TREE. Earlier levels decomposed the research area into its taken-for-granted assumptions and, for the load-bearing ones, into sub-assumptions; you now generate hypotheses by challenging the weakest nodes of that tree.

Research goal:
{{research_goal}}

{{meta_review_context}}
{{literature_context}}
{{citation_reference_section}}
{{assumption_tree_section}}
{{research_expansion_section}}
{{falsified_assumptions_section}}
Instructions:

1. Interrogation: for the most promising assumptions and sub-assumptions above, ask what would follow if they were false, incomplete, or only conditionally true. (If no assumption tree is provided above, first identify the area's key assumptions yourself — mechanistic, methodological, or conceptual — and interrogate those.)
2. Hypotheses: from the most promising interrogations, generate distinct, testable hypotheses. Each must name the assumption or sub-assumption it challenges or extends, propose a concrete mechanism, and state the expected effect.

For each hypothesis's `literature_grounding`: if a Citation Reference List is provided above, cite the relevant evidence using ONLY those `[C*]` keys (e.g. `[C1]`, `[C2]`) and do NOT invent author-year citations; if no list is provided, state that the hypothesis is formulated without access to a literature review.

Generate {{num_hypotheses}} hypotheses. Favor hypotheses that overturn or refine a load-bearing assumption over incremental variations.
