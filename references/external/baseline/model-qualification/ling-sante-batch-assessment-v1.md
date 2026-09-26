# Ling Sante frozen batch-schema screen

**Disposition:** fails the registered all-three batch gate; candidate remains
open/inconclusive. No citation, usefulness, ranking, default switch, or deployment
is authorized by these results.

The [preregistration](ling-sante-scientific-prereg-v1.json) was committed at
`a12bdd7a` before these calls. Each trial used its own fresh process, the same
four public claims, the same committed assessor, one physical-request ceiling,
and a fresh public catalog/exact-Novita/ZDR admission receipt. The
[trial 1 admission](ling-sante-batch-admission-v1.json),
[trial 2 admission](ling-sante-batch-admission-v1-2.json), and
[trial 3 admission](ling-sante-batch-admission-v1-3.json) each showed zero
prompt/completion prices, an available Novita endpoint, and a ZDR inventory
match. Every request carried Novita-only routing, ZDR, data-collection denial,
and zero prompt/completion/request caps. Each of the three successful physical
responses identified `inclusionai/ling-3.0-flash-sante:free`, reported token
usage and `cost: 0.0`, and showed no deterministic fallback. A cost field is
provider telemetry, not a billing statement.

| Trial | Frozen expected labels | Observed result | Outcome |
| --- | --- | --- | --- |
| [1](ling-sante-batch-v1-1.json) | partial, supports, insufficient, contradicts | All four expected labels, one call | Pass |
| [2](ling-sante-batch-v1-2.json) | Same | First claim `insufficient`; other three expected labels, one call | Completed quality failure |
| [3](ling-sante-batch-v1-3.json) | Same | Primary response again calls first claim `insufficient` and cites a markerless passage for contradiction; local one-call ceiling blocks its verifier/retry | Incomplete, with a repeated raw-response quality failure |

The first claim says compound R reduces lipid accumulation **and** restores
insulin sensitivity in adult hepatocytes. Its public passage reports the lipid
result and says insulin sensitivity was not measured. The frozen label is
`partial`. The retained [Nex Pro trials](batch-context120-acceptance.json) give
that label in all three runs. Trial 2's Ling response cites the supported part
while calling the whole claim `insufficient`; trial 3's primary response repeats
that label. Trial 3 is not a provider outage or 429: the model answered once,
and the local budget refused a second physical call. The `lexical_founded`
method on valid contradiction results is the existing opposition guard's
post-processing of a model draft, also present in the M1 comparator; it is not
a deterministic assessor fallback.

The fixed rule requires all three batch trials to pass before larger panels.
One pass, one completed miss, and one incomplete trial cannot qualify this
configuration. The preregistration calls a mixed series inconclusive and
reserves rejection for repeatable completed failure, so this record does not
rename the candidate as rejected. An independent Luna 6 xhigh audit confirmed
the repeated raw partial-label miss, the trial-3 budget cause, and the
conditional stop. No selective rerun or threshold change was made.
