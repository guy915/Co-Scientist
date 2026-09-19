# Claim scope and partial support

Local design choice; not a claim about Google's private verifier.

The first retrieval-candidate pair scored 22/30 (.733) with .90 contradiction
recall, below the unchanged .75 accuracy gate. All six paraphrased supports
were correctly assessed. Seven errors were primary `partial` verdicts for
species/population or time/endpoint mismatches; one contradiction remained
insufficient because its quote did not meet the existing subject-coverage guard.
The historical controls, hybrid verifier and no-new-false-contradiction criteria
passed. The first pair remains failed; the frozen six-arm batch continues.

The single and batch prompts expressly allowed related/adjacent findings and
narrower conditions to establish partial support. This can give a support badge
to a human claim using animal-only evidence, or a long-term claim using only
an early surrogate measurement. The defect is in the stated entailment contract,
not the transport or schema. Existing failure artifacts are the red behavioral
evidence. The candidate clarifies that explicit claim-defining scope must be
addressed; partial remains available for an incomplete result within that scope.
Conditions not asserted by the claim must not be invented.

Independent review preferred this prompt-only correction over extra schema
booleans (the same judge's unverified assertion), keyword scope rules (brittle),
or another model pass (unnecessary added latency and calls). The four-label
schema, span validation, contradiction guard, budgets and publication gates stay
unchanged. Both public assessor paths receive the same rule.

`partial-support-scope-controls.json` adds prospective synthetic controls for
legitimate same-scope partial results, broad claims, full support, changed
population/model/dose/endpoint/follow-up, and same-scope contradiction. These
are not blind hold-outs or independent scientific adjudication. They must pass
alongside the unchanged challenge and historical controls in fresh matched live
trials. Preserve all old artifacts and do not reuse old answers as new results.
Primary metrics remain challenge accuracy and contradiction recall, improving
against the original pre-opposition baseline with .75/.80 gates in each pair.
The new scope controls are additional non-regression checks, not replacements
for failed challenge labels. Prompt edits and mocked assessor tests do not
establish scientific acceptance. The candidate remains open until live evidence.

Before launching that fresh comparison, bind the scope-control file hash into
its manifest, execute it separately through the public assessor in both arms,
persist labels and located-quote results, and require every candidate control
to pass in the comparator. The current frozen runner does not yet execute these
controls. Do not alter its shared probe while batch91986 remains active; this
wiring is pending, and no new scientific acceptance is claimed.

Cycle51 prepares `scope_controls.py` independently of the active observer. It
exercises single and batch public assessment interfaces with each control's own
evidence, retains located quotes, and requires a recognized model provenance.
Ten offline behavioral tests pass, including three reproduced false accepts for
unknown/non-model provenance. No live inference has used this helper. Batch
controls contain one claim per call to prevent cross-control evidence leakage;
full multi-claim behavior remains a workflow check. Original baseline provenance
is legacy-unknown: preserve that observation rather than manufacturing a model
method; candidate all-pass gating and physical telemetry remain separate checks.
Manifest, observer and comparator integration is still pending batch completion.

The prospective `evaluate_model_scope_controls` wrapper now calls both real
assessor factories with separate completed usage captures. Before launch, the
comparator must require both mode keys, every individual candidate check, physical
calls with matching served model and usage, and zero deterministic fallbacks.
`live=True` alone is not evidence of inference. Capture identity fingerprints
existing evaluator/request policies; bind the helper and control hashes as well.
Independent review approved this wrapper with those caller gates still pending.
