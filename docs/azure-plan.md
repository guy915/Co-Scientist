# Azure implementation plan

Azure is the paid fallback after free OpenRouter routes and direct subscriber
API credit. BYOK comes first.
Operator funding covers Express only. Standard and higher tiers require BYOK.
Mistral is dropped. If no route can serve, return "No model is available right now".

Roles, bounded effort, exact USD prices and a native Responses adapter are in
place, and operator calls select it. It uses resource
`/openai/v1/responses`, two deployment names and no SDK retries. Unknown paid outcomes are terminal; a failed Azure call ends the chain. JSON, streams, function results and encrypted
reasoning items retain the existing completion contract. Usage stays unknown
when the provider omits it. Hosted paid tools are refused.

One hard total applies, `LLM_TOTAL_BUDGET_EUR`. Unset means Azure off.
Reserve upper cost with durable admission before dispatch; settle once after the
call in a short transaction. Missing usage, failure, interruption or restart
keeps the reservation. No writer spans network work. Convert USD prices with
`LLM_USD_TO_EUR=0.88`. Stop Azure after `LLM_AZURE_UNTIL`.

The guard uses integer micro-EUR and snapshots FX/rates for each reservation.
Paid transactions sync the reservation before dispatch. Native calls recheck
kill switches, expiry and the process spend hold after any thread wait.
Until Luna's price boundary is known, charge at the higher long-context rate.
Reserve input bytes plus the framing allowance, the full output allowance and
up to four cache-write prefixes. Missing Luna cache-write usage keeps the full
money reservation. Reported reasoning stays within output tokens. Settlement
failure keeps all reservations and stops new paid calls. Prices cover model
tokens only; other subscription charges still reduce the subscription credit.

Because the portal omits the expiry time and zone, stop at 00:00 UTC on the
configured expiry date. This avoids using the unconfirmed final day.

Admission compares run estimates with remaining total. If the estimate does not fit,
do not offer Azure. There is no daily/monthly money cap, spread or carry-forward.
Keep existing per-user/free-run limits. Read `LLM_ENABLED` and
`LLM_AZURE_ENABLED` for every request. Record provider changes in provenance.

Product paths never fall back to automatic offline success. The deterministic
backend stays an explicit test double. Spend metrics are token-protected, and
[Azure setup](azure-setup.md) is the setup guide. New funding needs one
total-variable change, not code.
The admin view has no email or alert.

The reference deployments are Sweden Central Global Standard:
`coscientist-supervisor-luna` (gpt-6-luna, 2026-09-22) and
`coscientist-worker-nano` (gpt-5-nano, 2025-08-07). Remaining provider credits
and their expiry come from the portal. Exact expiry time and Luna's
short/long price boundary are unknown. Nano cached input is $0.01/M.
Each deployment has 1,000 TPM / 1 RPM. This cannot fit the existing 18k
reasoning allowance; usable quota is an operator setup step. No quota is
changed by this implementation. There is no live model quality receipt.

## Validation status

Hermetic tests cover the guard, admission and settlement. Live quality and
full-run cost on Azure are not yet measured; this plan does not claim that
deployment, quota or live quality is done.
