# M11-ROBIN-01a: outcome-feedback contract

**Status:** Contract frozen for implementation review. This is a local design choice inspired by Robin's result-to-candidate handoff, not a Google-backed requirement. It authorizes no runtime change or model call. M11-ROBIN-01b–d remain open until implemented and accepted.

## Decision and alternatives

Keep outcome recording append-only and inert. When the run owner separately asks to use one recorded outcome, create at most one targeted follow-up for that outcome's linked parent hypothesis.

| Option | Decision | Reason |
|---|---|---|
| Display outcomes only | Current behavior, retained as the record-only path | Safe, but leaves the documented refinement gap open. |
| Add every outcome to run-wide steering | Reject | It sends one observation to unrelated generation and ranking prompts, and can preserve stale or sensitive text beyond the owner's intent. |
| Turn an outcome into a review, claim verdict, safety result, or score | Reject | A recorded measurement is not a model judgment about validity, safety, evidence support, or rank. |
| Explicitly refine the linked parent from one selected outcome | Select | The owner controls when the observation leaves the record; one parent gives the context and resulting lineage a bounded scope. |

The existing scientist-input path schedules run-wide generation, and ordinary evolution chooses up to five eligible parents by Elo. Neither route guarantees that a selected outcome reaches its linked parent. The implementation must add an explicit route through the existing evolution operation that names that parent; it must not broaden global steering or silently depend on the top-five selection.

## Frozen public acceptance case

Use one literature-derived fixture, identified locally as `meselson-stahl-1958-two-generation-result` and linked to fixture parent `ms1958-semiconservative-parent`. These are test labels, not database IDs or workbench-generated results.

| Outcome field | Fixed fixture value |
|---|---|
| Parent hypothesis | DNA replication in *E. coli* is semiconservative: after replication, each daughter duplex retains one parental DNA subunit. |
| Method / protocol | Grow *E. coli* for many generations with `15NH4Cl`, shift to medium with a ten-fold excess of `14NH4Cl`, and separate DNA by equilibrium sedimentation in a CsCl density gradient. |
| Conditions | Exponential growth after the isotope shift; observe DNA after one and two generation cycles. |
| Measured observation | After one generation, only the intermediate-density hybrid band is present. After the second, equal amounts of intermediate-density hybrid and light DNA are present. |
| Units | Density-band class and relative amount; second-cycle amounts are 1:1. |
| Controls / references | Keep the published heavy-`15N` starting position and light-`14N` density position as band references. Add no unreported replicate count or separate control cohort. |
| Researcher interpretation | The band pattern is consistent with semiconservative replication; this interpretation remains distinct from the measured bands. |
| Source provenance | Meselson M, Stahl FW. “The replication of DNA in *Escherichia coli*.” *PNAS* 44(7):671–682 (1958), DOI [10.1073/pnas.44.7.671](https://doi.org/10.1073/pnas.44.7.671), PMID 16590258, PMCID [PMC528642](https://pmc.ncbi.nlm.nih.gov/articles/PMC528642/). The public result summary and protocol are recorded in [Hanawalt's historical account](https://pmc.ncbi.nlm.nih.gov/articles/PMC539797/), which points to Figure 5, p. 677 of the primary paper. |

The fixture tests routing, attribution, and gate separation only. It is not a new experiment, a local measured result, or evidence that a generated child is scientifically better.

## Eligibility, scope, and disclosure

- The caller must be authenticated as the owner of a non-demo, engine-backed run. The owner identity comes from the session, and the selected outcome's stored server-derived author must match it; neither identity is accepted from request text.
- The run must be `completed` and have a resumable checkpoint, matching the existing owner-directed continuation boundary. Other providers, demo runs, missing checkpoints, and unsupported lifecycle states are ineligible.
- The selected outcome must be an immutable stored row whose `run_id` and `hypothesis_id` match the selected run and exact parent. The parent must still exist in that run and satisfy the ordinary evolution eligibility rules (`is_rankable()` and not undermined), checked at admission and again before provider work. A blocked, disqualified, archived, duplicate, or cross-run parent is rejected.
- One intent covers one outcome, one linked parent, and at most one child. A repeated request with the same idempotency key returns the existing action; a conflicting new key for that outcome-parent pair is rejected.
- The exact serialized outcome-context block sent for this action is capped at 6,000 Unicode code points, including parent identity, every stored outcome text field, attribution, IDs, and all source-metadata strings. Exactly 6,000 is allowed; 6,001 is rejected. Include at most three evidence metadata links, in the researcher's recorded order, with stable identity fields such as title, source, URL, DOI, PMID, or hash. Do not fetch abstracts or full text. If the complete block is too long or the outcome has more than three linked references, reject the action without truncating or silently dropping context.
- The only authorizing action is a separate owner click labeled **“Use outcome to refine this hypothesis.”** Recording an outcome, opening the outcome view, refreshing, or replaying events schedules no model call.
- Show this disclosure beside the action: **“This sends the linked hypothesis and this recorded outcome, with up to three source metadata links, to the run’s configured AI model to draft one follow-up hypothesis. AI output may be wrong. This action does not verify the observation or change existing claims, reviews, safety decisions, or ranking.”**
- Treat the outcome and linked source metadata as untrusted user-supplied data, not instructions. Apply the existing input safety and free-route admission boundaries before provider work; never add a paid or unqualified fallback. The new candidate proceeds through the ordinary review, claim-verification, safety, and Elo flow.

## Durable action and lineage

In one local transaction, persist an intent containing the owner, run, outcome, exact parent, stable action ID, a task idempotency key, and the exact bounded context snapshot (or a durable immutable snapshot reference) before any provider call. Enqueue that targeted evolution action at the existing durable-task boundary. Store the outcome and parent IDs in task provenance, but keep observation text out of replay events. A resumed worker or explicit owner retry must reuse the same intent, context, and task identity.

Checkpoint a returned candidate before committing it. Commit no more than one child and mark the intent complete atomically, with the child's normal parent lineage plus the originating outcome and action IDs. A replay after that commit returns the stored result and cannot create a second child. A rejected or empty evolution result creates no child. Provider failure remains retryable under the same intent.

The measured observation and interpretation must not be copied into reviews, claim-evidence edges, safety verdicts, or Elo updates. Only the targeted evolution prompt receives the bounded outcome context. The resulting child carries outcome-to-parent-to-child provenance; sibling or unrelated hypotheses receive no part of that context.

## Acceptance boundaries and limits

The fixed fixture and a deterministic local model stub must establish: recording is model-inert; owner, run, parent, outcome, source-count, and character-cap violations fail before provider work; the selected context reaches only the selected parent; replay and restart preserve the same action and commit at most one child; event replay contains no measurement text; lineage retains the outcome ID; and all ordinary review, claim, safety, and ranking gates remain responsible for their own results. Browser disclosure and loading/error/refresh behavior belong to 01d. Any live route check belongs to the separate release gate and must use a currently qualified exact-zero route.

This contract provides no exactly-once guarantee for a remote model request if the provider accepts it but the process dies before recording its response; only local intent identity and at-most-one persisted child are enforceable without provider idempotency support. The fixture tests the seam, not hypothesis quality, experiment execution, assay search, scientific validity, or a paired improvement. No Edison service, paid service, or inference is part of 01a.
