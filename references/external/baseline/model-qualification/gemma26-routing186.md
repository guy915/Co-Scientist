# Gemma 26B routing diagnosis

Classification: **local design choice**. This concerns provider compatibility,
not Google Co-Scientist behavior or scientific quality.

The retained cycle-185 JSON requests sent `response_format.type=json_schema`
with a named envelope. Both failed with HTTP404 at `Filter by Parameters`.
The tool request instead reached the provider and received a shared-pool429.

A credential-free [endpoint API read](https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it:free/endpoints)
is retained in [gemma26-endpoints186.json](gemma26-endpoints186.json). The single
listed Google AI Studio endpoint has zero prompt/completion pricing and lists
`response_format`, but not `structured_outputs`. OpenRouter's
[structured-output documentation](https://openrouter.ai/docs/guides/features/structured-outputs)
identifies the latter as the endpoint capability to check for native JSON-schema
requests. Metadata is time-sensitive and must be refreshed before inference.

Inference: native JSON-schema selection is the likely incompatible parameter;
this is stronger evidence than treating the404 as generic temporary overload.
It does not establish that JSON-object mode will succeed or that this model is
scientifically suitable.

Local counterpart: `engine/src/co_scientist/llm_request.py` chooses schema support
using explicit exceptions and LiteLLM's registry. Undeclared Gemma currently
reaches the native-schema branch. The existing JSON-object alternative in
`llm_request_schema.py` inserts the schema into the prompt; JSON parsing and
local schema validation remain in the shared engine path.

Next candidate: reproduce the exact route's mismatch offline through the LLM
request boundary and select the existing JSON-object path for a justified,
bounded exception. Avoid a blanket rule for all Gemma providers or future
versions. Keep `require_parameters=true`, all zero-price ceilings, schema
validation and retry budgets. A later free live response after provider backoff
is required before compatibility acceptance. No production setting or runtime
code was changed by this diagnosis; no inference was performed.


## Offline correction — cycle 187

The request builder now selects the existing JSON-object shim only for
`openrouter/google/gemma-4-26b-a4b-it:free` (case-insensitive). Other Gemma routes
continue to use their existing registry decision. This is a provider capability
exception, not adding Gemma to the deployed fallback chain.

Before the next live compatibility attempt, refresh catalog and endpoint
eligibility, use the current committed source and probe hash, and run the
existing capability probe with `QUALIFICATION_CASES=json_off` in the established
isolated environment. Stop on any nonzero exit or recorded error. Only expand
to reasoning-on, tool, streaming and long-input cases after the bounded request
succeeds. Retain the served model, request caps, usage and response artifact.
The September 22 backoff decision remains in force; no live test occurred in
cycle187. This change requires fresh affected release checks and source
manifests before eventual deployment; cycle178 results predate this change.
