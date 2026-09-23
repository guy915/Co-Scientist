# M1 security review supplement

## Frozen scan

Codex Security scan `37397870-2c59-4fa1-b638-30445fd598f6` completed and sealed on 2026-09-22 for the immutable diff `7dce086dd483831b40a12532a84cf7321f058e52..c3cdef26769aefc4bd877755871473cc7e0b36e8`. Its inventory closed 76 changed-source rows and reported two low-severity, high-confidence PubMed findings: a campaign request could use the MCP process's shared Entrez API key, and the default Entrez path disabled TLS certificate verification. The retained generated report is `security-diff-scan-original196.md`. The scan did not review any later commit, the unrelated working-tree `AGENTS.md` edit, live deployment, or provider traffic.

The two findings describe the **frozen vulnerable revision**; they are not claims that the same code remains vulnerable at `b5d9a70105368a001055cf05ce87efe471518ea8`. The fixes and their behavioral checks are documented in `security-entrez195.md`.

## Later code review

I reviewed the production-source changes in `c3cdef26769aefc4bd877755871473cc7e0b36e8..b5d9a70105368a001055cf05ce87efe471518ea8`, concentrating on all 35 changed non-test files under `app/app`, `engine/src`, `engine/mcp_server`, and `evaluations`. This is a manual supplement, not a second sealed Codex Security scan and not a claim about the 221 other changed files, mostly campaign records and tests. It found no additional reportable vulnerability in the inspected changes; the following are the control paths and remaining proof limits.

| Control path | Source evidence and result |
| --- | --- |
| Entrez TLS | `engine/mcp_server/entrez.py` removed the process-wide unverified HTTPS-context mutation and rejects `DISABLE_SSL_VERIFY=true` before initialization. The old default-unverified path is absent. `test_entrez_campaign_isolation.py` checks both conditions. |
| Entrez shared key | `engine/mcp_server/entrez_rate_limit.py` forces `api_key=None` on each campaign Biopython request and uses anonymous pacing; ordinary requests retain the keyed path. The test intercepts a real constructed request and checks the serialized key is absent. |
| MCP request authority | `auth_middleware.py` accepts campaign header `1` only with the configured matching shared secret, including on the public health route; it scopes the request in a context variable. `mcp_campaign.py` now requires that secret, attaches the campaign header during policy qualification, and still rejects redirects and proxy overrides. Tests cover unauthorized headers and scope reset. |
| Persisted campaign identity | `execution_policy.py` derives campaign status only from a verified bearer principal in the configured researcher set or an already-campaign interview. `runs_crud.py` and `interviews.py` persist it; the schema migration defaults pre-existing rows to `standard`. `engine_tasks.py` restores it from the run on task dispatch. Tests cover forged compatibility identity, restart, BYOK rejection before transport, and separate standard runs. |
| Context isolation | `llm_free_policy.py` makes campaign mode monotone within a context; `async_bridge.py` restores prior context values after thread/loop handoff. `mcp_client.py` keys its cached sessions by event loop, resolved configuration, and campaign state. Tests cover nested disabling attempts and concurrent scopes. |
| Auxiliary inference | Interview, Q&A, announcement, title, restatement, safety, and human-input paths now enter the persisted campaign scope before inference. Campaign BYOK headers are rejected before writes or streaming. The exact Gemma 4 26B free route uses the existing JSON-object shim; this alters format compatibility, not model-price admission. |

`git diff --check` passed for the reviewed source range. Existing targeted tests and the full MCP suite reported in `security-entrez195.md` provide behavioral evidence for the two original fixes. This supplement did not run a new full suite, perform live provider or production tests, inspect secret values, or create a new scan identity. A release review must cover any code committed after `b5d9a701` and confirm the deployed MCP/API configuration and real public-interface behavior; the original sealed scan cannot prove those later states.

The next source edit adds `llm_free_policy.py` and `llm_free_catalog.py` to the
existing policy-hash file list in `evaluations/_comparison_identity.py`, with a
test that compares each saved hash to the actual source bytes. This is an
evaluation-identity correction: it reads local files and adds no network,
credential, authorization, or runtime-request path. The two-file diff was
manually inspected; 21 focused comparison tests passed. It remains outside the
original sealed scan.
