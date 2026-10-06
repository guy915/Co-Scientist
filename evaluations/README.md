# Evaluations

Reproducible evaluation harness for research experiments. Everything here runs **offline** (no LLM, no network) unless a runner
explicitly says otherwise; machine-readable results are written under
`results/`. Historical receipts are retained in the
[pinned results tree](https://github.com/guy915/Co-Scientist/tree/7c2878aeb071a962cb713e9c271cd88e1635ca5f/evaluations/results);
the offline baseline remains local.

## Layout

- `_artifacts.py` — shared result-artifact writer. Every artifact any runner
  writes through it is stamped with a `provenance` block (source git
  commit/branch/dirty, python/platform environment, a digest over the
  engine's prompt templates, and whatever the runner knows about the model,
  seed, and cost of its own measurement) automatically, so a result found
  later carries what produced it rather than depending on memory.
- `citation_eval.py` — claim/entailment metrics over
  `datasets/citation_entailment_v1.json` (precision/recall per label,
  contradiction recall, abstention). `--challenge` scores the larger
  adversarial `datasets/citation_entailment_challenge_v1.json` panel and
  enforces the documented production gates (contradiction recall ≥ 0.80,
  accuracy ≥ 0.75). Run the semantic path with `--llm`; the offline
  deterministic (lexical) assessor is expected to fail the challenge gates
  and is retained only as a fallback baseline. See "Citation evaluation
  panels" below.
- `safety_eval.py` — per-hypothesis safety false-positive / false-negative
  rates for the deterministic-regex reviewer layer
  (`co_scientist.safety.review_hypothesis_safety`; never the optional
  semantic/LLM escalation), over two datasets:
  `datasets/hypothesis_safety_adversarial_v1.json` (must-block items; every
  item's `should_block` is `true`) and
  `datasets/hypothesis_safety_controls_v1.json` (must-allow items; every
  item's `should_block` is `false`, including a broad domain-diverse sample,
  not just adversarial near-misses). Each item also carries a `difficulty`:
  `easy` is the literal-trigger regression floor the classifier was written
  against (gated at 0 false negatives by `smoke.py`); `hard` is
  genuinely adversarial -- paraphrase/synonym evasion, character-gap
  padding past the regex's window, a word-boundary spacing trick, and
  vocabulary the classifier has no pattern for at all (nuclear, explosive),
  plus legitimate research that happens to use a literal trigger phrase
  ("mass casualty" disaster response, "nerve agent" detection assays,
  "bioweapon" treaty-compliance history). The `hard` split is measured and
  reported, never gated to pass -- see the eval's own module docstring.
- `claim_support_eval.py` — unsupported-claim rate over the verdicts a run
  already recorded, never re-judged here (a second lexical opinion inside
  an eval is how a metric comes to disagree with the product; see the
  Jaccard entry in the root AGENTS.md). Reports two rates: over claims,
  and over ideas with nothing behind them, since a retrieval change can
  move one without the other. **Offline by default proves the wiring, not
  quality** -- the deterministic backend answers every assessment the same
  canned way whatever was retrieved, and offline artifacts say so in an
  `offline_disclaimer`. `--run <id>` scores a persisted run; `--live`
  drives one against a real provider, at the size `--tier` names
  (default `express`). The manual `Benchmark` workflow runs it live for
  the optimization campaign's quality benchmark.
- `citation_usefulness_eval.py` — does a retrieved span answer *the
  question the search was serving*? Distinct from `citation_eval.py`,
  which asks whether a span entails a claim: the two come apart exactly
  where a research loop earns its cost, on a span that is squarely
  on-topic and answers a different question. Scores
  `datasets/citation_usefulness_v1.json`; the default deterministic judge
  is lexical coverage and is kept as a floor (it scores ~0.38 on the
  panel, by construction), `--llm` scores a real model. Note there is no
  production assessor to score here -- the system does not yet judge its
  own retrievals this way, so this eval's judge is its own.
- `_run_driver.py` — shared plumbing `claim_support_eval.py --live`
  uses to persist a research goal through the real durable path
  (`store.create_run` -> `task_worker` -> `engine_tasks` -> engine -> drain
  -> report) and read back the resulting artifacts. Not a runner itself.
- `_identity.py` — shared run and panel controls, policy snapshots and
  provenance checks. Hashing and validation load without app or engine
  dependencies; execution snapshots import those packages only when needed.
- `smoke.py` — the offline smoke suite with documented regression tolerances.
- `datasets/` — versioned, synthetic, legally shareable labeled sets.
- `results/` — dated machine-readable result artifacts.
- `tests/` — unit tests for the runners, architecture and source-size checks that
  `make test-evaluations` runs.

## Commands

```bash
# From the repo root, using the shared venv python:
python -m evaluations.smoke                 # offline smoke (safety + citation)
python -m evaluations.citation_eval         # writes results/citation-entailment-deterministic-<date>.json
python -m evaluations.citation_eval --challenge --llm  # adversarial panel, semantic assessor, enforces gates
python -m evaluations.safety_eval           # writes results/hypothesis-safety-<date>.json
python -m pytest evaluations/tests -q       # harness unit tests

# Or via make:
make test-evaluations # harness tests
make eval-smoke    # offline smoke suite
```

## Citation evaluation panels

Two panels exercise the claim-entailment assessor:

- **`citation_entailment_v1`** (20 items) — the offline regression panel. The
  deterministic (lexical) assessor handles it, so it gates the CI smoke suite
  (`smoke.py`) at contradiction recall ≥ 0.80.
- **`citation_entailment_challenge_v1`** (30 items) — an adversarial panel
  whose passages share the claim's vocabulary but must be rejected or inverted
  by a semantic reader: negation-free numeric/direction conflicts,
  species/model mismatches, temporal mismatches, topic-mention-only passages,
  retracted sources, and low-overlap paraphrase support/contradiction. It is
  the production-gate panel.

Recorded results from 2026-07-14 ([archived receipts](https://github.com/guy915/Co-Scientist/tree/7c2878aeb071a962cb713e9c271cd88e1635ca5f/evaluations/results)):

| Assessor | Panel | n | accuracy | contradiction recall | gates |
|---|---|---|---|---|---|
| deterministic (lexical) | v1 | 20 | 1.00 | 1.00 | pass |
| deterministic (lexical) | challenge | 30 | 0.17 | 0.00 | **fail (expected)** |
| `llm:deepseek/deepseek-chat` | challenge | 30 | 0.90 | 1.00 | pass |

The lexical assessor collapsing to 0.00 contradiction recall on the challenge
panel is the point: token overlap is a retrieval feature, not proof, so it is
retained only as an offline fallback. The semantic assessor clears the gates.
Its two conservative misses (abstaining on genuine paraphrase support) are
safe; its one retracted-passage miss is scored in isolation here — the full
pipeline quarantines retracted sources upstream, before grounding.

DeepSeek is a **compatibility-mode** provider. These numbers are not a claim of
current Google-model (Gemini) parity, and the thresholds are the replica's own
reconstructed gates, not Google's undisclosed production thresholds. The panel
is synthetic and legally shareable; a human-audited representative sample and
calibrated thresholds remain an external gap.

## Safety evaluation splits

`safety_eval.py` scores the hypothesis-safety layer over `easy` (the
literal-trigger regression floor) and `hard` (genuinely adversarial
paraphrase/synonym/padding/spacing evasion, vocabulary the classifier has no
pattern for, and legitimate near-boundary research that happens to use a
trigger phrase) items, combined from the adversarial and controls datasets.

It reports **two arms**, because the shipped layer is two layers and neither
number alone describes it:

- **Floor** — the deterministic regex alone. This is also exactly what ships
  whenever the contextual assessor cannot run: disabled, offline-pinned,
  uncredentialed, erroring, or answering anything but a clean allow. Every one
  of those leaves a held verdict held.
- **Permissive-assessor ceiling** — the same measurement assuming an assessor
  that clears *every* hold put to it, whether because it is weak, captured, or
  talked into it by the text it is reading. The eligibility gate is the real
  one, so this arm can only clear what the shipped code would actually put to
  an assessor.

Latest recorded results (2026-08-07, `results/hypothesis-safety-2026-08-07.json`):

| Arm | Split | n | false-negative rate | false-positive rate |
|---|---|---|---|---|
| floor | easy | 31 | 0.00 | 0.00 |
| floor | hard | 18 | 0.333 | 0.833 |
| ceiling | easy | 31 | 0.143 | 0.00 |
| ceiling | hard | 18 | 0.333 | 0.00 |

Read them together. The false-positive problem is entirely a hold problem: at
the floor the layer wrongly withholds 5 of 6 legitimate near-boundary research
items, and an assessor resolving those holds takes that to zero. What it costs
in the worst case is the gap in the other column — one easy adversarial item
whose danger is a genuine context call ("test the compound on patients without
informed consent"). Constructions whose danger is *not* a context call —
acquisition, yield improvement, a synthesis procedure named against a weapon
class — are deterministic blocks no assessor can reach, which is why the
ceiling's hard-split false-negative rate does not move at all.

Neither arm measures a real assessor's judgment. That needs a provider and is
not something this offline harness claims. What it does claim is a bound in
each direction, which is what a reader needs to judge the trade.

The remaining hard-split false negatives are genuine paraphrase with no
literal trigger token, which neither layer closes today.

## External gaps (not reproducible here)

These need unavailable data / credentials / expert panels / wet
labs and are recorded honestly rather than fabricated:

- **Google's private 1,200-goal safety benchmark** and **203-goal scaling
  corpus** are request-only and not reproduced.
- **Wet-lab validation** (AML / fibrosis / AMR) is out of scope.

Each runner records its own `external_gap` in its result artifact.

### Live panels

Live citation entailment and citation usefulness panels use free-model
configuration before importing model code. Set an explicit OpenRouter `MODEL_NAME`
and `OPENROUTER_API_KEY`; citation usefulness also accepts `--model` explicitly.
Every model role is pinned and transport admission checks current zero prices.
No paid/default model is selected implicitly. Run each live panel in a fresh
process. Offline modes require neither setting. Served-model, cost and fallback
evidence is still being completed under M1-03d3b; a panel score alone is not
qualified live scientific evidence. Historical results above remain historical.
