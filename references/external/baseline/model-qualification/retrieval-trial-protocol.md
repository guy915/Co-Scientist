# Updated candidate qualification protocol

This comparison qualifies a composite candidate, not the causal effect of the
retrieval change alone. Baseline app/engine revision is
`14e8c59950204c96cdfa2195594885383d1d5720`; candidate app/engine revision is
`94107aedd9c68df9811c69c48b3ac0b7d2ec119f`. Both evaluation subtrees come from
baseline revision `14e8c59950204c96cdfa2195594885383d1d5720`. The evaluator,
challenge inputs and scoring gates therefore remain byte-identical.

`prepare_retrieval_trial.py DESTINATION` creates new snapshots, refuses to
replace an existing destination, verifies every archived Git blob and the
frozen Python/dependency environment, and writes a full source manifest.
The cycle-45 snapshots are at `/tmp/coscientist-retrieval45-reviewed`; their manifest
contains subtree tree IDs and all file hashes. `retrieval-preflight.json`
is reproducible with `preflight_retrieval_trial.py MANIFEST`; it records an offline challenge execution in each snapshot, without credentials,
with dotenv disabled. All imported project source hashes matched the manifest.
This proves compatibility only; its deterministic labels are not live evidence.

Before inference, extend the existing shared probe and comparator, preserving
prior artifacts. Capture every imported app/engine/evaluation module against
its declared subtree revision before requests and at completion. Record the
probe and runner hashes, frozen challenge and historical-control hashes,
runtime identity, fresh catalog evidence and per-request usage. Unknown model,
price or usage evidence cannot support acceptance. Every real request must
carry zero prompt/completion/request price caps and report the selected model.
Do not include controlled synthetic primary responses as physical requests.

Use `openrouter/nex-agi/nex-n2.5-pro:free` only if fresh catalog admission
confirms it remains free. Three new pairs run in order baseline/candidate,
candidate/baseline, baseline/candidate, with existing four-second pacing and
isolated caches. Retain timestamps. A stable route ID does not prove unchanged
hosted weights; counterbalancing reduces but cannot eliminate that limitation.
If configuration changes, rerun both arms. Preserve errors and honor limits.

Each candidate trial must achieve accuracy >= .75 and contradiction recall
>= .80, improve both against its paired baseline, preserve all historical
non-contradiction controls, introduce no new challenge false contradictions,
and record no deterministic fallback. Report item-level flips and other label
regressions as well as per-trial and pooled results. The hybrid control must
force the erroneous markerless primary contradiction and demonstrate a real
secondary verifier request, its negative verdict and actual verification method.
Three small synthetic-panel pairs are qualification evidence, not expert
scientific validation. Prior failed pairs remain failed and are not pooled into
this new series. No model selection or scientific adoption follows from the
offline preflight.
