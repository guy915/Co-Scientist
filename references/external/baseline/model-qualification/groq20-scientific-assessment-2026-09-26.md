# Groq Free GPT-OSS 20B: bounded scientific screen

**Disposition:** rejected for the campaign default on this frozen scientific gate. The completed response did not meet the public four-claim acceptance rule. No larger interface panel or repeat trial is authorized by this result.

## Admission and route

Immediately before the request, the signed-in Groq console showed **Free — Current Plan, $0**, **Inference APIs ZDR Enabled**, and `openai/gpt-oss-20b` in the organization limit table at 30 RPM, 1,000 RPD, 8,000 TPM and 200,000 TPD; the Default Project had no lower custom cap. The campaign key shown in the console was active through 26 October 2026 and matched the protected local mode-0600 key. A read-only Python `urllib` model-list request returned Cloudflare 1010/HTTP 403, but the actual LiteLLM request reached the model and returned a served-model ID. The first launcher attempt failed before import or artifact creation because it omitted `PYTHONPATH`; it made no provider request. These local transport issues do not explain the completed model verdicts.

The [frozen protocol](groq20-scientific-prereg-v1.json) SHA-256 is `f573af52b467a4ac96e0e859dbbbbaa2ffcb1c56ff901c1e28b021c0dbb5cee9`. Source commit `c7d2cbacf0aaff51bd36ddc4ccb3305dc91e8b9d` pins the runner and 15 source/input hashes; protocol commit `7e0f50f2` freezes the panel and one-call cap. Offline policy/runner checks passed 120/120 and the clean, keyless preflight loaded all four fixed claims. The independent review found no one-shot retry, route or fallback blocker for this exact checkout. It noted that a future committed change to an unlisted dependency would need a new freeze; this protocol was used once before any such change.

## Observed result

The [sanitized trial artifact](groq20-science-2026-09-26-1.json) records exactly one physical request, one logical call, `openai/gpt-oss-20b` as the served model, `finish_reason=stop`, and usage of 1,193 prompt + 834 completion = **2,027 tokens**. The response completed without a provider error. Raw and actual-interface labels were `insufficient, supports, insufficient, contradicts`, versus the frozen `partial, supports, insufficient, contradicts`.

The first claim states two effects while its evidence supports only reduced lipid accumulation and explicitly says insulin sensitivity was not measured. The frozen correct label is `partial`; the model returned `insufficient`. For the second, full-support claim, the model returned `supports` but cited the **fourth claim's contradiction passage** as its support. The retained source span is exact for that other passage but is not located in the second claim's own evidence. The fourth claim was correctly labeled `contradicts` with the local `lexical_founded` method and a self-contained negating quote. The first wrong label and cross-claim citation independently fail the preregistered gate; the local parser/guard did not manufacture either raw error.

One completed synthetic panel cannot establish general model quality, and 2,027 tokens cannot establish full-run Free quota fit. The observed failure is sufficient to decline this checkpoint as the campaign default under the declared acceptance rule. No paid route, fallback, retry, production setting, merge or deployment was used for this trial. Explicit user BYOK behavior remains separate.

The provisional 20B policy and one-off runner were removed from the active tree after this failed gate. Their exact test-first source remains recoverable at `c7d2cbac` and the frozen protocol at `7e0f50f2`; neither is a maintained runtime dependency.
