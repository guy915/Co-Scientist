# Bounded fallback capability qualification — cycle 178

## Candidate

- **Selected for one guarded batch:** `openrouter/nvidia/nemotron-3-super-120b-a12b:free`
- **Selection basis:** The fresh public catalog lists this explicit text route at prompt `0` and completion `0`, with `structured_outputs`, `response_format`, and `tools`, plus a 262,144-token context window. Retained cycle-164 evidence passed short JSON off/on, local tools, and streaming; the only retained gap was the representative long JSON request, which failed twice with upstream provider overload.
- **Why the other retained leads were not chosen:** Qwen had no completed case after two shared-pool `429` responses (`qwen-capabilities164.json`, `qwen-capabilities-recovery168.json`). Gemma had no completed case after a shared-pool `429` (`gemma31-capabilities168.json`) and currently advertises `response_format` but not `structured_outputs`.

## Evidence

- Public catalog: [`openrouter-catalog178.json`](openrouter-catalog178.json), fetched `2026-09-22T08:52:25.208654Z` from `https://openrouter.ai/api/v1/models`; raw response SHA256 `2cf4847930445a5f1513061e6449d548b87b1f632abdf7b1e9c0da57c9005aa6`.
- The raw catalog contained 444 entries and 21 explicit `:free` text-output routes with prompt/completion price `0`. The stored comparison against `free-catalog163.json` has no added IDs. Its three absent IDs are audio-only Lyria routes and the non-explicit `openrouter/free` router, already excluded by campaign eligibility; this is not evidence that OpenRouter removed them from its catalog.
- Runtime preflight fetched a fresh catalog through `co_scientist.llm_free_catalog.current_catalog()` and `verify_model()` accepted the selected raw ID with prompt `0` and completion `0`. The credential was extracted in memory from the existing local `.env`; it was never printed or sourced.
- Source revision: `9ad8bac9152ce5a97f2b13543fe57392d7849a2c`. Probe SHA256: `1a470cc7c7fb6cf7e35b0d116c65dc5e0ba4c88854ae0f73127a82ff78574abf`.
- Capability artifact: [`nemotron-super-capabilities178.json`](nemotron-super-capabilities178.json). Runner PTY session: `94738`; it exited before post-run inspection at `2026-09-22T08:54:37.376429Z`. No capability process remains.
- The launcher used a clean environment, `PYTHON_DOTENV_DISABLED=1`, `COSCIENTIST_REQUIRE_FREE_MODELS=1`, disabled cache, the selected model for every model role, and no alternate model. Every recorded request carried provider caps `max_price.prompt=0`, `max_price.completion=0`, and `max_price.request=0`; no paid route or paid fallback was permitted.

## Results

The batch started at `2026-09-22T08:53:40.312528Z`. The existing probe ran one sequential capability batch; no scientific challenge trials were launched.

| Case | Result | Physical requests | Served-model evidence | Error / retry state |
| --- | --- | ---: | --- | --- |
| `json_off` | pass | 1 | 1 observed selected model; 1 usage record | 297 prompt, 120 completion, 100 reasoning tokens; 1.733s; no retry; estimated cost `$0` |
| `json_on` | fail, operational | 1 | no observed completion; 1 unreported request | `ServiceUnavailableError`, Nvidia upstream temporarily overloaded; `max_attempts=1`, no retry |
| `tools` | fail, operational | 2 | 1 observed selected model and usage; second request unobserved | second loop request hit `ServiceUnavailableError`; one tool-loop retry/iteration, no model fallback; zero caps on both requests |
| `streaming` | fail, operational | 1 requested stream | no served-model or usage record | `MidStreamFallbackError` caused by Nvidia overload; no completed stream; no retry |
| `long_json` | fail, operational | 1 | no observed completion; 1 unreported request | `ServiceUnavailableError`, Nvidia upstream temporarily overloaded; `max_attempts=1`, no retry |

No deterministic fallback event was recorded. The batch is operationally inconclusive and does not qualify the candidate.

## Remaining

- Nemotron Super remains an unqualified fallback: current evidence has one successful short JSON off case, while reasoning-on JSON, tools completion, streaming, and long JSON were blocked by provider overload in this batch.
- The prior long-input gap remains unresolved; no automatic retry or paid substitution was attempted, consistent with the provider errors and zero-price policy.
- Qwen and Gemma remain deferred behind their retained shared-pool `429` evidence. No threshold, source, or PLAN file was changed.
