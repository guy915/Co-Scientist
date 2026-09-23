# Ling 3.0 Flash Sante qualification decision — cycle 195

## Eligibility decision

- **Requested model:** `openrouter/inclusionai/ling-3.0-flash-sante:free`
- Fresh credential-free catalog and exact endpoint receipt: [`ling-eligibility195.json`](ling-eligibility195.json), checked `2026-09-22T12:28:26.892174+00:00`.
- Catalog SHA256: `37b63e5670f95b3526ba65b6d316fd0d184c03460207fb476097a95e7d3b0945`; 444 entries.
- Exact `:free` endpoint returned HTTP 200 with one endpoint and prompt/completion pricing `0`.
- Current catalog and endpoint advertise `tools`, but neither advertises `response_format` or `structured_outputs`; the existing registry path also reports `supports_json_schema_response_format=False`.

## Action and outcome

- **Decision:** `incompatible_for_scientific_probe`.
- The existing capability runner's structured cases require a response-format path that this exact route does not advertise. Running only tools would not establish the structured-output prerequisite for the frozen scientific panel, so no credential was loaded and no inference was attempted.
- No capability process, provider request, retry, paid fallback, runtime patch, scientific trial, or deployment action occurred.

## Remaining steps

- Ling Sante is not eligible for this scientific qualification path under the current public metadata. Reassess only after a fresh catalog/endpoint receipt advertises structured output support or the campaign changes its acceptance gate.
- This cycle added only the Ling eligibility evidence and this summary; no runtime, PLAN, deployment, schedule or committed source changes were made.
