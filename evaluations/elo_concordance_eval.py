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
tournament uses (``co_scientist.agents.ranking.ranking_elo.
calculate_elo_update``) updates both ratings after each verdict. The
default comparator (used in CI and by the committed test) is a
deterministic stub that never calls a model. ``--llm`` wires the engine's
real pairwise ranking judge (``co_scientist.agents.ranking.ranking_debate.
judge_matchup``) for a live, opt-in measurement of the real judge; it needs
a provider key and is never run in CI.

Concordance is reported as Kendall's tau-b between the final Elo ranking
and the known correctness ranking (implemented here from scratch: this
package is stdlib-only), plus top-1 accuracy (does Elo's highest-rated
candidate carry the item's best correctness label). A coin-flip comparator
is also run as a chance-level baseline the real numbers should be read
against, since tau has no other built-in floor here.

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
    DEEPSEEK_API_KEY=... python -m evaluations.elo_concordance_eval --llm
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import pathlib
import random
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any

from co_scientist.agents.ranking.ranking_elo import calculate_elo_update
from co_scientist.constants import ELO_K_FACTOR

from evaluations._artifacts import write_dated_artifact

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DATASET = (
    _ROOT
    / "evaluations"
    / "datasets"
    / "hypothesis_correctness_concordance_v1.json"
)
_INITIAL_ELO = 1200


@dataclass(frozen=True)
class Candidate:
    """One graded candidate answer to a concordance item's question."""

    id: str
    text: str
    correctness: int


# A comparator judges one pair and returns "a" (candidate_a wins) or "b".
Comparator = Callable[[Candidate, Candidate, str], str]


def correctness_preferring_comparator(
    a: Candidate, b: Candidate, question: str
) -> str:
    """A comparator that always prefers the more-correct candidate.

    Ties broken toward ``a``. Used to pin the harness's own math: with a
    comparator that never disagrees with the ground truth, Elo must recover
    a ranking that never disagrees with it either.
    """
    del question
    return "a" if a.correctness >= b.correctness else "b"


def inverting_comparator(a: Candidate, b: Candidate, question: str) -> str:
    """A comparator that always prefers the LESS-correct candidate."""
    del question
    return "a" if a.correctness <= b.correctness else "b"


def make_coin_flip_comparator(seed: int) -> Comparator:
    """Return a seeded comparator that ignores correctness entirely.

    A chance-level baseline: real comparator results should be read against
    this, since Kendall's tau has no other built-in floor.
    """
    rng = random.Random(seed)

    def _flip(a: Candidate, b: Candidate, question: str) -> str:
        del a, b, question
        return rng.choice(("a", "b"))

    return _flip


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _tie_correction(values: Sequence[float]) -> float:
    """Sum of ``t*(t-1)/2`` over each tie group, for the tau-b denominator."""
    counts = Counter(values)
    return sum(count * (count - 1) / 2 for count in counts.values())


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Return Kendall's tau-b between two equal-length ranked sequences.

    Tau-b corrects for ties in either sequence (both correctness labels and
    final Elo ratings can tie), matching the standard definition used by
    e.g. ``scipy.stats.kendalltau``. Returns None when fewer than two items
    are given or every pair is tied in one sequence (rank undefined).
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
    """Deterministic per-item seed, stable across processes and re-runs.

    Builtin ``hash()`` on a string is salted per-process (PYTHONHASHSEED),
    so it cannot be used here without breaking reproducibility; CRC32 has
    no such salt.
    """
    return zlib.crc32(item_id.encode("utf-8"))


def _run_item_tournament(
    candidates: Sequence[Candidate],
    question: str,
    comparator: Comparator,
    position_seed: int,
) -> dict[str, int]:
    """Round-robin every distinct pair once; return final ratings by id.

    Args:
        candidates: The item's graded candidates.
        question: The item's question, passed through to the comparator.
        comparator: The pairwise judge.
        position_seed: Seeds a per-item shuffle of candidate order before
            pairing. The committed dataset places the correct answer first
            in most items, so pairing in list order would show every
            comparator -- including a position-biased real judge -- the
            correct answer as "a" almost every time, inflating concordance
            for a reason that has nothing to do with judgment quality. The
            shuffle is deterministic per item (seed = hash of item id) so a
            re-run reproduces the same matchups.
    """
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
    """Run one item's tournament; score its Elo-vs-correctness concordance."""
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


def evaluate_concordance(
    items: Sequence[dict[str, Any]],
    comparator: Comparator,
    comparator_id: str,
) -> dict[str, Any]:
    """Score one comparator's Elo-vs-correctness concordance over a dataset.

    Args:
        items: Dataset items, each with a ``question`` and ``candidates``.
        comparator: The pairwise judge to drive every matchup.
        comparator_id: A label for the comparator, carried into the report.

    Returns:
        Per-item results plus mean tau-b and top-1 accuracy.
    """
    per_item = [_item_result(item, comparator) for item in items]
    taus = [r["tau_b"] for r in per_item if r["tau_b"] is not None]
    return {
        "comparator": comparator_id,
        "n_items": len(per_item),
        "mean_tau_b": _mean(taus),
        "top1_accuracy": _mean(
            [1.0 if r["top1_correct"] else 0.0 for r in per_item]
        ),
        "per_item": per_item,
    }


def _load_dataset() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_DATASET.read_text(encoding="utf-8"))
    return data


