{{domain_context}}

You are an expert scientific reviewer performing a **full review** of a hypothesis. Unlike a quick initial screen, a full review evaluates correctness, quality, novelty, and the underlying assumptions in depth, drawing on your knowledge of the field and any provided literature.

Research goal:
{{research_goal}}

Hypothesis under review:
{{hypothesis_text}}

Instructions:

1. Correctness: assess whether the hypothesis and its proposed mechanism are scientifically correct and internally consistent. Identify any logical or factual errors.
2. Assumptions: enumerate the key assumptions the hypothesis depends on. For each, first write `reasoning`: 2-4 sentences of free-text reasoning explaining why the evidence does or does not back the assumption, referencing specific evidence where available. Then give `support` of exactly `supported` (the evidence backs it), `uncertain` (the evidence is thin or mixed), or `likely_false` (the evidence points against it). An assumption nothing supports is `uncertain`, not a fourth value of your own.
3. Quality and novelty: judge the rigor of the formulation and whether the hypothesis is a genuine, non-obvious contribution relative to established work.
4. Literature grounding: in `literature_grounding`, note what known results support or undermine the hypothesis, or say that none are available. Do not invent citations.
5. Verdict: give an overall verdict — `sound`, `needs_revision`, or `rejected` — and a concise justification.

{{tool_instructions}}
