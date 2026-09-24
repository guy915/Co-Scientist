# External reference campaign

[PLAN.md](../../PLAN.md) owns execution state. [Campaign procedures](campaign.md)
record the evaluation and release contract. [M1 dossier](baseline/README.md)
records the starting system and baseline work.

Sources are acquired sequentially in ignored `references/work/<slug>/`.
The Kaimen, conradry, LLNL, raktim-mondol, K-Dense, and Sakana sources are
closed. Sakana's result-conditioned search follow-up remains open in M11;
OpenScience is under assessment, and later sources remain unacquired.
Each source gets a dossier and immutable commit permalinks when its milestone begins.

| Order | Repository | Pinned revision | Assessment |
|---|---|---|---|
| 1 | [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist) | [`cef5bcfec8820865855593b437a941005a9f961a`](https://github.com/Kaimen-Inc/Co-Scientist/commit/cef5bcfec8820865855593b437a941005a9f961a) | [Closed; no adoption from pinned source](kaimen-inc-co-scientist.md) |
| 2 | [conradry/open-coscientist-agents](https://github.com/conradry/open-coscientist-agents) | [`a20b018300da57a26578f8e7442b890193950afa`](https://github.com/conradry/open-coscientist-agents/commit/a20b018300da57a26578f8e7442b890193950afa) | [Closed; two UI adoptions](conradry-open-coscientist-agents.md) |
| 3 | [llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist) | [`c8342c0e28474d134f80caa6b9668470ebf55258`](https://github.com/llnl/open-ai-co-scientist/commit/c8342c0e28474d134f80caa6b9668470ebf55258) | [Closed; failure guidance and BYOK redaction adopted](llnl-open-ai-co-scientist.md) |
| 4 | [raktim-mondol/co-scientist](https://github.com/raktim-mondol/co-scientist) | [`10aa84a3c5a774c6fe5de050000c3f5e0996eb45`](https://github.com/raktim-mondol/co-scientist/commit/10aa84a3c5a774c6fe5de050000c3f5e0996eb45) | [Closed; owned empirical outcomes adopted](raktim-mondol-co-scientist.md) |
| 5 | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | [`49c6e97775eaa18ba791bebe23162a70ae601c18`](https://github.com/K-Dense-AI/scientific-agent-skills/commit/49c6e97775eaa18ba791bebe23162a70ae601c18) | [Closed; bounded citation-edge lookup adopted](k-dense-scientific-agent-skills.md) |
| 6 | [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist) | [`1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb`](https://github.com/SakanaAI/AI-Scientist/commit/1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb) | [Closed; no product adoption, M11 follow-up open](sakana-ai-scientist.md) |
| 7 | [synthetic-sciences/openscience](https://github.com/synthetic-sciences/openscience) | [`4e060d6c3670e3704f34b5cb6fe49ef8fafb29f5`](https://github.com/synthetic-sciences/openscience/commit/4e060d6c3670e3704f34b5cb6fe49ef8fafb29f5) | [Under assessment](synthetic-sciences-openscience.md) |
| 8 | [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | Not acquired | Pending |
| 9 | [Future-House/robin](https://github.com/Future-House/robin) | Not acquired | Pending |

Candidate IDs use `M<number>-<number>` and remain stable after checklist expansion.
Each records the gap, upstream evidence, local counterpart, fidelity classification,
reuse route, acceptance criteria, test boundary, costs/results, and disposition.
Only adopted, already covered, evidence-backed rejection, and out-of-scope decisions
close a candidate; promising inconclusive findings stay open.
