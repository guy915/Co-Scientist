# External reference campaign

Current state — 1 October 2026: all nine source assessments are closed; the campaign remains incomplete. [PR #88](https://github.com/guy915/Co-Scientist/pull/88) is the current verified release (`a7767153`), with [existing-service release evidence](m12-pubmed-batching-release-2026-10-01.json). Metadata batching and bounded recovery remain disabled by default in production. The [seventh novelty comparison](sakana/novelty-pilot-v7-terminal-2026-10-01.json) stopped on PMC fulltext HTTP400 after16 valid model responses and24 retrieval events; three of six pairs completed. All seven consumed comparisons are incomplete and unscored. The four original scientific/final gates remain open, with a bounded default-preserving fulltext opt-out correction and its release observation now recorded as preparatory items i1/i2 in PLAN. No further model qualification, replay or new comparison registration is authorized by this update.

[PLAN.md](../../PLAN.md) owns execution state. [Campaign procedures](campaign.md)
record the evaluation and release contract. [M1 dossier](baseline/README.md)
records the starting system and baseline work.

Sources are acquired sequentially in ignored `references/work/<slug>/`.
All nine required source investigations are closed. The OpenScience timeout and
ToolUniverse GWAS follow-ups were [released in M11](m11-release-verification.json).
The [corrected Space Bunny screen](m12-space-bunny-corrected-result-2026-09-30.md)
passed its frozen gates; the [released public flow](m12-free-default-public-acceptance-2026-09-30.json)
completed 71/71 durable tasks with 178 observed responses and $0 reported cost.
The [distinct Robin continuation](m12-robin-continuation-acceptance-2026-09-30.json)
completed 17 further tasks with lineage, ownership, model/cost telemetry and
browser refresh. Its weakened and blocked scientific dispositions are retained;
these workflow results do not establish expert or experimental validation.
Sakana's result-conditioned search remains unresolved. The separately registered
[third study](sakana/novelty-result-conditioned-pilot-prereg-v3.json)
[stopped on a PubMed metadata-fetch error](sakana/novelty-pilot-v3-interruption-2026-09-30.json)
after one model response and one retrieval call at reported $0. All three study
admissions are consumed and incomplete; none may be replayed. No scientific
adoption or rejection follows from an interrupted comparison.
[PR #80](m12-reference-evidence-release-2026-09-30.json) preserves the reference
repair and study evidence; its unchanged product is healthy in existing services.
Four original M12 gates remain open in [PLAN.md](../../PLAN.md). The prospective
fourth-study preparation passed actual isolated process/CLI gates, then its
[sole admission stopped incomplete](sakana/novelty-pilot-v4-terminal-2026-09-30.json)
after 13 model responses and 19 outer searches at reported $0. Two EFetch 429 recoveries
succeeded; a later ELink 429 exhausted the registered budget. All four admissions
are now consumed and unscored; no replay or scientific disposition follows. The
[deferred register](deferred-followups-2026-09-25.md) preserves earlier decisions,
and [current release reconciliation](m12-current-release-reconciliation-2026-09-30.json)
identifies the verified production and rollback points.
Sakana's separate precise-rung retention candidate was rejected after a
completed, blinded, independently sourced confirmation; see the
[dossier](sakana-ai-scientist.md#m11-precise-rung-disposition-26-september-2026).
Each source gets a dossier and immutable commit permalinks when its milestone begins.
[M11's follow-up register](m11-follow-up-register.md) records the remaining
mechanism gaps and the additional-repository selection decision.
[M11 evidence release](m11-evidence-release-2026-09-26.json) records the
owner-directed route skip, PR #48, deployed commit and keyless smoke result.
That historical receipt predates the five-gate deferral. [PR #60's route release](m12-space-bunny-release-2026-09-27.json)
and the [negative acceptance finding](m12-acceptance-gaps-2026-09-27.md)
record historical local-flow evidence and its then-remaining limits. The
[authenticated production receipt](m12-production-public-run-2026-09-27.json)
now records a completed campaign-owned goal and two terminal Robin
`no_child` actions. [PR #65's Robin release](m12-robin-release-2026-09-27.md)
created a live child, but the [post-release receipt](m12-robin-postrelease-2026-09-27.json)
records a metrics-checkpoint regression. Corrective [PR #66](m12-robin-release-2026-09-27.md)
reached production, and a [new live refinement](m12-robin-corrective-observation-2026-09-27.json)
retained its served-model/cost entry after successor review. The fixed-input
comparison was superseded by the corrected screen linked above; novelty
disposition and final zero-open acceptance remain open.

| Order | Repository | Pinned revision | Assessment |
|---|---|---|---|
| 1 | [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist) | [`cef5bcfec8820865855593b437a941005a9f961a`](https://github.com/Kaimen-Inc/Co-Scientist/commit/cef5bcfec8820865855593b437a941005a9f961a) | [Closed; no adoption from pinned source](kaimen-inc-co-scientist.md) |
| 2 | [conradry/open-coscientist-agents](https://github.com/conradry/open-coscientist-agents) | [`a20b018300da57a26578f8e7442b890193950afa`](https://github.com/conradry/open-coscientist-agents/commit/a20b018300da57a26578f8e7442b890193950afa) | [Closed; two UI adoptions](conradry-open-coscientist-agents.md) |
| 3 | [llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist) | [`c8342c0e28474d134f80caa6b9668470ebf55258`](https://github.com/llnl/open-ai-co-scientist/commit/c8342c0e28474d134f80caa6b9668470ebf55258) | [Closed; failure guidance and BYOK redaction adopted](llnl-open-ai-co-scientist.md) |
| 4 | [raktim-mondol/co-scientist](https://github.com/raktim-mondol/co-scientist) | [`10aa84a3c5a774c6fe5de050000c3f5e0996eb45`](https://github.com/raktim-mondol/co-scientist/commit/10aa84a3c5a774c6fe5de050000c3f5e0996eb45) | [Closed; owned empirical outcomes adopted](raktim-mondol-co-scientist.md) |
| 5 | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | [`49c6e97775eaa18ba791bebe23162a70ae601c18`](https://github.com/K-Dense-AI/scientific-agent-skills/commit/49c6e97775eaa18ba791bebe23162a70ae601c18) | [Closed; bounded citation-edge lookup adopted](k-dense-scientific-agent-skills.md) |
| 6 | [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist) | [`1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb`](https://github.com/SakanaAI/AI-Scientist/commit/1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb) | [Closed source assessment; result-conditioned follow-up unresolved in M12](sakana-ai-scientist.md) |
| 7 | [synthetic-sciences/openscience](https://github.com/synthetic-sciences/openscience) | [`4e060d6c3670e3704f34b5cb6fe49ef8fafb29f5`](https://github.com/synthetic-sciences/openscience/commit/4e060d6c3670e3704f34b5cb6fe49ef8fafb29f5) | [Closed; owned admission and lifecycle corrections adopted](synthetic-sciences-openscience.md) |
| 8 | [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse) | [`78883724c46a94ec1d1bfdc984efb25ba1b76aed`](https://github.com/mims-harvard/ToolUniverse/commit/78883724c46a94ec1d1bfdc984efb25ba1b76aed) | [Assessed and released; GWAS follow-up adopted and released in M11](mims-harvard-tooluniverse.md) |
| 9 | [Future-House/robin](https://github.com/Future-House/robin) | [`4a5cce310f3bc7663a67117db88af43b84733ffe`](https://github.com/Future-House/robin/commit/4a5cce310f3bc7663a67117db88af43b84733ffe) | [Assessed and released; distinct live continuation verified with scientific limits](future-house-robin.md) |

Candidate IDs normally use `M<number>-<number>`; M6's stable `KDS-*` IDs are the
documented exception. IDs remain stable after checklist expansion.
Each records the gap, upstream evidence, local counterpart, fidelity classification,
reuse route, acceptance criteria, test boundary, costs/results, and disposition.
Only adopted, already covered, evidence-backed rejection, and out-of-scope decisions
close a candidate; promising inconclusive findings stay open.

Latest support release: [PubMed batching and study evidence, 1 October 2026](m12-pubmed-batching-release-2026-10-01.json), PR87/`0b642a97`; all existing services verified healthy. Default-off support and incomplete scientific comparisons are separate outcomes; four original M12 acceptance gates remain open.
