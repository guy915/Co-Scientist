# External source campaign — scoped closure report

**As of:** 25 September 2026. **Status:** Nine required source assessments and accepted product releases are reconciled. This is the PR #46 scoped evidence snapshot, not final acceptance of the original campaign: eight unfinished M11 follow-ups remain open in `PLAN.md` after the owner's status correction. None is completed, verified, or rejected by deferral.

## Reconciliation

The [source inventory](README.md) and all nine [source dossiers](README.md#L17-L27) agree on the pinned 40-character revisions (9/9). A fresh static pass found no missing target paths among 186 relative links in the inventory, nine dossiers, and M11 register. This confirms repository-internal consistency only; it is not a live check of upstream branches. The [M12 audit](m12-reconciliation-audit.md) records the candidate-level evidence and corrections, including K-Dense's `KDS-*` ID exception and the distinction between Robin's released code and its still-open live observation.

| Source | Adopted or released disposition | Remaining candidate disposition |
|---|---|---|
| [Kaimen](kaimen-inc-co-scientist.md) | No adoption. | Two candidates already covered, two outside scope, two rejected on source evidence. |
| [Conradry](conradry-open-coscientist-agents.md) | `M3-02` supervisor-plan visibility and `M3-04` per-idea match history. | Six candidates covered, rejected, or outside scope. |
| [LLNL](llnl-open-ai-co-scientist.md) | `M4-01` failure guidance and `M4-09` BYOK-key diagnostic redaction. | Seven candidates covered, rejected, or outside scope. |
| [Raktim Mondol](raktim-mondol-co-scientist.md) | `M5-10` owner-scoped empirical outcomes and report/UI replay. | Eleven candidates covered or rejected under the recorded replacement, scope, safety, or evidence limits. |
| [K-Dense](k-dense-scientific-agent-skills.md) | `KDS-CITE-02` bounded OpenCitations edge lookup. | Five candidates rejected, covered, or outside scope. |
| [Sakana](sakana-ai-scientist.md) | PubMed parser correction for valid records without `AuthorList` released separately in M11. No novelty-search change was adopted. | Five source candidates are covered, rejected, or outside scope; result-conditioned search remains open as `M11-NOV-01`. Precise-rung retrieval is a separate open M11 candidate. |
| [OpenScience](synthetic-sciences-openscience.md) | Owner-scoped request receipts and lifecycle corrections; ambiguous LLM-timeout recovery released as `M11-LLM-02`. | Remaining source candidates are covered, rejected, or outside scope; no separate runtime was added. |
| [ToolUniverse](mims-harvard-tooluniverse.md) | Independent cache/error and retraction-data improvements; bounded GWAS association lookup released as `M11-GWAS-07`. | Other candidates are covered or rejected on their recorded evidence. |
| [Robin](future-house-robin.md) | `M10-01`'s explicit, owner-authorized outcome-to-parent refinement path released through M11. | Assay automation is out of scope, mechanistic criteria and durable trajectories are covered, and direct Choix replacement is rejected. The live campaign observation remains open. |

The candidate detail stays in the dossiers. No unresolved promising candidate is represented here as finished. No additional repository was selected: the [M11 register](m11-follow-up-register.md) found no distinct unaddressed mechanism among the proposed categories.

## Adopted changes and measured outcomes

- Conradry's viewer ideas became disclosures over the existing supervisor ledger and match records; they did not change scheduling or Elo. LLNL-informed run guidance and BYOK redaction use existing failure and credential boundaries.
- The Raktim-inspired outcome path stores a measured result under its owner and linked hypothesis, exposes it in the workbench/report, and keeps it out of review, claim, safety, and Elo verdicts. M11's frozen two-generation case verifies one linked child traverses the ordinary gates; no live production outcome action was observed.
- K-Dense's lookup returned 57 incoming citations as a count and 45 outgoing references under the 50-edge cap. These are citation relationships, not evidence that one paper supports another.
- OpenScience-informed request admission and lifecycle recovery were tested at the local API/worker boundary. M11 timeout recovery and the M9 GWAS tool shipped in PR #41; the deployed keyless `rs334` call returned one association for study `GCST90480652`. That association is contextual and not causal evidence. The separate PubMed parser fix shipped in PR #44; the deployed normal-record probe returned PMID `22745249` with six authors, while the missing-`AuthorList` case is covered by the offline regression.
- ToolUniverse-inspired retraction-data refresh added 1,331 DOI entries and removed two; the refreshed resolver recognized the newly included DOI as retracted. No absence of a notice is labeled a clean result.
- Robin's implementation and frozen-case/UI release are covered by PRs #43 and #45. PR #45 records local checks, Playwright 18/18, production smoke 5/5, and healthy API/MCP/Vercel deployments on merge `91c70ed0dd23b34529f19fbfb9331b247d56ef9d`. That merge object resolves locally and is an ancestor of `origin/main`. Hosted CI failed before its affected-target job ran; the user-authorized waiver is not a passing CI result.

The source-release trail is PRs [#22](https://github.com/guy915/Co-Scientist/pull/22), [#23](https://github.com/guy915/Co-Scientist/pull/23), [#24](https://github.com/guy915/Co-Scientist/pull/24), [#25](https://github.com/guy915/Co-Scientist/pull/25), [#28](https://github.com/guy915/Co-Scientist/pull/28), [#30](https://github.com/guy915/Co-Scientist/pull/30), [#35](https://github.com/guy915/Co-Scientist/pull/35), [#37](https://github.com/guy915/Co-Scientist/pull/37), and [#39](https://github.com/guy915/Co-Scientist/pull/39). Follow-up releases are [#41](https://github.com/guy915/Co-Scientist/pull/41), [#43](https://github.com/guy915/Co-Scientist/pull/43), [#44](https://github.com/guy915/Co-Scientist/pull/44), and [#45](https://github.com/guy915/Co-Scientist/pull/45). Their retained receipts distinguish local checks, deployment status, smoke results, and hosted-CI waivers. A fresh [no-inference production audit](final-release-audit-2026-09-25.json) finds all three services healthy on `91c70ed0`, with GET-only smoke 5/5; its deployment IDs are the current known-good rollback target. Railway hides exact runtime values, so this audit cannot confirm the live model route, DB/cache paths, UID, worker flag or shared-secret match.

## Deferred open items

The owner directed skipping blocked or rate-limited work for the time being. These eight items are **unfinished and still open in the original campaign**, not complete or rejected. Their evidence and revisit triggers are recorded in the [deferred follow-up register](deferred-followups-2026-09-25.md); their acceptance criteria remain in [PLAN.md](../../PLAN.md):

- `M11-OPS-02b` and `M11-OPS-02c`: qualify a current exact-zero route, then only if qualified switch defaults and verify deployment. The single bounded Qwen/ModelRun interface probe stopped on an upstream 429; there is no served-model or usage receipt, and no replacement qualified by the retained privacy/capability screen.
- `M11-NOV-01a3b3b2` and `M11-NOV-01a3b3c`: pin a qualified route and complete the preregistration, then run the one bounded six-pair result-conditioned pilot. The prepared protocol has `model_name: null`; no candidate call occurred.
- `M11-NOV-01b`: if that pilot passes, run a separately eligible three-pair confirmation before any adoption. No confirmatory result exists.
- `M11-NOV-RUNG-01b2b` and `M11-NOV-RUNG-01c`: finish a valid precise-rung retrieval comparison and make its separate disposition. The recorded attempt stopped at trace verification after one baseline MCP call. It produced no usable result or blind labels; the actual external PubMed request count is unknown, so it is not reported as zero. The frozen no-retry comparison was not scored, adopted, or rejected.
- `M11-ROBIN-01d4`: observe the explicit refinement on an eligible campaign-owned production run. The retained public run has eight route-admission failures and zero hypotheses; no eligible alternative run was established, and no refinement was attempted.

The [M11 release receipts](m11-release-verification.json) and [Robin UI receipt](robin/m11-ui-release-verification.json) show that accepted code is released independently of these deferred follow-ups. The timeout path was not tested by inducing an ambiguous production provider response. No post-route-change public research run or report establishes scientific improvement, expert validation, or a wet-lab result.

## Attribution and release boundary

Each dossier records its pinned source license and exceptions. The review covers permissive roots (Apache-2.0 or MIT), Sakana's conditional AI Scientist Source Code License, and component/service boundaries including GPT Researcher, Raktim's `x_code/` tree, K-Dense and OpenScience bundled materials, Sakana's NVIDIA helper, ToolUniverse's conflicting documentation license and optional AGPL package, and Robin's Edison/provider terms. Accepted behaviors were independently implemented; the dossiers do not report copied source code. The existing [NOTICE](../../NOTICE) was checked for retained shipped attributions, including the DOI-derived Retraction Watch data and vendored Science Skills. It does not grant rights to unrelated upstream components.

The campaign branch also contains experimental PubMed pilot instrumentation under `engine/mcp_server/` without a candidate acceptance or release receipt. This report does not count it as an adopted product change. Keep the final closeout change reference-only from `origin/main`; retain the experiment as evidence under `references/` unless it receives a separate acceptance.

## Campaign acceptance boundary

The [scoped offline verification](final-closure-verification.md) and no-inference production audit are complete. The released product code passed its release-time checks and browser suite; the reference-only closeout branch additionally passed the function-length gate and offline safety/citation smoke. The original campaign is **not complete**: eight follow-ups remain open, the experimental PubMed branch's separate check failed, and no fresh public research run, live refinement, current model-role readback, or scientific-quality result is claimed. No Google private-implementation or fidelity claim is inferred from the nine external repositories.
