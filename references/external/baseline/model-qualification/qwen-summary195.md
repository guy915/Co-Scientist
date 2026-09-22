# Bounded Qwen json_off retry — cycle 195

## Candidate

- **Requested model:** `openrouter/qwen/qwen3.8-27b:free`
- **Frozen source:** `49111a15ba372842a3316ae8edcbd59c8807e55e`
- **Scope:** one `json_off` capability case through the existing `probe_capabilities.py`; no scientific cases.

## Evidence

- Fresh credential-free catalog and runtime admission were completed before the live request. [`qwen-eligibility195.json`](qwen-eligibility195.json) records the endpoint response, runtime `verify_model()` acceptance, prompt/completion price `0`, and zero preflight provider calls.
- Catalog source: `https://openrouter.ai/api/v1/models`; raw response SHA256 `37b63e5670f95b3526ba65b6d316fd0d184c03460207fb476097a95e7d3b0945`.
- Capability artifact: [`qwen-json-off195.json`](qwen-json-off195.json). Probe SHA256 `cdfe1c5fa688254b06ddc4bf92e1e7121b77d4d6814978306b8909a1abebf014`.
- Runner PTY session: `64819`; started `2026-09-22T12:11:09.190184Z` and exited after the first case. Post-run process inspection found no live qualification runner.
- The launcher used a clean environment, `PYTHON_DOTENV_DISABLED=1`, `COSCIENTIST_REQUIRE_FREE_MODELS=1`, isolated cache paths, the selected Qwen route for every model role, and an in-memory extraction of the existing local OpenRouter credential. The credential was never printed, sourced, or written to artifacts.

## Results

- `json_off`: terminal operational failure on the first physical request.
- Request controls: model `openrouter/qwen/qwen3.8-27b:free`, `max_tokens=6000`, `response_format=json_schema`, and provider caps `max_price.prompt=0`, `max_price.completion=0`, `max_price.request=0` with `require_parameters=true`.
- Error: `RateLimitError` / HTTP `429`; provider metadata identifies `limit_source=upstream_provider_shared_pool`.
- Exact provider hint: `qwen/qwen3.8-27b:free is temporarily rate-limited upstream. Please retry shortly, add your own provider key, or route to another provider with provider routing.`
- Retry state: `max_attempts=1`, observed retries `0`; the run stopped immediately on the terminal 429. No paid route, runtime fallback, timer, or scheduled retry was used.
- Served-model evidence: none. Usage evidence records one unobserved/unreported request, zero completion tokens, zero estimated cost, and no deterministic fallback.

## Remaining

- Qwen remains operationally inconclusive and unqualified. The terminal 429 prevented any successful capability observation.
- The requested bounded advance after a successful json_off was not entered. No further capability cases or scientific trials were launched.
- No source, PLAN, deployment, or memory files were modified.

