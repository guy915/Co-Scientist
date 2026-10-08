import argparse
import asyncio
import dataclasses
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

import httpx
from co_scientist.platform.llm import CompletionSpec, call_llm_json
from co_scientist.platform.llm.decisions import (
    DecisionSettings,
    DecisionUnavailableError,
    SystemOneClient,
)
from co_scientist.platform.llm.decisions.calibration import (
    LabeledDecision,
    agreement_lower_bound,
    choose_threshold,
    expected_calibration_error,
)
from co_scientist.platform.llm.decisions.types import DecisionResult
from co_scientist.platform.llm.telemetry import scoped_telemetry

from evaluations.decision_cases import DecisionCase, build_cases


def reference_values(
    site: str, response: dict[str, Any], names: list[str] | None = None
) -> dict[str, Any]:
    if site == "ranking_pairwise":
        from co_scientist.science.ranking.ranking_debate import _parse_matchup_winner

        winner, valid = _parse_matchup_winner(response, fallback="a")
        if not valid:
            raise ValueError("reference ranking has no valid winner")
        return {"winner": winner.upper()}
    if site == "literature_relevance":
        from co_scientist.platform.retrieval.evidence.relevance import _match_batch_judgments

        names = names or ["relevance"]
        judgments = _match_batch_judgments(response.get("judgments") or [], names)
        values = {}
        for name, entry in zip(names, judgments, strict=True):
            if not isinstance(entry, dict) or type(entry.get("relevance")) not in (int, float):
                raise ValueError("reference relevance labels are incomplete")
            value = float(entry["relevance"])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("reference relevance score is outside its bounds")
            values[name] = value
        return values
    if site == "proximity":
        grade = "low"
        for cluster in response["similarity_clusters"]:
            members = {
                row["index"]: row["similarity_degree"] for row in cluster["similar_hypotheses"]
            }
            if set(members) == {0, 1}:
                if all(value == "high" for value in members.values()):
                    grade = "high"
                    break
                grade = "medium"
        return {"similarity": grade}
    return {
        key: response.get(key, False)
        for key in (
            "category",
            "offensive_score",
            "is_personal_medical_recommendation",
            "is_personal_finance_recommendation",
        )
    }


def decision_values(site: str, result: DecisionResult) -> dict[str, Any]:
    values = {key: answer.value for key, answer in result.answers.items()}
    if site == "literature_relevance":
        values = {name: float(value) / 4 for name, value in values.items()}
    if site == "semantic_safety":
        values["offensive_score"] = float(values["offensive_score"]) + 1
    return values


def agrees(site: str, reference: dict[str, Any], decision: dict[str, Any]) -> bool:
    if site == "literature_relevance":
        return set(reference) == set(decision) and all(
            abs(reference[name] - decision[name]) <= 0.15
            and (reference[name] >= 0.5) == (decision[name] >= 0.5)
            for name in reference
        )
    if site == "semantic_safety":
        return all(
            (reference[key] >= 4) == (decision[key] >= 4)
            if key == "offensive_score"
            else reference[key] == decision[key]
            for key in decision
        )
    return reference == decision


async def _decide(client: SystemOneClient, case: DecisionCase, delay: float) -> DecisionResult:
    forward = await client.decide(case.decision_prompt or case.prompt, case.questions)
    if case.reverse_prompt is None:
        return forward
    await asyncio.sleep(delay)
    reverse = await client.decide(case.reverse_prompt, case.questions)
    a, b = forward.answers["winner"], reverse.answers["winner"]
    probability = (a.probabilities["A"] + b.probabilities["B"]) / 2
    confidence = min(a.confidence, b.confidence, max(probability, 1 - probability))
    if a.value == b.value:
        confidence = 0
    answer = dataclasses.replace(
        a,
        value="A" if probability >= 0.5 else "B",
        confidence=confidence,
        probabilities={"A": probability, "B": 1 - probability},
    )
    return dataclasses.replace(
        forward,
        answers={"winner": answer},
        input_tokens=(
            forward.input_tokens + reverse.input_tokens
            if forward.input_tokens is not None and reverse.input_tokens is not None
            else None
        ),
    )


