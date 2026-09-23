# Guarded public retrieval — 2026-09-19

Live local verification of PubMed, Europe PMC and OpenAlex through the existing
engine MCP client and current reference server. This is retrieval evidence, not
model inference, scientific-quality evaluation or production acceptance.

- Initial revision: `3bd227580f7cff2405905209c12307584d9fe29f`.
- Corrected PubMed availability: `566660cc` (same retrieval implementation).
- Endpoint: `http://127.0.0.1:8898/mcp`, explicitly campaign-qualified.
- Each search was capped at one record. All three returned the expected DOI
  `10.1126/science.1225829`, source identifiers and nonempty abstract text.
- Europe PMC used the model-shaped `execute_tool_call` envelope; PubMed and
  OpenAlex used `call_tool`. No LLM supplied the calls.
- The original PubMed probe returned false despite successful retrieval. After
  correction and server restart it returned true. `search_web` was rejected.
- No HTTP 429 was observed; no deliberate quota exhaustion or paid retry occurred.

`evidence.json` retains exact results, durations, isolation conditions, abstract
hashes and post-fix checks. `server-policy.json` is the observed serving manifest.
`source-requests.txt` contains filtered public source request/status diagnostics.
`probe.py` is the exact initial experiment script, retained as evidence rather
than a general evaluation runner; it writes to the temporary directory below.

Both processes used `env -i`, `PATH=/usr/bin:/bin`, a temporary HOME,
`PYTHON_DOTENV_DISABLED=1`, and `COSCIENTIST_REQUIRE_FREE_MODELS=1`. No API keys,
contact email, proxy settings, private documents or production-run data were
passed. Caches and literature output were under
`/tmp/coscientist-campaign-retrieval/`. Start the server from `engine/` with
`.venv-mcp`'s Python running `uvicorn mcp_server.server:app --host 127.0.0.1
--port 8898`; the client uses root `.venv` and sets
`COSCIENTIST_CAMPAIGN_MCP_URL` to the endpoint above. Use absolute interpreter
paths because the isolated PATH intentionally excludes development tools.

Limits: the three-source success path is verified, not every exposed database
connector. The subsequent M1-03c3b correction distinguishes Europe PMC service errors
from empty results; see [fault-injection evidence](../europepmc-errors-2026-09-19.json). Model selection, full workflow, rate-limit
recovery and production release remain separate acceptance work.
