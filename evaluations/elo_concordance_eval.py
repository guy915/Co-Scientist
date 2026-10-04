"""Elo-vs-known-correctness concordance harness (L8).

Google's evaluation calibrates the tournament's Elo ordering against
known-correct answers (a GPQA-style graduate-level question set). GPQA
itself is a licensed, gated benchmark -- not something this repository can
commit -- so this harness runs against a small, hand-authored, synthetic
dataset instead (``datasets/hypothesis_correctness_concordance_v1.json``,
8 items, 4 graded candidates each). That substitution is real and is stated
in every report this harness writes: passing here is NOT evidence of
GPQA-difficulty concordance. It shows only that the Elo mechanism recovers
a *coarse*, unambiguous correctness ordering over a handful of candidates
per question -- a much easier task than distinguishing expert-level
correctness at the research frontier.

For each item, every distinct pair of candidates is judged once by an
injectable comparator, and the SAME Elo update math the production
tournament uses (``co_scientist.agents.ranking.ranking_debate.
calculate_elo_update``) updates both ratings after each verdict. The
default comparator (used in CI and by the committed test) is a
deterministic stub that never calls a model. ``--llm`` wires the engine's
real pairwise ranking judge (``co_scientist.agents.ranking.ranking_debate.
judge_matchup``) for a live, opt-in measurement of the real judge; it needs
a provider key and is never run in CI.

Two concordance methods are reported, side by side, because they answer
different questions. Kendall's tau-b (implemented here from scratch: this
package is stdlib-only) is a rank-correlation statistic between the final
Elo ranking and the known correctness ranking, plus top-1 accuracy (does
Elo's highest-rated candidate carry the item's best correctness label). A
coin-flip comparator is also run as a chance-level baseline the real
numbers should be read against, since tau has no other built-in floor here.

The second method is Google's own published one (SSR L141, App. D): pool
every candidate response's *final* Elo rating across all questions,
categorize into discrete 50-point buckets (1001-1050, 1051-1100, ...), and
report the percentage of responses within each bucket that are the
question's correct answer -- see ``elo_bucket_accuracy``. This is not a
rank-correlation statistic at all; it asks whether Elo, read as an absolute
score, predicts correctness on its own terms, and it is what
``EVAL-ELO-CALIB-001`` names. Tau-b stays alongside it (not replaced) as an
independent sanity check of the harness's own Elo/ranking math -- it pins
"a comparator that always agrees with ground truth must rank in perfect
agreement with ground truth" the way the committed tests already use it,
a property the bucket method doesn't check as directly.

Position bias: the committed dataset places the correct answer first in
most items, so pairing candidates in list order would show any
first-position-biased comparator -- most plausibly the real LLM judge --
the correct answer as candidate "a" almost every time, inflating
concordance for a reason unrelated to judgment quality. Each item's
candidates are shuffled with a deterministic per-item seed before pairing,
and ``--llm`` additionally feeds a running ``matchup_index`` so the
production judge's own position-parity alternation engages.

Run:
    python -m evaluations.elo_concordance_eval             # offline stub
    # Export explicit MODEL_NAME and OPENROUTER_API_KEY first.
    python -m evaluations.elo_concordance_eval --llm
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import pathlib
import random
import zlib
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any

from evaluations._artifacts import write_dated_artifact

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DATASET = (
    _ROOT
    / "evaluations"
    / "datasets"
    / "hypothesis_correctness_concordance_v1.json"
)
_INITIAL_ELO = 1200

_EXTERNAL_GAP = (
    "Not GPQA: GPQA is a licensed, gated benchmark and is not reproduced "
    "here. This is a small (8-item), hand-authored, synthetic substitute "
    "with an unambiguous graded-correctness ground truth; it establishes "
    "only that Google's published method (elo_bucket_accuracy: pool every "
    "response's final Elo rating across questions, bucket in 50-point "
    "increments, report percent-correct per bucket -- see 'elo_buckets' "
    "below) and the Elo mechanism behind it behave sensibly over a few "
    "candidates per question, not concordance at GPQA-difficulty or "
    "research-frontier correctness judgments. The paper's companion "
    "Gemini-2.0 reference-accuracy baseline (32 sampled responses per "
    "question, used to correct for uneven per-question difficulty across "
    "buckets) is also not reproduced here -- it needs a live Gemini "
    "backend this repository is not configured to reach."
)


@dataclass(frozen=True)
class Candidate:
    id: str
    text: str
    correctness: int


Comparator = Callable[[Candidate, Candidate, str], str]


def correctness_preferring_comparator(
    a: Candidate, b: Candidate, question: str
) -> str:
    """The always-correct comparator pins harness math independently of the
    real judge.
    """
    del question
    return "a" if a.correctness >= b.correctness else "b"


def inverting_comparator(a: Candidate, b: Candidate, question: str) -> str:
    del question
    return "a" if a.correctness <= b.correctness else "b"


def make_coin_flip_comparator(seed: int) -> Comparator:
    """Compare real judgments against a chance baseline; tau has no other
    built-in floor.
    """
    rng = random.Random(seed)

    def _flip(a: Candidate, b: Candidate, question: str) -> str:
        del a, b, question
        return rng.choice(("a", "b"))

    return _flip


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _tie_correction(values: Sequence[float]) -> float:
    counts = Counter(values)
    return sum(count * (count - 1) / 2 for count in counts.values())


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Tau-b corrects ties in labels and ratings; fully tied ranks are
    undefined.
    """
    n = len(x)
    if n < 2 or n != len(y):
        return None
    concordant_minus_discordant = sum(
        _sign(x[i] - x[j]) * _sign(y[i] - y[j])
        for i, j in itertools.combinations(range(n), 2)
    )
    pair_count = n * (n - 1) / 2
    denom = sqrt(
        (pair_count - _tie_correction(x)) * (pair_count - _tie_correction(y))
    )
    return concordant_minus_discordant / denom if denom else None


