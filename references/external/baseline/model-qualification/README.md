# Free-model qualification

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
