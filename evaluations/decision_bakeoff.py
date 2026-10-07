import argparse
import asyncio
import dataclasses
import json
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


def reference_values(site: str, response: dict[str, Any]) -> dict[str, Any]:
    if site == "ranking_pairwise":
        from co_scientist.science.ranking.ranking_debate import _parse_matchup_winner

        winner, valid = _parse_matchup_winner(response, fallback="a")
        if not valid:
            raise ValueError("reference ranking has no valid winner")
        return {"winner": winner.upper()}
    if site == "literature_relevance":
        return {"relevance": float(response["judgments"][0]["relevance"])}
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
        values["relevance"] = float(values["relevance"]) / 4
    if site == "semantic_safety":
        values["offensive_score"] = float(values["offensive_score"]) + 1
    return values


def agrees(site: str, reference: dict[str, Any], decision: dict[str, Any]) -> bool:
    if site == "literature_relevance":
        a, b = reference["relevance"], decision["relevance"]
        return bool(abs(a - b) <= 0.15 and (a >= 0.5) == (b >= 0.5))
    if site == "semantic_safety":
        return all(
            (reference[key] >= 4) == (decision[key] >= 4)
            if key == "offensive_score"
            else reference[key] == decision[key]
            for key in decision
        )
    return reference == decision


async def _decide(client: SystemOneClient, case: DecisionCase, delay: float) -> DecisionResult:
    forward = await client.decide(case.prompt, case.questions)
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
    calibration, held_out = completed[:100], completed[100:]
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
        "agreement": statistics.mean(row["agrees"] for row in completed) if completed else None,
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
    }
    if site == "literature_relevance" and completed:
        summary["score_mae"] = statistics.mean(
            abs(row["reference"]["relevance"] - row["decision"]["relevance"]) for row in completed
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
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with scoped_telemetry(f"decision_bakeoff.{site}") as telemetry:
        for case in cases:
            row: dict[str, Any] = {"id": case.identifier, "side_ids": case.side_ids}
            try:
                reference = await call_llm_json(
                    case.prompt, CompletionSpec(model, json_schema=case.schema), max_attempts=1
                )
                row["reference"] = reference_values(site, reference)
                await asyncio.sleep(delay)
                result = await _decide(client, case, delay)
                row["decision"] = decision_values(site, result)
                row["confidence"] = min(answer.confidence for answer in result.answers.values())
                row["agrees"] = agrees(site, row["reference"], row["decision"])
                row["rate_limits"] = result.rate_limits
                row["input_tokens"] = result.input_tokens
                row["state"] = case.prompt
                row["answers"] = {
                    name: dataclasses.asdict(answer) for name, answer in result.answers.items()
                }
            except Exception as error:
                row["error"] = type(error).__name__
                if isinstance(error, DecisionUnavailableError):
                    row["provider_status"] = error.status_code
                    row["rate_limits"] = error.rate_limits
                rows.append(row)
                break
            rows.append(row)
            output.write_text(
                json.dumps(
                    {"summary": summarize(site, rows), "rows": rows, "usage": telemetry.snapshot()},
                    indent=2,
                )
            )
            await asyncio.sleep(delay)
        report = {"summary": summarize(site, rows), "rows": rows, "usage": telemetry.snapshot()}
        output.write_text(json.dumps(report, indent=2))
        return report


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
    site: str, cases: list[DecisionCase], settings: DecisionSettings, output: Path
) -> dict[str, Any]:
    before = await account_limits()
    report = await run_panel(
        site, cases, SystemOneClient(settings), os.environ["MODEL_NAME"], 4, output
    )
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
    args = parser.parse_args()
    if (
        os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.getenv("GITHUB_ACTIONS") != "true"
    ):
        raise ValueError("live decision bake-off requires manual GitHub Actions dispatch")
    if not all(os.getenv(name, "").strip() for name in ("LIQUID_API_KEY", "OPENROUTER_API_KEY")):
        raise ValueError("manual bake-off credentials are missing")
    if not 1 <= args.cases <= 150:
        raise ValueError("case limit must be between 1 and 150")
    cases = build_cases(args.site, args.corpus)[: args.cases]
    if not cases:
        raise ValueError("no real-backend corpus inputs found")
    settings = DecisionSettings.from_env()
    report = asyncio.run(run_live(args.site, cases, settings, args.output))
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
