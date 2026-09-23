# Remaining model-selection screens

Declared before these live panels, cycle 103. **Local design choice**, not a
Google-backed threshold or evidence of scientific improvement. Apply the same
criteria independently to every proposed primary and fallback. Existing citation,
claim-support, safety and workflow gates remain mandatory.

Use the frozen datasets and evaluator hashes in `remaining-panels-preflight.json`.
Run three fresh-process trials per model per panel with identical configuration,
isolated caches and retained unique artifacts. Every trial must pass; mixed
results remain inconclusive and require diagnosis, not selective reruns or an
average that hides a failure. A changed configuration starts a new full series.

| Panel | Criteria for each trial |
| --- | --- |
| Citation usefulness | At least 13/16 correct; zero useless spans labeled useful; at least 6/7 useful and 2/3 partial items correctly classified. |
| Ranking | At least 6/8 correct top choices and mean Kendall tau-b at least 0.50, using the real production judge result. |

The usefulness floor limits errors to three; class-specific floors prevent a
passing aggregate from hiding failure on a whole class. Zero false-useful guards
the evaluator's documented critical retrieval error. Ranking requires both
correct top choices and broadly correct ordering. These are engineering screens
on small synthetic panels, not confidence bounds or expert validation. Historical
DeepSeek scores and offline controls provide context only, not matched baselines.

For every trial retain requested and observed model, evaluator/input/configuration
identity, raw judgments, physical request telemetry, zero-price caps, and fallback
evidence. Require verified current zero-price eligibility before each batch,
zero deterministic judgment fallbacks, and complete token/model evidence on every
successful completion. Retain every failed attempt and retry too; a recovered
transport attempt is not a scientific error, but missing telemetry or a terminal
failure prevents qualification. Report explicit provider cost when present; an
estimated zero alone never establishes free execution. Unknown applicable pricing
or a missing binding zero-price path prevents the request.

Use the existing public evaluator functions and exclusive-create filenames to
avoid same-day CLI overwrites. Keep offline controls visibly offline. No panel
may bypass the campaign admission, cache or credential boundaries. Rate-limit
parking preserves unfinished work and does not justify replacing the model with
a paid route.

Independent read-only review supported the thresholds and all-three-trial rule;
the partial-recall floor additionally prevents an untested label class from
passing on aggregate accuracy. No inference for these panels has started. Passing
these screens still requires interface qualification, the local research flow,
release checks, deployment and the production public-goal run.
