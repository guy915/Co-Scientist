# External reference campaign

[PLAN.md](../../PLAN.md) owns execution state. [Campaign procedures](campaign.md)
record the evaluation and release contract. [M1 dossier](baseline/README.md)
records the starting system and baseline work.

Sources are acquired sequentially in ignored `references/work/<slug>/`.
The Kaimen source is closed and the conradry source is pinned and under assessment;
later sources remain unacquired.
Each source gets a dossier and immutable commit permalinks when its milestone begins.

| Order | Repository | Pinned revision | Assessment |
|---|---|---|---|
| 1 | [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist) | [`cef5bcfec8820865855593b437a941005a9f961a`](https://github.com/Kaimen-Inc/Co-Scientist/commit/cef5bcfec8820865855593b437a941005a9f961a) | [Closed; no adoption from pinned source](kaimen-inc-co-scientist.md) |
| 2 | [conradry/open-coscientist-agents](https://github.com/conradry/open-coscientist-agents) | [`a20b018300da57a26578f8e7442b890193950afa`](https://github.com/conradry/open-coscientist-agents/commit/a20b018300da57a26578f8e7442b890193950afa) | [Assessment in progress](conradry-open-coscientist-agents.md) |
| 3 | [llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist) | Not acquired | Pending |
| 4 | [raktim-mondol/co-scientist](https://github.com/raktim-mondol/co-scientist) | Not acquired | Pending |
| 5 | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | Not acquired | Pending |
| 6 | [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist) | Not acquired | Pending |
| 7 | [synthetic-sciences/openscience](https://github.com/synthetic-sciences/openscience) | Not acquired | Pending |
| 8 | [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | Not acquired | Pending |
| 9 | [Future-House/robin](https://github.com/Future-House/robin) | Not acquired | Pending |

Candidate IDs use `M<number>-<number>` and remain stable after checklist expansion.
Each records the gap, upstream evidence, local counterpart, fidelity classification,
reuse route, acceptance criteria, test boundary, costs/results, and disposition.
Only adopted, already covered, evidence-backed rejection, and out-of-scope decisions
close a candidate; promising inconclusive findings stay open.