def _make_llm_comparator() -> tuple[Comparator, str]:
    """Build a comparator backed by the engine's real pairwise ranking judge.

    Wraps the async ``judge_matchup`` (the exact function the production
    tournament calls) in a synchronous comparator via ``asyncio.run`` --
    this harness's tournament loop is synchronous, and the CLI issues calls
    one at a time regardless.

    Position bias: the candidate order the caller passes in is already
    per-item shuffled (see ``_run_item_tournament``), and on top of that a
    running matchup counter is fed as ``matchup_index`` so the production
    judge's own ``start_parity`` alternation engages too -- with
    ``matchup_index`` left ``None`` (its default) that alternation never
    triggers and a first-position-biased judge would inflate concordance on
    a dataset that happens to place the correct answer first most often.
    """
    from co_scientist.agents.ranking.ranking_debate import (
        _DebateContext,
        judge_matchup,
    )
    from co_scientist.models import Hypothesis

    model = os.getenv("MODEL_NAME") or "deepseek/deepseek-chat"
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
    """Evaluate every comparator (plus the real judge, if requested).

    The stub comparators always run, offline and free, so the report is
    never empty even for a live invocation; ``--llm`` adds the real judge's
    result alongside them for direct comparison.
    """
    dataset = _load_dataset()
    items = dataset["items"]
    results = {
        "correctness_preferring": evaluate_concordance(
            items, correctness_preferring_comparator, "correctness_preferring"
        ),
        "inverting": evaluate_concordance(
            items, inverting_comparator, "inverting"
        ),
        "coin_flip_seed0": evaluate_concordance(
            items, make_coin_flip_comparator(0), "coin_flip_seed0"
        ),
    }
    if use_llm:
        comparator, comparator_id = _make_llm_comparator()
        results[comparator_id] = evaluate_concordance(
            items, comparator, comparator_id
        )
    return {
        "dataset": dataset["name"],
        "dataset_version": dataset["version"],
        "external_gap": (
            "Not GPQA: GPQA is a licensed, gated benchmark and is not "
            "reproduced here. This is a small (8-item), hand-authored, "
            "synthetic substitute with an unambiguous graded-correctness "
            "ground truth; it establishes only that the Elo mechanism "
            "recovers a coarse ordering over a few candidates per question, "
            "not concordance at GPQA-difficulty or research-frontier "
            "correctness judgments."
        ),
        "results": results,
    }


def main() -> int:
    """Run the CLI, write the artifact, print a summary table."""
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
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
