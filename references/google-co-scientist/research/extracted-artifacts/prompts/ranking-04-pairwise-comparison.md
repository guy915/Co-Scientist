<!--
SOURCE (canonical, verbatim): references/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.3 "Prompts for the Ranking agent" -> Figure A.4 (lines ~789-811).
PARALLEL SOURCE: references/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.3 "Prompts for the Ranking agent".
AGENT: Ranking agent. PURPOSE: single-turn pairwise hypothesis comparison in the Elo tournament (used for lower-ranked pairs).
VERBATIM extract. {curly_brace} placeholders are the paper's.
NOTE [sic]: the prompt body says 'concluding with the phrase "better idea: <1 or 2>"' but the final line instructs ending with
'"better hypothesis: <1 or 2>"'. Both phrasings appear in the source; reproduced as-is.
-->

# Ranking agent — pairwise hypothesis comparison (tournament)

```
Prompt for hypothesis comparison during tournament
You are an expert evaluator tasked with comparing two hypotheses.
Evaluate the two provided hypotheses (hypothesis 1 and hypothesis 2) and determine which one
is superior based on the specified {idea_attributes}.
Provide a concise rationale for your selection, concluding with the phrase "better idea: <1 or 2>".
Goal: {goal}
Evaluation criteria:
{preferences}
Considerations:
{notes}
Each hypothesis includes an independent review. These reviews may contain numerical scores.
Disregard these scores in your comparative analysis, as they may not be directly comparable across reviews.
Hypothesis 1:
{hypothesis 1}
Hypothesis 2:
{hypothesis 2}
Review of hypothesis 1:
{review 1}
Review of hypothesis 2:
{review 2}
Reasoning and conclusion (end with "better hypothesis: <1 or 2>"):
```
