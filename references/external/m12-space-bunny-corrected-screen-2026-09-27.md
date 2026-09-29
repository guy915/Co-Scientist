# Corrected Space Bunny scientific screen

**Classification:** local design choice. **Status:** frozen before candidate inference. This is a new screen of the released, general batch-schema correction; it does not overwrite or reinterpret the failed [earlier Space Bunny trials](m12-space-bunny-scientific-result-2026-09-27.md). A pass would establish only the declared fixed-input gates, not expert or wet-lab validation or knowledge of Google's private implementation.

## Fixed product, route, and inputs

The product base is [PR #73](https://github.com/guy915/Co-Scientist/pull/73), merged as `c8399332368d730ba367208db416f3e5797462cc` and observed healthy on all existing services. The comparison launch must use a committed descendant containing only the bounded probe and protocol changes. `QUALIFICATION_REVISION` must equal that exact launch `git HEAD`; launch receipts record both it and the released product base. If production assessor behavior changes, stop and freeze a new protocol before further calls.

| Fixed component | SHA-256 |
| --- | --- |
| `app/app/claim_verifier_batch.py` | `c5de81a34b3c9c378e8738dcf54f5bd6fd7cf01d72179afbb23c0dae8e2c1884` |
| `app/app/claims_batch.py` | `296778b93db6a3445cf319ce519881e39ca12a4c3be079fb2742ae0b715e1b91` |
| `app/app/claim_verifier.py` | `a1f15992cf4e554e4876f5704dc7830a5b495862e20af9df08c692fe87cfc7de` |
| `app/app/claim_verifier_opposition.py` | `98bdf1d77452f7bf1288ae110423027b79e3bf1a965ab12ab76846d07fff7281` |
| `app/app/claims_assessor.py` | `4269496be5aecdedc017e8465729706d710d99e5df93393922f8b830ee4d56b5` |
| `app/app/claims_span.py` | `d464733cc5c90c2a3c296f1398a6790b982530f27ae797dfc83f202c7ad36ee0` |
| `app/app/claims_gate.py` | `0d09de7be5dbd67da0fb6c80e4e1232dc73fd6b2303d2f9aa7be9f3b41c7dd20` |
| `engine/src/co_scientist/llm.py` | `1cec1a98c9cb688168c93e207c87fb433da54d5aaf5e987cd1e4fd331ab83d40` |
| Four-claim public input `partial-support-scope-controls.json` | `f5e70ede3f73549e071e21579d3e7d41dac8afdf815443be51037a4b21696015` |
| New immutable `batch-schema-preflight110.json` | `46da64915fcd6498da50dc313405a12329676c7aca98ad67a0f1e2a25a3475ec` |
| Required batch schema, canonical sorted JSON | `7bcf977830ae6550db977b4dc8a392ee80bc8f35ddd47fb1ee09e937b430367c` |
| New `probe_batch_schema.py` | `b4a8db3a4e8f8fadd9945413d2b7d884835d247473f7ea8597363cb7d693bb69` |
| 30-item public input `citation_entailment_challenge_v1.json` | `1636ddcfb94084ccabe5f155fd5701c3270c7ffc751e1c16a6450cece61c39f2` |
| `evaluations/citation_eval.py` | `da331d808fa75e7161a364814ead894c4978c724f5a0cebb44582449618fa8ee` |
| `probe_citation_panel.py` | `a8c9b650837f71531b84ec3aaff2b63b53d01e7679f68d17d0adb941838d5b23` |
| Citation source manifest `space-bunny-corrected-current-sources-2026-09-29.json` | `fea49dcea703b62f0dd8f7e80f23f7a107f092eeb55a600658673f67b945975f` |
| `qualification_sources.py` | `64edc5d5f57f6594ea0cdf9836c9a9a302a21b51e18faa0ccc1c76c04541238c` |
| `historical-negative-controls.json` | `2c226b079f5337b76919a842245744b429fbb76d78cc4ff70661b94f1300ec3a` |
| `scope_controls.py` | `e059c65dda9c0cd69cf55b86725e695aa03f2e70270cae7204f28897db1db6de` |
| `evaluations/_panel_identity.py` | `8b152590bfc5db2a4970c040bbc7d90d75fc0771568eff7707f05ae9d535daef` |
| `evaluations/_comparison_identity.py` | `43e0d145b5088a256b92936915d772b1377479e533dff9ea52eb3b955e5bfbdd` |
| `evaluations/_usage_evidence.py` | `805f5fc6210e4111d1f40fbe41317d6a0c87eae6e3ebd46531f483d473c5e37a` |

Use the exact `openrouter/stealth/space-bunny-alpha` model via **Stealth only**, with fallback disabled, required parameters and zero prompt/completion price ceilings. Keep the released product's request shaping, JSON-object response format, bounded validation-feedback retry, and reasoning/token settings unchanged across trials. The first prior observed physical request used `max_tokens=18000` and `reasoning.enabled=true, max_tokens=2048`; verify each new request against the released policy. Only the product's existing validation-feedback or budget-escalation retry may change a prompt or request setting, and every such change must be retained in telemetry. Do not add paid tools, embeddings, auxiliary models or alternate credentials. Public research inputs alone may be sent; the owner waived data-retention restrictions, not the zero-spend rule.

## Admission and observed cost

Immediately before each live trial, check the [official model page](https://openrouter.ai/stealth/space-bunny-alpha), [billing FAQ](https://openrouter.ai/support/), current catalog and exact [endpoint API](https://openrouter.ai/api/v1/models/stealth/space-bunny-alpha/endpoints). Require the exact Stealth endpoint to advertise zero prompt and completion prices, the model to remain explicitly free, and no chargeable request path under the published billing terms. Unknown or conflicting prices stop before inference. The request guard must reject nonzero prices, pin Stealth, disable fallback, and send zero price ceilings. `max_price.request=0` is recorded but is **not** treated as a documented fixed-fee guarantee. Authenticate read-only, snapshot account usage before and after every trial, and retain provider-reported per-request cost and served model. If any usage/cost cannot be observed or is nonzero, stop. A zero internal estimate alone is insufficient billing evidence.

## Prespecified sequence and gates

Use `COSCIENTIST_LLM_TIMEOUT_SECONDS=60` for every comparison process. Bound the entire four-claim process at 240 seconds and each 30-item process at 720 seconds. These are experiment limits, with no production timeout change. Any provider timeout or killed process is an unavailable/ambiguous outcome and stops the series without replay. Record the timeout setting and process limit in each launch receipt.

1. In three fresh processes with caches disabled, run the four claims selected by preflight110 in one batch invocation per trial. Permit **at most three physical provider requests per trial** so the corrected schema retry can operate; record every attempt, including malformed content, errors, usage and validation feedback. The primary scientific metric is exact gold-label agreement: all four must be `partial`, `supports`, `insufficient`, `contradicts` in the frozen order. Each supporting or contradicting span must cite its own public source, quote text actually present there, and report valid offsets; no deterministic fallback is accepted. Correct final labels after a bounded schema repair count as recovery, but do not erase the malformed first response. All three trials must pass independently; one pass does not establish reliability.
2. Only after all three pass, run three fresh-process, cache-isolated 30-item citation trials through the existing evaluator and historical, controlled-primary and scope controls. The runner's shared physical-request ceiling is **80 per trial across phases**. Each trial must score at least **27/30** exact gold judgments, contradiction recall at least **0.80**, no new false contradiction, and pass all existing controls without deterministic fallback. Use identical model, evaluator, gold inputs, and request policy for every trial.

Stop the entire selected-route series on the **first failed or unavailable trial**, price or served-route mismatch, missing telemetry, nonzero cost, safety issue, terminal transport error, ambiguous accepted request, or rate limit. Do not reissue an ambiguous request, selectively replay a bad trial, wait/poll an unresponsive provider, substitute a paid route, or loosen a threshold. For the citation stage, set `QUALIFICATION_MANIFEST` to the pinned source manifest, `QUALIFICATION_ARM=current`, `QUALIFICATION_CONTROLS` to the pinned historical controls, and `QUALIFICATION_SCOPE_CONTROLS` to the same pinned scope input. The existing imported-source guard must validate every loaded project module before each live request. Retain unique raw artifacts and a concise result record even on failure; the old failed screen stays negative evidence. A transport recovery inside the bounded product retry must be recorded as an operational defect and stops progression after that trial. If the route fails, assess a *distinct* candidate under a new frozen protocol; do not mark the unqualified route as a product default.
