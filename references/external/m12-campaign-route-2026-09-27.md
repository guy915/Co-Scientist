# Campaign-only Space Bunny route

**Local design choice.** The owner selected `openrouter/stealth/space-bunny-alpha`
for controlled campaign use after its [single completed local public run](m12-space-bunny-full-run-assessment-2026-09-27.md).
Public-input retention is not a selection constraint. One completion establishes
operational compatibility, not repeat-run reliability or scientific quality.

New runs created by a verified campaign bearer persist the server-selected
`campaign_model_name` in run config. The [execution policy](../../app/app/execution_policy.py)
scopes that saved route around each durable task. [Generator construction](../../app/app/engine_adapter/opts.py)
uses it for worker and supervisor calls; [app credential resolution](../../app/app/credentials.py)
uses it before shaping auxiliary requests. [Checkpoint restore](../../app/app/engine_adapter/checkpoints.py)
reapplies it so recovery and Robin targeted evolution cannot inherit an older
checkpoint model. Interview streams select the same route before run creation.
Standard and BYOK runs, and legacy campaign runs without the saved route, retain
their prior model and credential behavior.

The [recovered-task regression](../../app/tests/test_campaign_policy_integration.py)
captures one request through the actual LLM boundary with a mocked provider. It
asserts the selected model, zero prompt/completion/request price caps,
Stealth-only provider pin, and disabled provider fallback. The
[campaign-route tests](../../app/tests/test_campaign_model_route.py) cover
creation, interview and chat, generator roles, safety, claim assessment, and
legacy recovery. The [Robin test](../../app/tests/test_campaign_robin_refinement.py)
checks the restored targeted-evolution model. These are offline checks; actual
served-model and account-cost evidence belongs to the production run item.

Production role environment values remain unread because automatic approval
review rejected that read. This route does not require or reveal them. The
existing [fresh zero-price admission](../../engine/src/co_scientist/llm_free_policy.py)
and [Stealth pin](../../engine/src/co_scientist/llm_gateway_routing.py)
still fail closed before transport if current metadata does not qualify.

## Verification

The first route test failed before implementation because campaign run config
had no saved model. The first full suite exposed a legacy-campaign BYOK recovery
regression, which was fixed without changing the existing assertions. A later
file-length check caught a test module over 500 lines; the new Robin regression
was moved to its own module. On the final code, `make test-all` passed (3,166
engine tests, 2,024 app tests, 312 MCP tests, and parity), as did `make lint`,
`make typecheck`, `make build`, `make eval-smoke`, frontend `bun run test` (803),
and `make e2e` (18). The frontend suite ran before the final test-only file move;
frontend source, dependencies, and evaluation inputs did not change. The final
code-bearing checks ran locally without a provider key or production mutation.
