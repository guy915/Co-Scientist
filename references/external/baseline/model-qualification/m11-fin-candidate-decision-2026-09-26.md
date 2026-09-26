# M11 exact-zero replacement after Ling Sante's failed batch gate

**Classification:** local model-selection decision, not Google-backed behavior.
**Decision:** investigate `openrouter/inclusionai/ling-3.0-flash-fin:free` on
Novita as a provisional, bounded candidate. It is not a default, fallback,
or scientific-quality result. Do not run inference until the exact adapter,
input, code, and rubric hashes are frozen in a committed protocol.

The [fresh official catalog/endpoint/ZDR screen](m11-free-route-post-ling-screen-2026-09-26.json)
used the project's `verify_model` policy for every listed `:free` text route,
then checked each exact endpoint's status and zero prompt/completion prices
against OpenRouter's [ZDR inventory](https://openrouter.ai/api/v1/endpoints/zdr).
Seventeen catalog routes met the project admission policy; only three had a
currently available exact-zero endpoint in that inventory. Nex Pro was absent
from the catalog, while the [sanitized Railway production role readback](m11-production-model-roles-2026-09-26.json)
still names it. That is a release risk, not authority to use an unqualified or
paid route.

| Route | Current evidence | Decision |
| --- | --- | --- |
| Qwen3.8 27B / ModelRun | Exact-zero, ZDR, tools and native structured output; the retained [26 September request](qwen-m11-capabilities-2026-09-26.json) returned an upstream shared-pool 429 before model/usage evidence. | Keep open. Endpoint status metadata does not prove inference capacity; do not timer-retry a saturated pool. |
| Ling Sante / Novita | Exact-zero, ZDR and tools; prompt-only adapter passed synthetic interfaces, but the [frozen batch screen](ling-sante-batch-assessment-v1.md) did not qualify. | Keep open/inconclusive under its frozen rule; no selective rerun. |
| Ling Fin / Novita | Exact-zero, ZDR, tools and 262,144-token context; no native `response_format` or `structured_outputs`. | Test the same local prompt-schema mechanism as a **new model route** under a separately frozen protocol. |

Ling Fin is finance-enhanced and shares Ling Sante's base family, so it is not
an independent architecture. Its [publisher model card](https://huggingface.co/inclusionAI/Ling-3.0-flash-Fin-fp4)
reports GPQA Diamond and SciCode results for named quantizations; those
publisher-reported scores do not identify or validate OpenRouter's exact
Novita endpoint or this product's claim-evidence behavior. The finance tuning
could help or hurt. Its only concrete advantage over another Sante rerun is
that it is a distinct checkpoint with a currently listed, available-status
zero-price ZDR endpoint; actual inference capacity remains unproven. Qwen
would be technically simpler if its upstream pool becomes usable.

The bounded sequence is fixed before any Fin request:

1. Red-first request-boundary tests add only the exact Fin route to the
   existing prompt-schema, Novita pin, ZDR/data-denial and zero-price path.
   Preserve explicit BYOK behavior. Run affected offline checks, then commit
   final code/input/config hashes and the physical-call protocol.
2. Recheck catalog, exact endpoint, ZDR and applicable zero prices. Through
   the existing capability runner, test schema JSON with thinking off/on,
   unschemaed JSON, one synthetic tool round trip, streaming, and a long
   prompt. Limit the whole panel to seven physical requests (one per case,
   two for the tool exchange); stop on the first failed case or terminal
   error. Require the requested and served model, usage, zero-price controls
   and no unapproved fallback.
3. Only if interfaces pass, run the same frozen four-claim batch screen in
   three fresh processes against the retained M1 public inputs. Require all
   four exact labels and grounded quotes in every trial, with one physical
   request per trial; preserve failures and stop larger panels if this gate
   fails. The conditional 30-item citation, usefulness and ranking panels
   retain the preregistered Ling Sante/M1 public inputs, class floors,
   three-trial rule, and hard physical-call caps of 80/20/60 respectively.
   A changed rubric requires a committed amendment and a new full series.

Successful synthetic cases only justify the next stage. Selection and any
deployment still require scientific non-regression, a real public workflow,
the campaign's release checks and verified serving configuration. No private
documents, paid provider route or production setting may enter this screen.

An independent read-only Antigravity Gemini 3.8 Flash High analysis of the
three Sante artifacts found the project parser and opposition guard behaving
as designed; the raw model answers in trials 2 and 3 made the partial-label
error. A Luna 6 xhigh read-only route review independently identified Fin as
the only other available exact-zero ZDR route after Qwen's 429 and Sante's
quality miss. Neither peer ran inference or changed the repository.