def summarize(site: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if "reference" in row and "decision" in row]
    label_rows = completed
    if site == "literature_relevance":
        label_rows = [
            {
                "reference": {"relevance": row["reference"][name]},
                "decision": {"relevance": row["decision"][name]},
                "confidence": row.get("answers", {})
                .get(name, {})
                .get("confidence", row["confidence"]),
                "agrees": agrees(
                    site, {name: row["reference"][name]}, {name: row["decision"][name]}
                ),
                "batch_id": row["id"],
            }
            for row in completed
            for name in row["decision"]
        ]
    calibration_count = 100
    if site == "literature_relevance":
        calibration_count = 0
        for row in completed:
            calibration_count += len(row["decision"])
            if calibration_count >= 100:
                break
    calibration, held_out = label_rows[:calibration_count], label_rows[calibration_count:]
    labels = [LabeledDecision(row["confidence"], row["agrees"]) for row in calibration]
    threshold = choose_threshold(labels)
    accepted = [row for row in held_out if threshold is not None and row["confidence"] >= threshold]
    validation = [LabeledDecision(row["confidence"], row["agrees"]) for row in held_out]
    summary: dict[str, Any] = {
        "site": site,
        "reference_basis": "fresh current-LLM judgments; agreement is not ground truth",
        "completed_cases": len(completed),
        "calibration_cases": len(calibration),
        "held_out_cases": len(held_out),
        "threshold": threshold,
        "agreement": statistics.mean(row["agrees"] for row in label_rows) if label_rows else None,
        "reference_ece": expected_calibration_error(labels),
        "accepted_held_out_agreement": statistics.mean(row["agrees"] for row in accepted)
        if accepted
        else None,
        "held_out_escalation": 1 - len(accepted) / len(held_out) if held_out else None,
        "held_out_lower_bound": agreement_lower_bound(validation, threshold)
        if threshold is not None and held_out
        else None,
        "errors": len(rows) - len(completed),
        "adoption_ready": False,
        "attempted_cases": len(rows),
        "provider_refusals": sum(row.get("provider_status") == 429 for row in rows),
        "decision_served_fraction": len(completed) / sum("reference" in row for row in rows)
        if any("reference" in row for row in rows)
        else None,
    }
    if site == "literature_relevance" and completed:
        summary["paper_labels"] = len(label_rows)
        summary["score_mae"] = statistics.mean(
            abs(row["reference"]["relevance"] - row["decision"]["relevance"]) for row in label_rows
        )
        held_ids = {row["batch_id"] for row in held_out}
        calibration_ids = {row["batch_id"] for row in calibration}
        batches = [row for row in completed if row["id"] in held_ids - calibration_ids]
        accepted_batches = [
            row for row in batches if threshold is not None and row["confidence"] >= threshold
        ]
        calibration_end = max(
            (index for index, row in enumerate(rows) if row["id"] in calibration_ids), default=-1
        )
        attempted_holdout = (
            [row for row in rows[calibration_end + 1 :] if "reference" in row]
            if len(calibration) >= 100
            else []
        )
        summary["held_out_batches"] = len(batches)
        summary["held_out_batch_attempts"] = len(attempted_holdout)
        summary["held_out_batch_escalation"] = (
            1 - len(accepted_batches) / len(attempted_holdout) if attempted_holdout else None
        )
        summary["accepted_batch_agreement"] = (
            statistics.mean(row["agrees"] for row in accepted_batches) if accepted_batches else None
        )
        summary["held_out_batch_lower_bound"] = (
            agreement_lower_bound(
                [LabeledDecision(row["confidence"], row["agrees"]) for row in batches], threshold
            )
            if threshold is not None and batches
            else None
        )
        ordering = [
            (a - b) * (row["decision"][x] - row["decision"][y]) > 0
            for row in completed
            for x, a in row["reference"].items()
            for y, b in row["reference"].items()
            if x < y and a != b
        ]
        summary["semantic_order_agreement"] = statistics.mean(ordering) if ordering else None
        summary["limitation"] = (
            "paper calibration is grouped by disjoint batches; "
            "lexical-fusion selection needs separate validation"
        )
    if site == "semantic_safety":
        summary["false_allow_count"] = sum(
            row["reference"]["category"] != "allowed" and row["decision"]["category"] == "allowed"
            for row in completed
        )
        summary["limitation"] = (
            "risk-domain coverage and independent safety labels require separate validation"
        )
    if site == "ranking_pairwise":
        summary["limitation"] = (
            "recorded hypothesis text without mature reviews; owner spot checks required"
        )
    if site == "proximity":
        summary["limitation"] = "pair subsets do not establish full-pool deduplication equivalence"
    return summary


