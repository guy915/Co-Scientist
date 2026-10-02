# Tool retries and separate app provider budgets

The owner approved both recommendations on 2 October 2026, resolving items 1
and 2 from the preceding architecture review.

## Tool turns

A turn gets at most three physical model attempts through the existing
`run_attempts` policy. Temporary throttling and outages use the existing
jittered schedules. Platform quotas raise `LLMRateLimitParkError` so the
durable worker parks the task without spending its task retry allowance.
Timeouts, call-budget exhaustion, oversized prompts and failed free admission
remain terminal. Retry telemetry now includes tool turns.

The attempt stops before tool execution and uses the same transcript on an
in-place retry. Tools from completed turns are not replayed by this loop.
Durable quota parking retains the existing task-level resume semantics; it
does not introduce a checkpoint after every tool call. The mandatory-reasoning
request shape is unchanged. Escalation and transient recovery share the
three-attempt allowance, bounding spend even when both occur in one turn.

## App provider transport and accounting

Streaming/plain-text calls use the same installed completion backend as the
engine, through public `complete_request`. That transport owns free admission,
physical-request reservation, establishment/hard deadlines and usage capture.
It does not replay a stream or add app retries. Existing thinking-only retry
and Q&A tool-round policies remain at their app call sites.

An interview, Q&A exchange, title, goal restatement, announcement or credential
probe receives a separate operation budget: `APP_LLM_MAX_CALLS`, default 4,
minimum 1. This is a physical-call cap, not a dollar estimate or a daily client
quota. Retries, question repair and tool rounds share it; nested helpers reuse
the enclosing operation budget. Concurrent child calls reserve from
the same thread-locked counter and refused calls never reach the backend.
The ephemeral scope overrides research counting and telemetry while active,
then restores them. It does not alter persisted research metrics or tier caps.

Streaming still bounds silence between chunks and has its existing total
backstop. A producer owns one context for the entire app stream, including
BYOK scopes across yields; acknowledgement-based backpressure prevents a slow
or cancelled consumer from initiating the next round early. Cancellation and
deadlines close the provider stream. All queues/futures belong to one operation
on one event loop, never a process-wide worker-cohort primitive.

Usage is aggregated in memory and logged once per operation. Final stream
usage is requested and captured when supplied. Missing usage and cancellation
remain incomplete cost evidence, rather than an observed zero bill. No prompt
or credential enters the usage summary. App token floors now delegate to the
engine; the app timeout floor is derived from that token floor at the existing
75 tokens/second assumption. Conversational effort remains app policy.

## Validation

New scripted-provider tests reproduced immediate tool failures and the app's
backend bypass before the changes. Focused suites cover bounded retries, quota
parking, unchanged tool execution, shared admission, independent/concurrent
budgets, hard cancellation, stream usage, backpressure and context restoration.
The existing stream, thinking, free-routing, BYOK and worker parking tests are
retained. Full engine/app suites, mypy for three projects, lint, parity, length
gates and browser/Docker CI are required before merge.
