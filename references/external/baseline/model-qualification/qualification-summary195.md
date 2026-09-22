# Gemma 4 26B capability qualification — cycle 195

## Selected action and rationale

- **Requested model:** `openrouter/google/gemma-4-26b-a4b-it:free`
- **Action:** Run one fresh-process `json_off` compatibility probe after the recorded backoff and the corrected schema-route and terminal-error fixes.
- **Rationale:** This is a materially corrected bounded request against the previously untested Gemma 4 26B free route. The current public catalog and the exact `:free` endpoint both reported zero prompt and completion prices before credential loading.

## Eligibility and invocation

- Fresh credential-free catalog and endpoint receipt: [`gemma26-eligibility195.json`](gemma26-eligibility195.json), checked `2026-09-22T12:07:25.413638+00:00`.
- Catalog SHA256: `37b63e5670f95b3526ba65b6d316fd0d184c03460207fb476097a95e7d3b0945`; 444 entries.
- Exact endpoint `https://openrouter.ai/api/v1/models/google/gemma-4-26b-a4b-it:free/endpoints` returned HTTP 200 with one endpoint, prompt/completion pricing `0`.
- Source revision: `49111a15ba372842a3316ae8edcbd59c8807e55e`.
- Existing runner: [`probe_capabilities.py`](probe_capabilities.py), SHA256 `cdfe1c5fa688254b06ddc4bf92e1e7121b77d4d6814978306b8909a1abebf014`.
- The fresh child used canonical repository, app, engine and evaluations paths; dotenv disabled; cache disabled; campaign free-model admission enabled; exact model only; one selected case; no paid fallback or retry loop.

## Exact outcome

| Case | Result | Physical requests | Provider evidence | Stop state |
| --- | --- | ---: | --- | --- |
| `json_off` | terminal operational failure | 1 | `RateLimitError` 429 from Google AI Studio, upstream shared pool temporarily rate-limited | stopped immediately; no further case launched |
| `json_on` | unavailable | 0 | not attempted after terminal error | unavailable |
| `tools` | unavailable | 0 | not attempted after terminal error | unavailable |
| `streaming` | unavailable | 0 | not attempted after terminal error | unavailable |
| `long_json` | unavailable | 0 | not attempted after terminal error | unavailable |

The single request captured the exact free route, `response_format={"type":"json_object"}`, `max_tokens=6000`, and provider controls `max_price.prompt=0`, `max_price.completion=0`, `max_price.request=0`, `require_parameters=true`. No served-model identity or reported usage was returned; the request was retained as one unreported and unobserved physical call. No paid route, own provider key, deterministic substitute or retry was used.

## Process handle and remaining steps

- Terminal session: `25216`; launcher PID: `34438`; probe child PID: `34439`.
- Launcher exited `1` after the terminal `RateLimitError`; no process remains. Log: `/private/tmp/gemma26-capabilities195-json_off.log`.
- Gemma 4 26B remains capability-unqualified. Do not continue this batch or start a scientific batch; any future compatibility attempt needs a new eligibility receipt and an explicitly authorized later retry after provider backoff.
- This cycle added only the `gemma26-*195` evidence and this summary; no runtime, PLAN, deployment, schedule or committed source changes were made.