async def run_panel(
    site: str,
    cases: list[DecisionCase],
    client: SystemOneClient,
    model: str,
    delay: float,
    output: Path,
    *,
    continue_on_rate_limit: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    rate_limit_streak = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with scoped_telemetry(f"decision_bakeoff.{site}") as telemetry:
        for case in cases:
            row: dict[str, Any] = {"id": case.identifier, "side_ids": case.side_ids}
            rate_limit_pause = None
            try:
                reference = await call_llm_json(
                    case.prompt, CompletionSpec(model, json_schema=case.schema), max_attempts=1
                )
                row["reference"] = reference_values(site, reference, list(case.questions))
                await asyncio.sleep(delay)
                result = await _decide(client, case, delay)
                row["decision"] = decision_values(site, result)
                row["confidence"] = min(answer.confidence for answer in result.answers.values())
                row["agrees"] = agrees(site, row["reference"], row["decision"])
                row["rate_limits"] = result.rate_limits
                row["input_tokens"] = result.input_tokens
                row["state"] = case.prompt
                if case.decision_prompt is not None:
                    row["decision_representation"] = "per-candidate-question/v1"
                row["answers"] = {
                    name: dataclasses.asdict(answer) for name, answer in result.answers.items()
                }
                rate_limit_streak = 0
            except Exception as error:
                row["error"] = type(error).__name__
                if isinstance(error, DecisionUnavailableError):
                    row["provider_status"] = error.status_code
                    row["rate_limits"] = error.rate_limits
                    if continue_on_rate_limit and error.status_code == 429:
                        rate_limit_streak += 1
                        if rate_limit_streak < 3:
                            rate_limit_pause = _rate_limit_pause(error.rate_limits)
            rows.append(row)
            output.write_text(
                json.dumps(
                    {"summary": summarize(site, rows), "rows": rows, "usage": telemetry.snapshot()},
                    indent=2,
                )
            )
            if "error" in row and rate_limit_pause is None:
                break
            await asyncio.sleep(rate_limit_pause if rate_limit_pause is not None else delay)
        report = {"summary": summarize(site, rows), "rows": rows, "usage": telemetry.snapshot()}
        output.write_text(json.dumps(report, indent=2))
        return report


def _rate_limit_pause(headers: dict[str, str]) -> float | None:
    try:
        seconds = float(headers.get("retry-after", "60"))
    except ValueError:
        return None
    # Long/unknown cooldowns end the manual panel; no repeated quota probing.
    if not math.isfinite(seconds) or seconds < 0 or seconds > 300:
        return None
    return max(60, seconds)


async def account_limits() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            )
            if response.status_code != 200:
                return {"status": response.status_code}
            data = response.json()["data"]
            result = {
                key: data[key]
                for key in (
                    "limit",
                    "limit_remaining",
                    "usage_daily",
                    "is_free_tier",
                )
                if key in data and (data[key] is None or isinstance(data[key], (bool, int, float)))
            }
            daily = data.get("free_model_daily_requests")
            if isinstance(daily, dict):
                result["free_model_daily_requests"] = {
                    key: daily[key]
                    for key in ("used", "limit", "remaining")
                    if type(daily.get(key)) in (int, float)
                }
            elif type(daily) in (int, float):
                result["free_model_daily_requests"] = daily
            return result
    except Exception as error:
        return {"error": type(error).__name__}


async def run_live(
    site: str,
    cases: list[DecisionCase],
    settings: DecisionSettings,
    output: Path,
    delay: float = 4,
    *,
    continue_on_rate_limit: bool = False,
) -> dict[str, Any]:
    client = SystemOneClient(settings)
    eligible = []
    oversized = []
    for case in cases:
        try:
            client.estimate_tokens(case.decision_prompt or case.prompt, case.questions)
            if case.reverse_prompt:
                client.estimate_tokens(case.reverse_prompt, case.questions)
        except DecisionUnavailableError as error:
            if str(error) not in {"decision input is too large", "decision context limit exceeded"}:
                raise
            oversized.append(case.identifier)
        else:
            eligible.append(case)
    before = await account_limits()
    report = await run_panel(
        site,
        eligible,
        client,
        os.environ["MODEL_NAME"],
        delay,
        output,
        continue_on_rate_limit=continue_on_rate_limit,
    )
    report["evaluation_pacing_seconds"] = delay
    report["continue_on_rate_limit"] = continue_on_rate_limit
    report["preflight_oversized_ids"] = oversized
    report["summary"]["preflight_oversized_fallbacks"] = len(oversized)
    report["openrouter_account_before"] = before
    report["openrouter_account_after"] = await account_limits()
    output.write_text(json.dumps(report, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--site",
        required=True,
        choices=("ranking_pairwise", "literature_relevance", "proximity", "semantic_safety"),
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=5)
    parser.add_argument("--delay", type=float, choices=(4, 30), default=30)
    parser.add_argument("--quota-diagnostics", action="store_true")
    parser.add_argument("--continue-on-rate-limit", action="store_true")
    args = parser.parse_args()
    if (
        os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.getenv("GITHUB_ACTIONS") != "true"
    ):
        raise ValueError("live decision bake-off requires manual GitHub Actions dispatch")
    required = (
        ("LIQUID_API_KEY",) if args.quota_diagnostics else ("LIQUID_API_KEY", "OPENROUTER_API_KEY")
    )
    if not all(os.getenv(name, "").strip() for name in required):
        raise ValueError("manual bake-off credentials are missing")
    if not 1 <= args.cases <= 150:
        raise ValueError("case limit must be between 1 and 150")
    cases = build_cases(args.site, args.corpus)[: args.cases]
    if not cases:
        raise ValueError("no real-backend corpus inputs found")
    settings = DecisionSettings.from_env()
    if args.quota_diagnostics:
        from evaluations.decision_quota import run_quota_diagnostic

        report = asyncio.run(run_quota_diagnostic(cases[0], settings, args.output))
        print(json.dumps(report, indent=2))
        return 0 if report["quota_metadata"].get("status") in (200, 429) else 1
    report = asyncio.run(
        run_live(
            args.site,
            cases,
            settings,
            args.output,
            delay=args.delay,
            continue_on_rate_limit=args.continue_on_rate_limit,
        )
    )
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
