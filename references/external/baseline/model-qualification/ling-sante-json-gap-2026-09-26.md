# M11-OPS-LING-01 — Ling Sante JSON compatibility

**Disposition:** interface-compatible candidate; scientific quality unqualified.
Parent: M11-OPS-02b. The adapter remains provisional on the campaign branch.
No default or deployment change is accepted.

An isolated candidate now exists on the campaign branch: only the exact Ling
route omits unsupported `response_format`, while the existing local parser and
schema validator remain in charge. It passed a bounded synthetic interface panel.
Offline request-boundary and probe-runner tests passed. An independent Luna 6
read-only review found no blocking code defect, but required one physical JSON
request per case and stopping the panel on the first failed result; the bounded
probe now enforces both. Tool use is allowed two physical requests because a
successful call needs a tool request and a closing answer.

The [first bounded panel](ling-sante-bounded-panel-2026-09-26.json) sent three
physical requests. Schema JSON with reasoning requested off and on both passed.
The third, unschemaed JSON, returned valid JSON with the exact supporting quote
and label `Supports`. The probe had silently required lowercase `supports`
without asking for that casing, so it stopped on an invalid fixture criterion.
The raw failed score remains untouched. A red-first test corrected the scorer
to accept case variants for this unschemaed case only; schema validation is
unchanged. The untested tool, stream and long-context cases remain for one
bounded continuation. [Preflight](ling-sante-preflight-2026-09-26.json) pinned
exact-zero Novita pricing and ZDR inventory immediately before the first panel.

The [continuation](ling-sante-bounded-continuation-2026-09-26.json) used a
second [fresh preflight](ling-sante-preflight-continuation-2026-09-26.json)
and only the three untested cases. Tool use passed with one invocation of
`lookup_measurement(control-A)` and a closing answer containing the returned
137; the closing answer was verbose and described its tool limit, so this
synthetic success is not a scientific-quality result. Streaming produced
content, a `stop` finish, a model field identifying Ling Sante and reported
token usage. Its engine telemetry row recorded zero because the app streaming
boundary is outside that telemetry scope; the stream chunk itself supplies
usage, so no billed amount is inferred. The 126,555-character long prompt
returned schema-valid support with the verbatim quote. The two stages sent
seven physical requests total, each with Novita-only, ZDR, data-collection
denial and zero prompt/completion/request caps. Non-streaming usage reported
the requested Ling Sante model and complete token counts; no provider billing
receipt exists. No rate limit occurred. These observations clear the bounded
interface panel, not scientific parity, expert validation, or production
readiness. M11-OPS-02b3 remains open for frozen paired evaluation.

**Gap and behavior.** Qwen/ModelRun remains unavailable to campaign inference:
the single 26 September actual-interface request hit an upstream shared-pool
429. Ling Sante is an exact-zero free route in the current ZDR
inventory, but its Novita endpoint advertises tools and reasoning without
`structured_outputs` or `response_format`. The research engine needs validated
JSON for generation, review, grounding, and other workflow nodes.

**Evidence.** The [dated endpoint receipt](m11-free-route-current-research-2026-09-26.json)
pins price, ZDR presence, endpoint parameters, and the Qwen stop. Locally,
`engine/src/co_scientist/llm_request_schema.py:119-141` sends either
`json_schema` or `json_object` even when it injects the schema into the prompt.
`engine/src/co_scientist/llm_gateway_routing.py:350-381` requires advertised
parameters and only pins/data-protects explicitly declared providers. An
independent read-only Antigravity Gemini 3.8 Flash High review reached the same
no-code-change verdict; its suggested tool-call shim would additionally require
unpacking tool-call arguments at the response boundary. That suggestion is not
an adopted design or live capability result.

**Options and choice.** Try a prompt-only schema instruction using the existing
JSON parser and schema validator in an isolated candidate first. This is smaller
than translating every structured response into a forced tool call, and it keeps
the existing validation contract. It is not equivalent to provider-enforced
structured output. A red-first request-boundary test must show the current route
sends an unsupported `response_format`; the candidate should omit that parameter
only for the exact Ling route, pin Novita, and retain zero prompt/completion/request
caps plus ZDR/data-collection controls. Then one bounded synthetic actual-interface
JSON/tool/stream/long/reasoning panel may assess reliability, stopping on its first
error or rate limit. A pass would still require the campaign's declared scientific
quality comparison before default selection.

**Reject if** the endpoint cannot produce valid schema-matching content through
the project's parser, cannot reliably call tools, cannot fund an answer after
reasoning, or violates zero-price/privacy admission. Metadata alone resolves none
of those checks. No additional spending, private document, or user run is allowed.
