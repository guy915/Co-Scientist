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
