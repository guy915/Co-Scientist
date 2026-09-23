# Bounded Qwen capability retry — cycle 179

## Candidate

- **Requested model:** `openrouter/qwen/qwen3.8-27b:free`
- **Frozen source:** `7f4d845e05d80314daff2b7e33dd25870677eb37`
- **Reason for retry:** Qwen was the remaining compatible fallback lead from cycle 178, but `qwen-capabilities164.json` and `qwen-capabilities-recovery168.json` both stopped on an upstream shared-pool `429` before producing a capability result.

## Evidence

- Credential-free public refresh: [`qwen-eligibility179.json`](qwen-eligibility179.json), checked `2026-09-22` before any credential was loaded.
- Raw catalog source: `https://openrouter.ai/api/v1/models`; response SHA256 `2cf4847930445a5f1513061e6449d548b87b1f632abdf7b1e9c0da57c9005aa6`; 444 catalog entries.
- Fresh runtime `current_catalog()` and `verify_model()` accepted the exact raw route. Current metadata reports prompt `0`, completion `0`, text input/output, structured outputs, tools, and 262,144 context.
- Runtime preflight made zero provider calls. The capability launcher extracted the OpenRouter credential in memory from the existing local `.env`, disabled dotenv, and used a clean isolated environment. The credential was never printed or written to an artifact.
- Existing probe SHA256: `1a470cc7c7fb6cf7e35b0d116c65dc5e0ba4c88854ae0f73127a82ff78574abf`.

## Results

- Capability artifact: [`qwen-capabilities179.json`](qwen-capabilities179.json).
- Runner PTY session: `35661`; started `2026-09-22T09:03:33.450395Z` and exited after the first case. No qualification process remains.
- The first `json_off` request made one physical request with provider caps `max_price.prompt=0`, `max_price.completion=0`, and `max_price.request=0`. It returned `RateLimitError` / HTTP `429` from the upstream shared pool.
- Exact provider reset hint: `qwen/qwen3.8-27b:free is temporarily rate-limited upstream. Please retry shortly, or add your own key to accumulate your rate limits, or route to another provider with provider routing.`
- Retry state: probe `max_attempts=1`; observed retries `0`; the batch stopped immediately on `RateLimitError`. No paid route, provider substitution, or retry timer was started.
- Served-model evidence: none. Usage evidence records one unobserved/unreported model request, zero completion tokens, zero estimated cost, and no deterministic fallback.
- No JSON-on, tools, streaming, long-context, or scientific cases were attempted after the terminal `429`.

## Remaining

- Qwen remains capability-unqualified because the provider shared-pool limit prevented even the first structured-output observation. This is an operational interruption, not a scientific rejection.
- The provider’s reset hint is retained for a later separately authorized run; this task created no scheduled retry and leaves no timers.
- No source, frozen manifest, or PLAN file was modified.
