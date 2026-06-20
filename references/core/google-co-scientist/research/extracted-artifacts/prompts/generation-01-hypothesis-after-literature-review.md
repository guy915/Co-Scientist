<!--
SOURCE (canonical, verbatim): references/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.2.1 "Prompts for the Generation agent" -> Figure A.1 (lines ~715-737).
PARALLEL SOURCE (same prompt, Nature-published version): references/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Section 9.1 "Prompts for the Generation agent" (lines ~1105-1127).
AGENT: Generation agent. PURPOSE: hypothesis generation after literature review and relevant article exploration.
This file is a VERBATIM extract of the prompt template. Placeholders in {curly_braces} are the paper's, not added by us.
-->

# Generation agent — hypothesis generation after literature review

```
Prompt for hypothesis generation after literature review
You are an expert tasked with formulating a novel and robust hypothesis to address
the following objective.
Describe the proposed hypothesis in detail, including specific entities, mechanisms,
and anticipated outcomes.
This description is intended for an audience of domain experts.
You have conducted a thorough review of relevant literature and developed a logical framework
for addressing the objective. The articles consulted, along with your analytical reasoning,
are provided below.
Goal: {goal}
Criteria for a strong hypothesis:
{preferences}
Existing hypothesis (if applicable):
{source_hypothesis}
{instructions}
Literature review and analytical rationale (chronologically ordered, beginning
with the most recent analysis):
{articles_with_reasoning}
Proposed hypothesis (detailed description for domain experts):
```
