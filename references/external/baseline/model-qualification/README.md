# Free-model qualification

Current status (cycle 122): no production primary or fallback is selected.

- **Contradiction candidate:** all three `opposition-magnitude-pro` pairs passed
  with the documented provenance correction. Candidate accuracy/recall were
  .967/.9, .933/.8 and .933/.8; baselines were .433/0, .367/0 and .433/0.
  See the [corrected receipt](opposition-magnitude-pro-corrected-summary.json)
  and [telemetry audit](opposition-magnitude-pro-telemetry-audit.json).
- **Nex Pro usefulness:** all three fresh trials passed; see
  [series 113 acceptance](usefulness-series113-acceptance.json). Earlier daily-cap
  and timeout attempts remain retained separately.
- **Nex Pro ranking:** all three trials passed with no top ties; see
  [series 114 acceptance](ranking-series114-acceptance.json). Trial 3 retained
  one recovered timeout with no response usage; all attempts had zero-price caps.
- **Nex Pro batch schema:** all three fresh context120 trials pass after the
  self-contained-quote prompt correction; guards remain unchanged. See
  [acceptance](batch-context120-acceptance.json). The failed
  [series 119](batch-schema119-summary.json) remains retained.
- **Nex Mini batch schema:** three independent fresh trials pass; see
  [Mini acceptance](mini-batch-context122-acceptance.json). Capability refresh
  and scientific panels remain open before fallback selection.
- **Remaining:** independently qualify fallbacks,
  select models, complete the local research workflow, and verify the release.

M1-04b1b-s1 and M1-04b1b are verified. The maintained observer repair is verified
as M1-04b1d; historical receipts retain their original observer. Failed scientific
series remain visible in [candidate evidence](partial-support-candidate.md).
The [declared model screens](remaining-panel-criteria.md) still govern acceptance.
Earlier results below are historical.

This is live eligibility and compatibility research, not a selected production
configuration. `catalog.json` retains the dated public catalog fields used by
the application's existing `verify_model` admission policy. Twenty-two explicit
routes pass; the deployed `minimax/minimax-m3:free` is absent. Audio-only Lyria
routes and the non-explicit `openrouter/free` router are not eligible.

Initial individual candidates, in probe order:

| Raw catalog ID | Why inspect it |
| --- | --- |
| `nex-agi/nex-n2.5-pro:free` | Current release advertising tools, structured output and 262k context; no assumed scientific superiority. |
| `nex-agi/nex-n2.5-mini:free` | Same advertised interface family, potential compatible fallback; must qualify independently. |
| `deepseek/deepseek-v4-flash-0731:free` | Advertised structured output/tools and 1M context; existing DeepSeek reasoning handling can be exercised directly. |
| `dots-studio/dots-3-note-preview:free` | Preview candidate with structured output/tools and 512k context; preview status does not establish reliability. |

Other eligible routes remain available if these fail. Metadata without advertised
structured outputs is a lower-priority compatibility lead, not a rejection of
scientific quality. Qwen, Liquid, Gemma and Nemotron structured-output candidates
are retained in the catalog for expansion. No unlisted stealth route is invented.
Runtime IDs prepend exactly `openrouter/` to the raw catalog ID.

`probe_json.py` sends one schema-constrained public entailment request through
`call_llm_json`, with caches disabled, one attempt and a 90-second observation
limit. It records full public input, schema, admission caps, response, telemetry
and sanitized failure. Its separately recorded admission body is a policy check;
it is not a wire capture. The shared physical request boundary independently
revalidates and attaches zero prompt/completion/request ceilings. Unknown static
pricing therefore does not remove the cap; cost estimates remain unknown.

Launch each probe in a fresh process with only the explicitly supplied
OpenRouter key, model and necessary runtime variables. Never source `.env`:
the launcher extracts that one credential in memory, and disables dotenv in the
child. No key goes in arguments or artifacts. `QUALIFICATION_OUTPUT` selects
the artifact path. Logs stay in `/tmp` and are not campaign evidence.

Still required: reasoning on/off and budget behavior, real app streaming deltas,
executed local tool plus final answer, representative long public inputs, and
scientific panels. For undeclared non-DeepSeek models the current gateway builder
sends no reasoning knob; a caller's `enable_thinking=False` alone does not prove
reasoning was disabled. Record effective behavior and add minimal tested model
configuration only when probe evidence justifies it. Qualify every fallback
independently before forming a production chain.

