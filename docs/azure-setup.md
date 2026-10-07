# Azure setup checklist for Guy

Owner clicks only. This checklist accompanies [azure-plan.md](azure-plan.md).
Do not paste keys into chat, GitHub, screenshots, shell history or repository
files. Guy requested research only: this readiness lane makes no model calls.
Do not send a playground prompt. The two-call protocol in the plan is suspended
until a later explicit authorization.

## Select the project and verify billing

1. Open [Azure portal](https://portal.azure.com/), sign in with your account and
   select **Default Directory (guybarel2006gmail.onmicrosoft.com)** through the
   directory/subscription filter.
2. Search **Subscriptions**, open **Azure subscription 1**, and verify the ID
   ends `181e1dfbb5b3`. Under its billing overview, verify startup credit is
   attached, read the **remaining balance** and precise expiry timestamp/timezone,
   and verify the reported 4 January 2027 date. These are your reported account
   details; this lane has not inspected them. Record only non-secret billing
   metadata; the plan's €175.99 assumption must be replaced if already consumed.
3. Open [Foundry](https://ai.azure.com/), use the project selector and open
   **guybarel2006-4361**. Verify its parent resource uses that subscription. Record
   parent resource name and region privately. If the project does not appear,
   check directory and project selection before creating another resource.

## Create Luna and Nano deployments

The sequence below uses Foundry classic's documented deployment controls. If
you see the **New Foundry** toggle, switch it **off** to use these labels.
In an existing Foundry project the left navigation calls the list **Models +
endpoints**; an Azure OpenAI resource can call it **Deployments**, under Shared
resources. These are alternative portal views of deployments, not API endpoints.
[Microsoft's deployment checklist](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource?pivots=web-portal).

1. In the project, open **Model catalog**, choose the **Direct from Azure**
   collection, search **gpt-6-luna**, and open its card. Verify OpenAI publisher,
   Azure-direct billing and version **2026-09-22**. The same catalog selection can
   be opened through **Models + endpoints → + Deploy model → Deploy base model**.
2. Open **Pricing** or **View pricing**. Select **Global Standard** and USD;
   verify short rates $0.10/$0.01/$0.125/$0.50 per million for
   input/read/write/output and the long-context rates. Record any account-specific
   difference and the displayed context-price boundary, not a key.
3. Select **Deploy** (or **Confirm** after selecting the base model). Choose the
   existing project/resource, name the deployment **coscientist-supervisor-luna**,
   choose **Global Standard**, and pin the displayed version where the portal
   allows it. Keep the default content filter; do not opt into paid hosted tools.
4. Expand **Deployment details / Advanced options**. Set **Tokens per Minute
   Rate Limit** to the smallest nonzero allocation the portal accepts for the
   deployment preparation, and leave **Dynamic quota** off. Read the displayed **RPM** too.
   The selectable minimum is not yet confirmed. Do not allocate the entire
   subscription quota or request an increase merely to create this test.
5. Verify the billing/deployment summary is Azure-direct **Global Standard**,
   then click **Deploy**. Wait until provisioning is **Succeeded**. Do not click
   **Open in playground** or submit a prompt.
6. Repeat steps 1–5 for **gpt-5-nano**, version **2025-08-07**, deployment name
   **coscientist-worker-nano**. Verify $0.05 input/$0.005 cached/$0.40 output per
   million. Nano has no extra cache-write fee. Use the same parent resource so
   both share one resource endpoint/key.
7. In **Models + endpoints**, open each row and record non-secret deployment
   name, model/version, resource region, type, TPM and RPM. Deployment names go
   into API `model`; the project name does not.

If either model is missing or quota is zero, stop before deploying a substitute.
Report model, region, type and the non-secret error. Availability and this new
subscription's tier are unconfirmed. Do not accept Marketplace terms, switch to
Provisioned/Batch or create another paid service to work around it.

For Foundry **new**, the documented quota path is project selector → **Manage**
(upper right) → **Quota** → **Token per minute** → deployment → **Affiliated
deployments using shared quota** → pencil in **Actions**. Verify the saved value
after propagation (up to 15 minutes). For classic, use **Management center →
Quota**, filter subscription/resource region and model, then the deployment edit
control. Do not click **Request quota** unless a later owner decision requires it.
[Quota management](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota).

**Low quota is not a credit-runway hard cap.** If the minimum is 1,000 TPM per model,
their short output prices alone permit $38.88 over 30 days. Normal research's
output floor also exceeds 1k TPM. The later lane must first implement the ledger,
then propose usable request limits and exact quota arithmetic for your budget.
Your chosen objective is to use remaining credit evenly by January 4. Assuming
€175.99 remains on October 7 and January 4 is inclusive, the plan allocates
€48.88 for October 7–31, €58.66 November, €60.62 December and €7.83 January 1–4:
about €1.96/day. Unused allowance carries forward within the total. These are
future backend limits, not settings applied here. The €1 email alert remains
useful as an early warning.

## Find endpoint and key; export locally

1. Open a deployment's **Details**, then its sample-code view, choosing
   **Responses** with API-key authentication. Find the parent resource link.
   Alternatively, in Azure portal open that resource → **Resource Management →
   Keys and Endpoint**. Read the **Azure OpenAI** resource endpoint and **Key 1**.
   Never send the key or a screenshot containing it.
2. Use a resource origin such as
   `https://<resource>.openai.azure.com` (or the documented
   `https://<resource>.services.ai.azure.com`). The Responses adapter appends
   `/openai/v1/`. Do not use the Foundry project URL containing
   `/api/projects/guybarel2006-4361` as the OpenAI endpoint.
   [Responses endpoint documentation](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses).
3. Export into the shell accessible to this readiness session, not only an
   unrelated local terminal. The following shell snippet prompts without echo
   and stores no literal secret in command history; enter the endpoint/key at
   the prompts. Disable shell tracing first. Never run `env`/`printenv` afterward.

   ```bash
   set +x
   read -r -p 'Azure OpenAI resource endpoint: ' AZURE_OPENAI_ENDPOINT
   export AZURE_OPENAI_ENDPOINT
   read -r -s -p 'Azure OpenAI key (hidden): ' AZURE_OPENAI_API_KEY
   printf '\n'
   export AZURE_OPENAI_API_KEY
   export AZURE_OPENAI_API_VERSION=v1
   export AZURE_OPENAI_SUPERVISOR_DEPLOYMENT=coscientist-supervisor-luna
   export AZURE_OPENAI_WORKER_DEPLOYMENT=coscientist-worker-nano
   ```

4. For a later explicitly authorized test, confirm in chat only that both deployments succeeded and the two required
   variables are exported in this session. Include deployment names and TPM/RPM
   if they differ; never the key. If the session cannot access your exports,
   keep the test pending rather than pasting a credential.

The v1 API does not use a dated `api-version` query; `v1` is the planned validated
configuration. [Version lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle).
A later test may follow the plan's two direct calls, once each, and report only
usage, status, reasoning fields and latency. Twenty tokens includes reasoning
and may return an incomplete response without visible text. Exporting variables
does not authorize a call under the current research-only instruction.

## Verify or set the email budget alert

You reported **monthly-1-eur-alert** already exists. Inspect it first; do not
create a duplicate.

1. In [Azure portal](https://portal.azure.com/), search **Cost Management +
   Billing**, open **Cost Management**, then **Budgets**.
2. Select **Scope** and choose **Azure subscription 1**, confirming the ID
   suffix. Keep subscription-wide coverage so other resource usage is visible.
3. Open **monthly-1-eur-alert** → **Edit**. If absent, choose **+ Add**, enter
   that name, **Monthly** reset, a valid start/end date, and **Budget amount 1**.
   Check the displayed currency is **EUR**; if it is USD, this is not the same
   €1 alert and the account billing currency must be resolved.
4. Select **Next / Set alerts**, add **Actual** thresholds at **50%, 80%, 100%**,
   and **Forecasted 100%** if available. Enter your email as recipient in the
   portal. Do not attach an automation/action group that changes hosting.
5. Select **Create / Save** and verify the name, amount, currency, scope,
   dates and recipients. Existing configured thresholds can remain if they
   provide the same requested warning.

This is email-only. Cost evaluation has delay, and it never refuses model calls.
The backend ledger is the future hard cap.
[Microsoft budget tutorial](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

## Check credit billing the next day

1. The day after any separately authorized first usage, open subscription **Cost Management → Cost
   analysis**, set the date range to include the test day and the same scope.
2. Filter/group by the parent Foundry/Azure OpenAI resource, **Service name** and
   **Meter**. Inspect Azure-native model input/output/cache usage, not Marketplace
   invoices. Depending on the view, use usage details/download to see small
   quantities that the chart rounds away.
3. Open the subscription billing-credit view (or the sponsorship balance linked
   from your startup benefits) and verify the usage drew from startup credit.
   Resource cost by itself does not prove which balance paid it. If unclear,
   keep the result unconfirmed and ask Azure billing support; no extra paid test.
4. Record only date, model meter/funding result and whether credit coverage was
   observed on the board. Tiny charges can round to zero and ingestion can lag;
   an absent entry is inconclusive. Recheck the same existing usage later.

Policy coverage is confirmed for Direct from Azure models; this account's actual
debit remains unconfirmed until observed.
[Sponsorship policy](https://learn.microsoft.com/en-us/startups/benefits/technical-benefits/azure-credits/foundry-model-sponsorship-coverage).

Before the later rollout, recalculate the dated monthly/daily backend budgets
from remaining credit minus other Azure charges, remaining valid days and
conservative FX/tax headroom. Keep Azure disabled until hard-cap tests pass.
Credit expires 4 January 2027 according to your brief: the backend must stop paid
Azure dispatch by the actual cutoff or credit exhaustion. Continuing on the card
requires a separate owner-approved budget.
