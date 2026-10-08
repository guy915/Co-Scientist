# Azure implementation plan

Azure is the paid fallback after free OpenRouter routes and direct subscriber
API credit. BYOK comes first.
Operator funding covers Express only. Standard and higher tiers require BYOK.
Mistral is dropped. If no route can serve, return "No model is available right now".

W4-1 and W4-2 are merged: roles, bounded effort, exact USD prices and a native
Responses adapter. W4-4 selects it for operator calls. It uses resource
`/openai/v1/responses`, two deployment names and no SDK retries. Unknown paid outcomes are terminal; a failed Azure call ends the chain. JSON, streams, function results and encrypted
reasoning items retain the existing completion contract. Usage stays unknown
when the provider omits it. Hosted paid tools are refused.

W4-3 adds one hard total, `LLM_TOTAL_BUDGET_EUR`. Unset means Azure off.
Reserve upper cost with SR-01 admission before dispatch; settle once after the
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
tokens only; other subscription charges still reduce the owner's credit.

Because the portal omits the expiry time and zone, stop at 00:00 UTC on the
configured expiry date. This avoids using the unconfirmed final day.

W4-4 (implemented, #620) compares run estimates with remaining total. If the estimate does not fit,
do not offer Azure. There is no daily/monthly money cap, spread or carry-forward.
Keep existing per-user/free-run limits. Read `LLM_ENABLED` and
`LLM_AZURE_ENABLED` for every request. Record provider changes in provenance.

W4-5 (#626) removes automatic offline success from product paths. The deterministic
backend stays an explicit test double. W4-6 (#632) adds token-protected spend metrics
and the setup guide. New funding needs one total-variable change, not code.
The admin view has no email or alert.

The owner confirmed Sweden Central Global Standard deployments:
`coscientist-supervisor-luna` (gpt-6-luna, 2026-09-22) and
`coscientist-worker-nano` (gpt-5-nano, 2025-08-07). Credit remaining was
€175.99, with expiry shown as 4 January 2027. Exact expiry time and Luna's
short/long price boundary are unknown. Nano cached input is $0.01/M.
Each deployment has 1,000 TPM / 1 RPM. This cannot fit the existing 18k
reasoning allowance; usable quota remains an owner setup step. No quota is
changed by this implementation. There is no live model quality receipt.

## Validation status

Merged foundations and routing: #455, #468, #522, #533, #577, #592, #607 and #620.
W4-5 is merged as #626. W4-6 is #632; it passed its local source checks;
the local Docker gate stopped at dependency certificate verification. Stock
CI images and exact-head review must pass before merge.
Hermetic receipts are on the campaign board. A live receipt is still required:
9 October allocation 50 requests, $5 subscriber API / €5 Azure, using the local
owner prompt. Default Express uses about 52 completions before Claude count
requests; one full run per provider cannot fit that allocation. Full-run proof
needs a concrete additional allocation before launch. This is not a claim
that deployment, quota or live quality is done.
