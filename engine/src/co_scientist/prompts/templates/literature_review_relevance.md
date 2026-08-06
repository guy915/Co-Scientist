# Judge Paper Relevance to Research Goal

You are judging how well one candidate paper bears on a research goal, before it is read in full.

## Research Goal
{{research_goal}}

## Candidate Paper
**Title:** {{title}}
**Abstract:** {{abstract}}

---

## Your Task

Judge only whether this paper's title and abstract bear on the research goal above -- not its citation count, recency, or venue. A paper can be highly relevant and obscure, or well-cited and irrelevant.

Score `relevance` from 0.0 (unrelated to the goal) to 1.0 (directly on point), and give one sentence of `rationale` stating why.

## Response Format

Return a JSON object with this structure:

```json
{{
    "relevance": 0.0,
    "rationale": "..."
}}
```
