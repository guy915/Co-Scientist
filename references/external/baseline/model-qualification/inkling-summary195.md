# Inkling capability qualification — cycle 195

## Selection and eligibility

- **Requested model:** `openrouter/thinkingmachines/inkling:free`
- **Selection:** Inkling was selected over `inclusionai/ling-3.0-flash-sante:free` because its current catalog description is general-purpose, multimodal and tool-oriented, with a 1,048,576-token context; Ling is text-only, medicine-focused, and 262,144 tokens.
- Fresh credential-free catalog and exact endpoint receipt: [`inkling-eligibility195.json`](inkling-eligibility195.json), checked `2026-09-22T12:22:38.907172+00:00`.
- Catalog SHA256: `37b63e5670f95b3526ba65b6d316fd0d184c03460207fb476097a95e7d3b0945`; 444 entries.
- Exact `:free` endpoint returned HTTP 200 with one endpoint and prompt/completion pricing `0`.
- Offline schema inspection selected the existing registry path `supports_json_schema_response_format=False`. The catalog and endpoint advertise tools and reasoning but neither `response_format` nor `structured_outputs`, so JSON cases were withheld rather than sending the known unsupported response-format path under `require_parameters=true`.

## Bounded invocation

- Existing runner: [`probe_capabilities.py`](probe_capabilities.py), SHA256 `cdfe1c5fa688254b06ddc4bf92e1e7121b77d4d6814978306b8909a1abebf014`.
- Source revision: `49111a15ba372842a3316ae8edcbd59c8807e55e`.
- Fresh child environment used canonical repository, app, engine and evaluations paths; dotenv disabled; cache disabled; campaign free-model admission enabled; exact model for every role; zero-price caps enforced by the existing admission seam.
- Selected cases were `tools,streaming`; no paid fallback or runtime patch was used.

## Exact outcome

| Case | Result | Physical requests | Provider evidence | Stop state |
| --- | --- | ---: | --- | --- |
| `tools` | terminal operational failure | 1 | HTTP 403: `thinkingmachines/inkling:free` is available only on agentic harnesses; failed routing step `Gate Free Endpoints by Agentic Harness` | stopped immediately |
| `streaming` | unavailable | 0 | not attempted after terminal error | unavailable |
| `json_off` / `json_on` / `long_json` | withheld | 0 | exact route does not advertise the required response-format capabilities | unsupported by current route metadata |

The physical request captured model `openrouter/thinkingmachines/inkling:free`, `response_format=null`, and provider controls `max_price.prompt=0`, `max_price.completion=0`, `max_price.request=0`, `require_parameters=true`. No served-model identity or reported usage was returned; usage records one unobserved and unreported physical call. No retry, paid route, provider-key fallback, deterministic substitution or scientific batch was used.

## Process and disposition

- Terminal session: `74255`; launcher PID: `39576`; probe child PID: `39577`.
- Launcher exited `1` after the 403; no process remains. Log: `/private/tmp/inkling-capabilities195.log`.
- Inkling remains capability-unqualified and cannot advance to the scientific panel from this runner. No runtime, PLAN, deployment, schedule or committed source changes were made.
