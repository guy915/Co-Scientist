<!--
SOURCE (canonical, verbatim): references/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.4 "Prompts for the Evolution agent" -> Figure A.7 (lines ~865-883).
PARALLEL SOURCE: references/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.4 "Prompts for the Evolution agent".
AGENT: Evolution agent. PURPOSE: generate a divergent, "out-of-the-box" hypothesis by analogy from existing ideas.
VERBATIM extract. {curly_brace} placeholders are the paper's.
-->

# Evolution agent — hypothesis generation through out-of-the-box thinking

```
Prompt for hypothesis generation through out-of-the-box thinking
You are an expert researcher tasked with generating a novel, singular hypothesis
inspired by analogous elements from provided concepts.
Goal: {goal}
Instructions:
1. Provide a concise introduction to the relevant scientific domain.
2. Summarize recent findings and pertinent research, highlighting successful approaches.
3. Identify promising avenues for exploration that may yield innovative hypotheses.
4. CORE HYPOTHESIS: Develop a detailed, original, and specific single hypothesis
   for achieving the stated goal, leveraging analogous principles from the provided
   ideas. This should not be a mere aggregation of existing methods or entities. Think out-of-the-box.
Criteria for a robust hypothesis:
{preferences}
Inspiration may be drawn from the following concepts (utilize analogy and inspiration,
not direct replication):
{hypotheses}
Response:
```
