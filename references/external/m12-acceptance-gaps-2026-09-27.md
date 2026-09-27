# M12 acceptance-gap disposition after PR #60

**Finding:** The nine required repository assessments and accepted releases are
reconciled, but the original campaign acceptance criteria do **not** yet hold.
This is a negative acceptance finding, not a declaration that the campaign is
finished. [PR #60's release receipt](m12-space-bunny-release-2026-09-27.json)
establishes healthy deployment of the route code and null-author fix. It does
not establish a production model-role switch or a production research run.

| Candidate or gap | Current evidence-backed disposition | Evidence needed to close |
|---|---|---|
| `M11-NOV-01` result-conditioned novelty search | **Promising, unresolved.** The six-pair [pilot preregistration](sakana/novelty-result-conditioned-pilot-prereg-v1.json) still has `model_name: null`; no model comparison ran. The distinct precise-rung candidate failed its own frozen confirmation and does not dispose of this one. | Complete and commit the route-bound preregistration before calls; run its frozen pilot, and an independent three-pair confirmation only if the pilot passes. |
| Ling Sante/Novita | **Inconclusive, not selected.** The [frozen batch](baseline/model-qualification/ling-sante-batch-assessment-v1.md) had a pass, a completed miss and an incomplete trial. Neither qualification nor rejection follows. | Revisit only with a materially changed provider/route and a newly frozen criterion; do not replay the same mixed series to force a result. |
| Cloudflare Gemma 4 26B larger-output variant | **Untested, unqualified.** The [tool trial](baseline/model-qualification/cloudflare-workers-free-candidate-2026-09-26.md) stopped at its output ceiling; a larger budget may be a different candidate. The provisional adapter was removed. The owner's public-input retention waiver removes that one gate, but unattended Free-plan admission, completed tool behavior and scientific quality remain unverified. | Prove fail-closed zero-spend operation, preregister a distinct larger-output configuration and test only if it is justified over the selected route. |
| Space Bunny scientific quality | **Operationally compatible, scientifically unqualified.** The [public local run](m12-space-bunny-full-run-assessment-2026-09-27.md) finished 75/75 tasks with $0 internal estimated cost and no account-usage delta between snapshots, but 39/48 claim edges were insufficient, all 26 deterministic citation rows unsupported, and no matched-model comparison exists. | Complete applicable fixed-route scientific comparisons under unchanged gates; report failure or inconclusive results honestly. One completed run is not a reliability rate. |

Five original M11 live gates remain **owner-deferred and unverified** in the
[corrected register](deferred-followups-2026-09-25.md): replacement default
`M11-OPS-02c4`, novelty preregistration `M11-NOV-01a3b3b2`, six-pair pilot
`M11-NOV-01a3b3c`, conditional confirmation/adoption `M11-NOV-01b`, and
deployed Robin refinement `M11-ROBIN-01d4`. `M11-OPS-02b` describes historical
route investigation and is not a sixth gate. The local public run gives a
possible scientific input, but it is not an eligible run in production's
separate persistent store. The production model-role read remains unavailable
after automatic approval review rejected the Railway variable read.

The resulting answer to M12-01b's acceptance question is **no**. M12-02b3,
M12-03b and M12-04b stay open; neither deferral nor the release of route code
is evidence that their original checks passed. The [follow-up register](m11-follow-up-register.md)
retains the distinct candidate dispositions and source links.
