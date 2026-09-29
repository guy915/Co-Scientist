# Corrected Space Bunny screen: result

**Classification:** local design choice. **Disposition:** qualified for the fixed scientific and reliability screen. Production-default and full-workflow acceptance remain separate open items.

The [frozen protocol](m12-space-bunny-corrected-screen-2026-09-27.md) ran on committed `6100fd0a`, with product base `c8399332`. [PR #76](https://github.com/guy915/Co-Scientist/pull/76) and the [release receipt](m12-corrected-screen-release-2026-09-29.json) record the published protocol and healthy deployment. Concurrent product changes reached main separately; independent review found no assessor semantic change. The experiment retained its exact tested source.

| Stage/trial | Physical calls | Result |
| --- | ---: | --- |
| Four-claim 1 | 2 | 4/4 exact labels, valid source quotes and offsets |
| Four-claim 2 | 3 | 4/4; bounded retry recovered a misspelled `verderts` field |
| Four-claim 3 | 1 | 4/4 exact labels, valid source quotes and offsets |
| Citation 1 | 65 | 27/30; contradiction recall 0.80; all controls pass |
| Citation 2 | 65 | 28/30; contradiction recall 0.80; all controls pass |
| Citation 3 | 64 | 28/30; contradiction recall 0.80; all controls pass |

All three citation panels had no false contradiction and passed historical, controlled-primary, and both single/batch scope controls. There were no transport errors or deterministic fallbacks. Imported project sources were checked against the frozen manifest. All 200 physical responses identified `stealth/space-bunny-alpha` and reported cost $0. Fresh exact-route pricing admission preceded each trial, requests pinned Stealth with fallback disabled and zero-price limits, and authenticated account usage remained unchanged after every trial. These are observed receipts, not an independent billing audit.

The batch trial-1 launch receipt initially reported an invalid span because its temporary checker required the cited source ID to equal the claim ID. The production batch shares its supplied evidence pool: the cited, same-condition passage said migration decreased, correctly refuting the claim that it increased. The [separate offline audit](baseline/model-qualification/space-bunny-corrected-batch-trial1-provenance-audit-2026-09-29.json) validates the quote against its actual source and offsets. The original receipt remains unchanged; no inference was replayed or threshold relaxed. Independent Luna review confirmed this distinction.

Raw responses, usage, errors, source identity and admission/account receipts are retained as `baseline/model-qualification/space-bunny-corrected-{batch,citation}-trial{1,2,3}-2026-09-29.json` and their `-launch-` counterparts. The earlier failed Space Bunny screen remains negative historical evidence.

These are synthetic public-input results, not external-literature verification, expert validation or evidence of Google's private implementation. Recheck pricing before further calls. Next: verify production defaults and a bounded deployed research flow under M12-04b2; no default has been changed by this result.