def _item_seed(item_id: str) -> int:
    """Python string hashes are salted per process; CRC32 preserves
    reproducible item seeds.
    """
    return zlib.crc32(item_id.encode("utf-8"))


def _run_item_tournament(
    candidates: Sequence[Candidate],
    question: str,
    comparator: Comparator,
    position_seed: int,
) -> dict[str, int]:
    """Shuffle deterministically: correct-first dataset order would inflate a
    position-biased judge's score.
    """
    from co_scientist.agents.ranking.ranking_debate import calculate_elo_update
    from co_scientist.constants import ELO_K_FACTOR

    shuffled = list(candidates)
    random.Random(position_seed).shuffle(shuffled)
    ratings = {c.id: _INITIAL_ELO for c in candidates}
    for a, b in itertools.combinations(shuffled, 2):
        verdict = comparator(a, b, question)
        if verdict not in ("a", "b"):
            raise ValueError(
                f"comparator returned {verdict!r}, expected 'a' or 'b'"
            )
        winner, loser = (a, b) if verdict == "a" else (b, a)
        new_winner, new_loser = calculate_elo_update(
            ratings[winner.id], ratings[loser.id], ELO_K_FACTOR
        )
        ratings[winner.id], ratings[loser.id] = new_winner, new_loser
    return ratings


