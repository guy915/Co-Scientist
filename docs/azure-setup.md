# Operator model credit setup

Order: BYOK → free OpenRouter → direct Haiku subscriber credit → Azure →
"No model is available right now". Operator runs are Express only; Standard and
higher tiers require BYOK. No Mistral slot remains.

## Portal steps

1. Claim the subscriber credit on claude.ai and link Console organization
   **Open Co-Scientist**. Confirm the organization before linking; self-service
   cannot change that link. Create workspace **Open Co-Scientist** and an API key
   there. Set `ANTHROPIC_API_KEY` on the API service only. Every key and workspace
   in the organization shares its credit.
2. In Azure AI Foundry, confirm Global Standard deployments in Sweden Central:
   `coscientist-supervisor-luna`, gpt-6-luna `2026-09-22`, and
   `coscientist-worker-nano`, gpt-5-nano `2025-08-07`. Use the resource HTTPS
   endpoint, not a deployment URL. Set the five variables below on the API only.
3. Read current remaining credit and expiry in the portal. Set
   `LLM_TOTAL_BUDGET_EUR` to the remaining amount after allowing for other
   subscription charges, and confirm the date.
   Azure has no hard subscription cap; excess spend is billed to the subscription.
4. Size TPM/RPM for the capped requests and Express concurrency within that
   total. The current 1,000 TPM / 1 RPM per deployment is too small for the
   existing prompts/output allowances. Confirm quota before enabling Azure.
5. Open `/operations/spend` with the logs-admin token and test the kill switches
   and refusal path. Enable Azure only after the bounded live checks pass.

## API settings

| Setting | Value or default |
|---|---|
| `LLM_ENABLED` | `true`; false stops all model dispatch |
| `LLM_AZURE_ENABLED` | `false` until the operator enables it |
| `LLM_TOTAL_BUDGET_EUR` | unset = Azure off; set fresh remaining credit |
| `LLM_AZURE_UNTIL` | ISO date; stop at its UTC start, even after new funding |
| `LLM_USD_TO_EUR` | `0.88` |
| `AZURE_OPENAI_API_KEY` | secret, API service only |
| `AZURE_OPENAI_ENDPOINT` | resource HTTPS origin `https://<resource>` + `.openai.azure.com`, `.services.ai.azure.com` or `.cognitiveservices.azure.com`; no path, port or query |
| `AZURE_OPENAI_API_VERSION` | `v1` |
| `AZURE_OPENAI_SUPERVISOR_DEPLOYMENT` | `coscientist-supervisor-luna` |
| `AZURE_OPENAI_WORKER_DEPLOYMENT` | `coscientist-worker-nano` |
| `ANTHROPIC_MONTHLY_CREDIT_USD` | `100` |
| `ANTHROPIC_BILLING_RESET_DAY` | `7`; UTC boundary |
| `LLM_OPENROUTER_CALLS_PER_DAY` | `1000`; free route requests only |
| `LOGS_ADMIN_TOKEN` | secret for private logs, control and spend views |

There is no daily/monthly EUR budget, even spread or carry-forward. New funding
needs only a higher `LLM_TOTAL_BUDGET_EUR` value; no code change. Expiry still
applies. Both kill switches are read at each dispatch. Never raise per-user,
host, global, app or concurrency limits to make a model run finish.

The shared physical-call default is 1024/day; the free-route default is
1000/day. After 1000 free calls, only 24 shared calls remain for credit slots.
The Express forecast allows 57 calls before fallbacks. Choose a lower
`LLM_OPENROUTER_CALLS_PER_DAY` if credit slots need more headroom. Keep the shared ceiling and per-user limits unchanged.

A run estimate must fit the remaining total before Azure is offered. The
forecast is held, converted into actual call reservations, and released when
work ends. Real priced usage settles once after the reply. Missing usage,
failed calls and unknown outcomes keep the full reservation across restart.
No database writer spans network I/O. Known cache reads/writes use saved USD
prices and FX; reasoning is already part of output tokens.

The private view shows today/week UTC spend, total, unknown call holds, run
forecasts, remaining capacity, seven-day EUR/day and days at that rate. It also
shows subscriber USD spend, credit and the usable 95% allowance. These are local
ledger figures, not provider-balance queries. Free routes add no money spend.
There is no spend email or alert. Quota/reset failures go to the next slot;
a Haiku refusal goes to Azure for that call. Nothing follows Azure.

Keep `COSCIENTIST_TEST_DOUBLE` unset on public services. Deterministic responses
are available only through that explicit private test adapter. Missing provider
keys return an honest error.
