# Completed external reference campaign

The campaign closed on **1 October 2026**, with all nine source assessments and
accepted releases complete and zero open campaign items. This is a historical
record. Use [docs/LAUNCH.md](docs/LAUNCH.md) for current release work and executable
configuration for current models and operational settings.

The former `references/` tree contained completed experiments, dated receipts
and one-shot research runners rather than product inputs. It was removed from
the working tree during the 3 October convergence pass. Its complete evidence
and original relative links remain available at immutable revision `7c2878aeb071a962cb713e9c271cd88e1635ca5f`:

- [Full execution record](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/PLAN.md), including candidate IDs, decisions,
  preregistrations, costs, verification commands and release history.
- [Source inventory](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/README.md),
  [final report](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/campaign-final-report.md) and
  [all original evidence](https://github.com/guy915/Co-Scientist/tree/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external).
- [Campaign procedures](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/campaign.md), including the
  [public-evidence acceptance workflow](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/campaign.md#public-evidence-acceptance-workflow).
- [Final acceptance receipt](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/m12-final-acceptance-2026-10-01.json).

These links preserve the original source and evidence records without keeping
obsolete research machinery in the maintained application. The published Google
prompts, pseudocode and worked outputs used by fidelity tests remain in
[docs/CORPUS-EXTRACTION.md](docs/CORPUS-EXTRACTION.md); the shipped Science Skills
bundle remains pinned and attributed in [NOTICE](NOTICE).

## Source decisions

Each assessment pins the upstream revision, inspected components and licenses,
local counterpart, candidate IDs, acceptance criteria and final dispositions.
External techniques and local design choices are distinguished from independently
supported Google requirements. Accepted changes retain the existing FastAPI,
React, LangGraph and SQLite runtime and its ownership, provenance, recovery and
safety boundaries.

| Pinned source | Retained conclusion | Evidence |
|---|---|---|
| [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist/commit/cef5bcfec8820865855593b437a941005a9f961a) | Existing coverage, rejected techniques and scope exclusions; no adoption. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/kaimen-inc-co-scientist.md) |
| [conradry/open-coscientist-agents](https://github.com/conradry/open-coscientist-agents/commit/a20b018300da57a26578f8e7442b890193950afa) | Supervisor decision visibility and per-idea match history. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/conradry-open-coscientist-agents.md) |
| [llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist/commit/c8342c0e28474d134f80caa6b9668470ebf55258) | Typed failure guidance and BYOK error redaction. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/llnl-open-ai-co-scientist.md) |
| [raktim-mondol/co-scientist](https://github.com/raktim-mondol/co-scientist/commit/10aa84a3c5a774c6fe5de050000c3f5e0996eb45) | Append-only, owner-scoped empirical outcomes; destructive similarity gate rejected. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/raktim-mondol-co-scientist.md) |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills/commit/49c6e97775eaa18ba791bebe23162a70ae601c18) | Bounded citation-edge lookup; broad bundle and new research modes excluded. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/k-dense-scientific-agent-skills.md) |
| [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist/commit/1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb) | Exact precise-rung and result-conditioned search adaptations rejected after completed comparisons. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/sakana-ai-scientist.md) |
| [synthetic-sciences/openscience](https://github.com/synthetic-sciences/openscience/commit/4e060d6c3670e3704f34b5cb6fe49ef8fafb29f5) | Durable admission, cancellation, pause/resume and provider-timeout corrections. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/synthetic-sciences-openscience.md) |
| [mims-harvard/ToolUniverse](https://github.com/mims-harvard/ToolUniverse/commit/78883724c46a94ec1d1bfdc984efb25ba1b76aed) | Cached retrieval provenance, typed lookup failures, retraction refresh and bounded GWAS lookup. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/mims-harvard-tooluniverse.md) |
| [Future-House/robin](https://github.com/Future-House/robin/commit/4a5cce310f3bc7663a67117db88af43b84733ffe) | Explicit outcome-to-parent refinement with durable intent, lineage and ordinary scientific gates. | [Assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/future-house-robin.md) |

## Final observations and limits

The following results describe the **1 October campaign snapshot**, not general
model quality or the current deployment.

- The corrected Space Bunny screen passed its frozen gates across **200 physical
  responses at reported $0**. A separate public flow completed **71/71 durable
  tasks**, with 178 observed responses and 29 recovered API errors. Its 21
  unsupported and four unavailable citation rows prevent a citation-completeness
  claim. See the [screen](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/m12-space-bunny-corrected-result-2026-09-30.md)
  and [public-flow receipt](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/m12-free-default-public-acceptance-2026-09-30.json).
- The distinct Robin continuation completed **17 further tasks**, preserving
  lineage, ownership and model/cost telemetry after browser refresh. Deep
  verification weakened its child, and a claim gate blocked it. This verifies
  workflow traversal while retaining the adverse scientific dispositions; it
  establishes neither expert nor wet-lab validity. See the
  [continuation receipt](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/m12-robin-continuation-acceptance-2026-09-30.json).
- Novelty Study 9 completed **six pairs**, 24 scientific OpenRouter responses,
  36 MCP calls and 72 blinded labels. Positive coverage was **3/6 in both arms**;
  control-anchor coverage fell from **4/6 to 3/6**, with two individual anchor
  losses. The preregistered assessment rejected **this exact result-conditioned
  search adaptation**; conditional confirmation was not triggered. It does not
  reject all iterative search or establish general provider or paper quality.
  The six pairs reuse exposed bank9 inputs. See the
  [scientific assessment](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/sakana/novelty-pilot-v9-scientific-assessment-2026-10-01.json),
  [terminal record](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/sakana/novelty-pilot-v9-terminal-2026-10-01.json),
  [protocol](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/sakana/novelty-result-conditioned-pilot-prereg-v9.json)
  and [bank](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/sakana/novelty-fixture-bank-prereg-v9.json).
- Studies 1–8 remain consumed, immutable, incomplete and unscored. No replay,
  substitution, partial-scoring claim, automatic new study or scientific-quality
  inference follows from their interruption. Their dated records remain in the
  [archived campaign history](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/references/external/campaign.md).

Product PR #89's metadata-only retrieval release and PR #91's reference study
records were verified at `9039c48c`. Production batching and recovery remained
disabled. Historical release receipts establish only their documented boundary;
current serving behavior must be checked independently.
