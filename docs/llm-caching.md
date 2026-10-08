# Prompt caching

Transport uses the existing gateway. Provider order and per-user limits do not change.
Claude Haiku 5.5 remains a BYOK model. Azure remains off unless the operator enables it,
sets a positive total EUR allowance and sets an unexpired credit date.

T supplies a `CacheablePrompt` from `core/prompt_cache.py`: final rendered text and two
character offsets, `run_end` and `item_end`. Appending a schema preserves these offsets.
The gateway sends five-minute breakpoints at both boundaries on Haiku 5.5. Tool loops
and chat also use top-level automatic caching. A request may have at most four cache
breakpoints, including the automatic one. No delimiter from user text is interpreted.

Haiku 5.5 always sends adaptive thinking and low effort, including recovery attempts.
The verified thinking parameter is allowed explicitly when the bundled SDK catalogue lags.
Signed thinking blocks survive engine and Q&A tool continuations. Stream fragments use
the pinned SDK assembler and stay in scoped memory.
Its USD/M rates through 100K input are input 0.10, output 0.50, read 0.01 and write 0.125.
Above 100K input they are 0.50, 2.50, 0.05 and 0.625. The gateway uses five-minute writes;
one-hour writes are not selected. Raw Claude input, read and write buckets are separate.
LiteLLM adds the latter two to prompt tokens; cost removes them before pricing each once.

Azure receives `prompt_cache_key` from run context and call role. A rolling 60-second
window starts a stable numbered partition after 15 requests per key. State uses a thread
lock, at most 4096 run/role entries and 256 partitions per entry; under larger bursts,
cache hits are best effort. No lock covers provider I/O. Calls without run context use
provider automatic caching. Nano receives no new cache options or breakpoints. The Azure
key API is covered by the installed SDK test; cache-hit behavior still needs a live check.

Azure writes are an additional input charge. The durable EUR ledger already reserves
and records them. Missing priced write usage keeps the full reservation. The single total
cap, request-time expiry and kill switches still apply. General usage now records writes
and uses each model's published read/write rates; Nano reads cost 0.01/M, not 0.1 times
its 0.05/M input rate. The ledger retains conservative Luna long-context rates until its
short/long boundary is confirmed. USD usage estimates do not replace that credit guard.

Private spans export numeric input, read and write counts plus a stable numeric call-type
ID. Cache keys and prompt text are excluded. Existing usage aggregates include write counts.

The cache becomes readable after the first response begins. A cold parallel wave may
miss on every call. Reuse a byte-identical prefix, let the first response begin, then send
the remaining calls without an extra warm-up request. T owns layout and E owns call reuse.

Completion needs T's boundary integration, E0's per-call-type meter and one budgeted live
Express run per provider. Hermetic SDK tests prove payload and accounting behavior; they
do not measure a real cache hit or claim live savings. No live measurement is recorded yet.

Sources checked 8 October 2026:

- [Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost)
- [Azure caching](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/prompt-caching?view=foundry-classic)
- [Azure prices](https://azure.microsoft.com/en-us/pricing/details/azure-openai/)
- [Cache-write billing](https://community.openai.com/t/how-are-reasoning-tokens-cached-tokens-input-tokens-and-output-tokens-counted-for-billing/1386849/3)