First live result (`nex-pro-json.json`, source `2a898f82`): one physical request,
HTTP/provider 400, no observed served-model identity or token usage. Nex rejected
`response_format` because its schema envelope lacks `name`. The engine's native
schema branch currently forwards the plain schema directly; production callers
also supply plain schemas. This is a compatibility investigation, not a quality
rejection. M1-04a1 tracks regression-first correction and live retry. No completion
or successful model qualification is claimed; usage/cost estimates remain unknown.

Native-envelope correction (cycle 28): the shared builder wraps bare schemas in
`{name: "response", schema: original}` and supplies the same default name for an
unnamed envelope. Existing names and envelope options remain intact; local
validation and the json_object path are unchanged. This matches the
[documented OpenRouter envelope](https://openrouter.ai/docs/guides/features/structured-outputs).

`nex-pro-json-envelope-fix.json` records the live retry: one physical call, valid
JSON, observed Nex Pro route, 71 prompt/112 completion tokens including 94
reasoning tokens. The requested reasoning-off flag did not disable reasoning
for this undeclared model, as anticipated. The artifact's `passed: false` is
retained: its verbatim quote check compares raw whitespace, while the returned
quote removes the input's newline between “viability” and “by 30%”. This is not
a schema failure; it remains a recorded probe outcome, not a scientific-quality
acceptance. Later tests should supply a single unwrapped passage string rather
than treating document layout as scientific content. Static billing estimates
remain unknown. The native request compatibility defect is corrected; broader
capability and scientific qualification remain open.

Cycle 29 Nex Pro capability trials (`nex-pro-capabilities.json`): short structured
entailment passes with requested thinking off and on; observed reasoning was
107 and 129 tokens respectively, so these flags do not demonstrate distinct
effective reasoning modes. A 126,555-character synthetic public context plus
explicit passage returns the correct label and verbatim quote (294 reasoning
tokens). This tests a long request with evidence at the end, not the full 262k
context limit or dispersed-evidence scientific synthesis.

The app's real admission and stream-draining interfaces yielded ten content
deltas, a `stop` finish, SDK model field `nex-agi/nex-n2.5-pro:free` and usage.
Shared engine telemetry shows zero for this case because app streams have a
separate observation path; use `stream_model_fields` and `reported_usage` rather
than interpreting that zero as no request. This does not exercise browser/SSE
or durable interview persistence, which remain full-workflow acceptance work.

The first tool case failed because the experimental executor returned a plain
payload instead of the engine's required tool-role message. This was a probe
error, not a product or model defect. Retained unchanged; superseded for tool
capability by `nex-pro-tools-corrected-probe.json`: two physical calls, one
validated local lookup invocation, final answer containing its numeric result,
and observed Nex model on both calls. The executor performs no network access.

No model is selected yet. M1-04b still needs other candidates, actual effective
reasoning control/budget behavior and representative complex schemas; M1-04c
still needs scientific panels. The current probe hashes itself in new artifacts
and checkpoints each case. All live calls traverse existing fresh eligibility
and zero-price admission. No paid alternative is substituted on failure.

Cycle 30 ran the same committed capability probe sequentially for the other
three candidates. Fresh eligibility was checked for every case; no rate limit
was observed. The original artifacts are retained without correcting outputs.

| Model | Short JSON off/on | Local tool loop | App stream | Long JSON |
| --- | --- | --- | --- | --- |
| Nex Mini | Both pass; 97/143 reasoning tokens | Pass | 10 content deltas, stop | Pass |
| DeepSeek Flash 0731 | Both pass; 0/53 reasoning tokens | Pass | 4 content deltas, stop | Wrong label and fabricated quote |
| Dots Preview | Both pass; 1400/716 reasoning tokens | Pass | 4 content deltas, stop | Pass |

Each tool trial records the expected local invocation and final numeric result.
Engine calls record the requested model as observed; app streams retain their
separate SDK model and usage fields. No claim of independent billing receipts
or comprehensive scientific capability follows from these smoke results.

Nex Mini, like Pro, has no declared reasoning profile: off/on flags currently
send the same control shape, and it reasons anyway. Before using either as a
selected deployment model, qualify an explicit profile that funds its reasoning
budget and test the resulting effective requests. DeepSeek's existing family
handling sends distinct enabled/disabled controls and uses JSON-object mode;
its failed long case used disabled reasoning and returned `contradicts` plus
an invented quote spanning “Record 0” to “Record 853”. This is a real incorrect
output, not a schema or transport error. Follow up with matched trials before
rejecting the candidate or attributing the effect to reasoning mode.

Dots has an existing declared mandatory-reasoning profile: “off” means bounded
minimal reasoning, not disabled reasoning. Its results support basic interface
compatibility under that profile. All long successes retain the prior limitation:
126k characters with the decisive passage at the end, not general long-context
scientific synthesis. M1-04b remains open for effective Nex reasoning/budget
qualification and representative complex schemas; M1-04c handles scientific
panels and final model/fallback selection.

Cycle 31 explicit Nex profiles: both variants are now declared reasoning-capable
with the existing conservative mandatory-reasoning behavior, no fallback chain
and no default-model change. Caller-off requests bounded reasoning (2048 tokens);
caller-on requests high effort. Both receive the existing 18k total-token floor.
This is not a claim that disabling reasoning is impossible: it is the bounded
mode qualified here while actual disable support remains unestablished.

Declaring these routes selects the existing JSON-object shim, including local
schema validation. `nex-pro-reasoning-profile.json` and
`nex-mini-reasoning-profile.json` rerun all five probes successfully under that
actual path. The probe observes non-secret kwargs at the physical LiteLLM seam
and forwards the real request unchanged; every recorded round has explicit zero
prompt/completion/request caps, the intended model, no fallback array and the
18k floor. Stream deltas and local tool execution still pass. No prior native
schema result is substituted for this changed configuration.

The existing static-pricing invariant required zero ModelPrice estimates for
the two newly declared routes; entries were added from their verified current
free metadata. These estimates do not authorize transport: fresh catalog checks
and zero ceilings remain mandatory. Live artifacts above predate that estimate
addition and correctly retain `unpriced_calls`; they are not rewritten.
Ninety-three routing, reasoning and free-admission regressions pass. Complex
scientific-schema/panel qualification remains outstanding before selection.

Scientific selection protocol (declared before trial results): use the existing
30-item citation-entailment challenge, not just the easy 20-item regression set.
Run three trials per shortlisted model on frozen code and evidence. Primary
metric is challenge accuracy; every selected model must also meet the existing
0.80 contradiction-recall and 0.75 accuracy gates in all three trials. Inspect
per-label precision/recall and abstention as non-regression evidence; do not
accept a higher score driven by deterministic fallback or unobserved models.
Ties favor consistent results then observed latency. This is model qualification,
not a claim of scientific improvement over the unavailable former primary.

Cross-model selection permits only the predeclared model and corresponding
routing profile to differ. Validate each manifest digest and compare every
remaining identity field; same-model repeated trials must have identical full
identities. The ordinary same-model panel comparison CLI is intentionally not
used to bypass that model distinction. Retain all failures. Rate limits stop
the batch for recorded later resumption. Physical starts are paced at least
four seconds apart. Model selection still requires ranking/usefulness and the
full research workflow; challenge success alone is not final acceptance.

Cycle 32 challenge investigation: the first Nex Mini challenge trial scored
0.433 accuracy and 0.0 contradiction recall, failing both unchanged gates.
It made 32 physical requests (two schema re-asks), all observing Nex Mini, with
no recorded deterministic fallback. The offline deterministic challenge scored
0.033 accuracy and 0.0 contradiction recall. These are failed results, not
successful model qualification. Further selection trials are deferred until the
assessment incompatibility is resolved; repeating the same structurally blocked
comparison cannot establish a winner.

`challenge-contradiction-diagnostic.json` maps the ten expected contradiction
items to initial physical responses using exact prompt hashes. All ten source
passages lack the marker required by `_quote_negates_claim`; even a correct
on-subject quote expressing reversed direction or numeric opposition is rejected
by that guard. Raw responses show both actual model insufficiency and correct
contradiction drafts subsequently downgraded. M1-04b1 investigates a correction
that preserves source/subject checks and historical false-contradiction
regressions. Do not merely add broad words to the marker list or lower recall
requirements to make the benchmark pass.

DeepSeek follow-up uses three identical long-input off/on pairs at `e0bc71af`.
All three enabled-reasoning cases returned the correct label and verbatim quote.
Disabled-reasoning cases produced two 100-second observation timeouts and one
wrong contradiction label with a fabricated quote. Timeouts record one attempted
physical request in `physical_request_controls` despite zero completed engine
telemetry calls; zero there is not evidence of no provider request or no spend.
The existing zero-cost admission still applies. This supports investigating its
reasoning configuration, not selecting the current disabled path as a reliable
fallback. No model selection or deployment followed.

Cycle 33 candidate protocol (before implementation/results): use a separate
semantic request for initial CONTRADICTS drafts rejected only by the lexical
marker requirement. Quotes must first resolve to actual source spans and clear
the existing .25 coverage floor. The verifier sees indexed claim/source-quote
pairs with source context, never the initial label; it checks matching conditions
and mutually exclusive assertions. Several eligible pairs share one request in
the batch assessor; the single-claim assessor can require one extra request per
claim. Missing, duplicated, ambiguous or failed verdicts remain insufficient.
The old lexical path and deterministic fallback retain their existing rules.

This is a local design choice, not Google-backed behavior. A same-model second
request remains correlated semantic evidence, not independent scientific proof.
Rejected alternatives: adding benchmark-specific words to the marker list;
trusting an opposition certificate in the original response; lowering gates.
Verified free requests do not add monetary spend, but their tokens, latency and
call-budget use must be retained. No production adoption precedes three paired
challenge trials: primary metric accuracy, contradiction recall must improve,
existing .80/.75 gates remain; all historical confirmatory/wrong-subject cases
must remain non-contradicting in each trial. Freeze source commits, model,
retrieval evidence and inputs; compare both sides on identical settings.

Candidate implementation note: malformed verification envelopes (missing,
duplicated, unknown or ill-typed indices/answers) invalidate the verification
wave. Valid false answers reject their own pairs. Provider/parse failures are
counted as `opposition_verification_unavailable` and missing valid answers as
`opposition_verification_incomplete`, under a separate `claim_opposition`
telemetry subphase. They are not deterministic fallback. Individual persisted
edges still name only the model; M1-04b1c requires verification-method lineage
before adoption. No experimental branch result is a deployed improvement.

Cycle 34 matched execution uses archive-only snapshots of baseline `14e8c599`
and candidate `06a17a70` in `/tmp/coscientist-paired-34/`. Both run from their
snapshot directory with explicit snapshot import paths and the same installed
dependency environment. The observer asserts and hashes actual imported modules;
the candidate-only verifier is explicitly absent from the baseline. The same
probe SHA256, complete dataset identity and fixed Nex Mini configuration must
match between arms. Each child freshly verifies the catalog and every physical
request retains its zero-price controls. The parent waits four seconds between
children; the probe paces actual requests at least four seconds apart.

Run order is baseline/candidate for trials 1, 2 and 3. The five historical
negative controls are extracted unchanged from committed regression fixtures;
only the allowed non-contradiction labels are adjudicated. Full live controls
are separate from a controlled-primary/live-verifier diagnostic: the latter
supplies the original erroneous contradiction label on the confirmatory GBM
quote, then lets the actual candidate verifier judge it. Its primary completion
is simulated, explicitly excluded from physical-request records and live-panel
telemetry. Baseline makes no verifier request; the candidate must make a real
one and reject opposition. This is not counted as a full live scientific panel.
All physical requests have phase and timestamp; per-assessment request indices
show which controls reached verification. No artifact is overwritten.

Cycle 34 results are complete and **not accepted**:

| Trial | Baseline accuracy / recall | Candidate accuracy / recall |
| --- | --- | --- |
| 1 | .367 / .0 | .667 / .8 |
| 2 | .433 / .0 | .567 / .6 |
| 3 | .400 / .0 | .667 / .6 |

The candidate improves each pair but fails the .75 accuracy gate in all trials
and the .80 recall gate twice. `compare_opposition_panels.py` validates the
retained `opposition-{baseline,candidate}-{1,2,3}.json` reports and regenerates
`opposition-paired-summary.json`. The summary explicitly allows only the named
assessor source delta; matched panel controls do not imply identical assessor
implementation. The same observer and historical-control hashes apply to all
six artifacts; `opposition-runtime.json` records the unchanged dependency set.

All 248 actual requests retain fresh free admission, zero-price caps, observed
Nex Mini identities and paced timestamps. All 30 full-live historical controls
across both arms passed; their primary responses were non-contradictory, so
these do not establish that the new semantic branch ran. The three separately
labeled controlled-primary diagnostics did invoke a live candidate verifier;
each returned explicit false conditions/opposition booleans. Simulated primary
responses are excluded from the physical requests and live-panel telemetry.
No challenge or historical panel recorded deterministic fallback.

The remaining errors are retained per assessment. In trial 1, the verifier
rejects matching conditions for the Drug A survival claim; the receptor-Y
paraphrase never reaches verification because its quote fails the unchanged
coverage floor. Other errors include partial labels on insufficient evidence.
The observed recall gain alone does not authorize deployment. M1-04b1b stays
open. Nex Pro was subsequently evaluated on the same pinned source revisions
with fresh matched baselines, as recorded below. Full batched workflow
verification remains required. The six-process launcher exited successfully; no trial
remains active. Source snapshots can be reconstructed from the full commits.


## Nex Pro paired qualification — completed cycle 43

Model: `openrouter/nex-agi/nex-n2.5-pro:free`. Source revisions, observer,
dataset, historical controls and runtime match the recorded frozen protocol.

| Trial | Baseline accuracy / recall | Candidate accuracy / recall |
| --- | --- | --- |
| 1 | .467 / .0 | .767 / .8 |
| 2 | .433 / .0 | .700 / .8 |
| 3 | .433 / .0 | .700 / .9 |

**Not accepted.** Two trials miss the unchanged .75 accuracy gate. All three
improve accuracy/recall, pass historical and controlled-primary/live-verifier
negative controls, and record no new challenge false contradictions or
deterministic fallback. The 229 physical calls retain explicit zero caps and
served-model evidence. Empty retrieval can still avoid a model request; absence
of fallback is not proof that every item reached the model.

Reproduce both summaries without inference:

```bash
.venv/bin/python references/external/baseline/model-qualification/compare_opposition_panels.py
.venv/bin/python references/external/baseline/model-qualification/compare_opposition_panels.py --series opposition-pro
```

Both report complete=true, accepted=false. The [failure analysis](pro-failure-analysis.md)
separates model labels from retrieval/guard limitations. Session 50677 exited 0;
no trial is running. No free model has been selected for production.

After this frozen experiment, per-assessment method provenance was added to
current code, persisted rows, reusable gate records, API/report payloads and
Markdown. That metadata change does not turn these failed qualifications into
acceptance; any subsequent scientific correction needs new matched evidence.

## Current scope comparison and recovery — cycle 89

The current candidate is `03ea8484`, compared with baseline `14e8c599` using
`openrouter/nex-agi/nex-n2.5-pro:free`; the evaluations subtree is pinned to
the baseline revision in both arms. See [the scope protocol](partial-support-candidate.md) for
fixed inputs, criteria, and the independently reviewed provenance correction.

Original pair 1 passes the separate corrected scope predicate and all other
paired gates. Original pair 2 is inconclusive because two baseline requests
lack usage and served-model telemetry. Original candidate 3 was interrupted
without a retained result. Neither gap is silently excluded: the
[pair-2 receipt](opposition-scope-pro-pair-2-evidence-gap.json) and
[interruption record](scope-interruption-recovery.json) remain authoritative.

`recovery1` repeats both arms of pairs 2 and 3 under separate names, preserving
pair 1. Recovery candidate 2 scores .933 accuracy/.80 contradiction recall;
recovery baselines 2 and 3 score .433/.0 and .400/.0. All three completed recovery
arms retain complete usage and model evidence plus zero-price caps. Recovery
candidate 3 remains pending. The full recovered series is not yet accepted.

After all replacement arms finish, run the paired comparator and separate
correction receipt with `--series opposition-scope-pro --attempt recovery1`
(comparator) and `--attempt recovery1` (correction). The original summaries stay
unchanged. A passing challenge comparison alone does not close model selection:
ranking/usefulness, independent fallback qualification, and the live research
workflow remain required by the selection protocol above. No production model
has been selected or deployed by this campaign.

## Replaying frozen comparisons after observer maintenance

The maintained scope observer now accepts guarded primary-model contradictions
without treating them as deterministic fallback. Historical raw flags and their
separate corrections remain unchanged. Run historical comparisons from their
original source, not the maintained helper: the current comparator deliberately
rejects a helper whose hash differs from a frozen manifest.

Archive `references/external/baseline/model-qualification` from
`c8a11d511268616ade139d217ffae2762a2a5da9` for the completed magnitude series,
or `c223b9ae19eb51fc5354618017627e87b8a3aae3` for scope recovery. Extract into
an isolated temporary directory. Use this repository's Python environment with
absolute repository/app/engine-src/evaluations paths on PYTHONPATH, dotenv
disabled, and GIT_DIR pointing to the repository's Git directory for historical
source verification. These comparator commands perform no inference.

For magnitude, run the archived `compare_opposition_panels.py` and
`scope_correction.py`, both with `--series opposition-magnitude-pro`.
For scope, run the archived comparator with `--series opposition-scope-pro
--attempt recovery1`, then its correction with `--attempt recovery1`.
Compare generated receipts byte-for-byte with the retained files before deleting
the temporary archive. `observer-replay-cycle104.json` records successful replay
of all four receipts, including the scope series' scientifically failed result.