def _item_result(
    item: dict[str, Any], comparator: Comparator
) -> dict[str, Any]:
    candidates = [Candidate(**c) for c in item["candidates"]]
    ratings = _run_item_tournament(
        candidates, item["question"], comparator, _item_seed(item["id"])
    )
    elo_by_id = [ratings[c.id] for c in candidates]
    correctness_by_id = [c.correctness for c in candidates]
    tau = kendall_tau_b(elo_by_id, correctness_by_id)
    best_elo_id = max(ratings, key=lambda cid: ratings[cid])
    best_correctness = max(correctness_by_id)
    top1_correct = any(
        c.id == best_elo_id and c.correctness == best_correctness
        for c in candidates
    )
    return {
        "item_id": item["id"],
        "domain": item.get("domain"),
        "tau_b": round(tau, 4) if tau is not None else None,
        "top1_correct": top1_correct,
        "ratings": ratings,
        "correctness": {c.id: c.correctness for c in candidates},
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


_ELO_BUCKET_WIDTH = 50


def _elo_bucket_floor(elo: int) -> int:
    """Elo bucket origin is arbitrary, but fixed to reproduce the
    publication's 50-point labels.
    """
    return _ELO_BUCKET_WIDTH * ((elo - 1) // _ELO_BUCKET_WIDTH) + 1


def _elo_bucket_label(floor: int) -> str:
    return f"{floor}-{floor + _ELO_BUCKET_WIDTH - 1}"


def elo_bucket_accuracy(
    per_item: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Calibrate against each item's own maximum, not a hardcoded correctness
    scale. Gemini difficulty-debiasing baselines require an unavailable
    live backend.
    """
    buckets: dict[int, list[bool]] = defaultdict(list)
    for item in per_item:
        correctness = item["correctness"]
        if not correctness:
            continue
        best = max(correctness.values())
        for candidate_id, elo in item["ratings"].items():
            buckets[_elo_bucket_floor(elo)].append(
                correctness[candidate_id] == best
            )
    return [
        {
            "bucket": _elo_bucket_label(floor),
            "floor": floor,
            "n_responses": len(flags),
            "accuracy": round(sum(flags) / len(flags), 4),
        }
        for floor, flags in sorted(buckets.items())
    ]


def evaluate_concordance(
    items: Sequence[dict[str, Any]],
    comparator: Comparator,
    comparator_id: str,
) -> dict[str, Any]:
    per_item = [_item_result(item, comparator) for item in items]
    taus = [r["tau_b"] for r in per_item if r["tau_b"] is not None]
    return {
        "comparator": comparator_id,
        "n_items": len(per_item),
        "mean_tau_b": _mean(taus),
        "top1_accuracy": _mean(
            [1.0 if r["top1_correct"] else 0.0 for r in per_item]
        ),
        "elo_buckets": elo_bucket_accuracy(per_item),
        "per_item": per_item,
    }


def _load_dataset() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_DATASET.read_text(encoding="utf-8"))
    return data


def _make_llm_comparator() -> tuple[Comparator, str]:
    """Alternate matchup parity as well as item order so position-biased
    judges cannot inflate concordance.
    """
    from evaluations._live_config import configure_live_environment

    model = configure_live_environment()
    from co_scientist.agents.ranking.ranking_debate import (
        _DebateContext,
        judge_matchup,
    )
    from co_scientist.models import Hypothesis

    counter = itertools.count()

    def _judge(a: Candidate, b: Candidate, question: str) -> str:
        ctx = _DebateContext(
            Hypothesis(text=a.text),
            Hypothesis(text=b.text),
            question,
            model,
            matchup_index=next(counter),
        )
        winner, _response = asyncio.run(judge_matchup(ctx))
        return winner

    return _judge, f"llm:{model}"


def run(*, use_llm: bool) -> dict[str, Any]:
    live_comparator = _make_llm_comparator() if use_llm else None
    dataset = _load_dataset()
    items = dataset["items"]
    from evaluations._identity import capture_panel

    model = (
        live_comparator[1].removeprefix("llm:")
        if live_comparator
        else "offline_controls"
    )
    with capture_panel(
        "elo_concordance", dataset, model, live=use_llm
    ) as evidence:
        results = {
            name: evaluate_concordance(items, comparator, name)
            for name, comparator in (
                ("correctness_preferring", correctness_preferring_comparator),
                ("inverting", inverting_comparator),
            )
        }
        results["coin_flip_seed0"] = evaluate_concordance(
            items, make_coin_flip_comparator(0), "coin_flip_seed0"
        )
        for result in results.values():
            result["execution_mode"] = "offline"
        if live_comparator is not None:
            comparator, comparator_id = live_comparator
            results[comparator_id] = evaluate_concordance(
                items, comparator, comparator_id
            )
    if live_comparator is not None:
        results[live_comparator[1]].update(evidence)
    return {
        **evidence,
        "dataset": dataset["name"],
        "dataset_version": dataset["version"],
        "external_gap": _EXTERNAL_GAP,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Also score the engine's real pairwise ranking judge.",
    )
    args = parser.parse_args()
    report = run(use_llm=args.llm)
    out = write_dated_artifact(report, "elo-concordance")

    print(f"dataset={report['dataset']} n_items>0 external_gap noted")
    for comparator_id, result in report["results"].items():
        print(
            f"  {comparator_id:<28} mean_tau_b={result['mean_tau_b']!s:<8} "
            f"top1_accuracy={result['top1_accuracy']}"
        )
        for bucket in result["elo_buckets"]:
            print(
                f"      elo {bucket['bucket']:<11} "
                f"n={bucket['n_responses']:<3} accuracy={bucket['accuracy']}"
            )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
