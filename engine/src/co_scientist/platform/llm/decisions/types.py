from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from co_scientist.platform.llm.decisions.settings import DecisionUnavailableError

Primitive = Literal["noul", "choice", "score"]


@dataclass(frozen=True)
class Question:
    kind: Primitive
    instructions: str
    criteria: dict[str, str] | tuple[str, ...] | None = None

    def body(self) -> dict[str, Any]:
        if not self.instructions.strip():
            raise DecisionUnavailableError("decision instructions are empty")
        body: dict[str, Any] = {"type": self.kind, "instructions": self.instructions}
        if self.kind == "noul":
            if self.criteria is not None:
                raise DecisionUnavailableError("binary questions cannot have criteria")
        elif self.kind == "choice":
            if not isinstance(self.criteria, dict) or not 2 <= len(self.criteria) <= 64:
                raise DecisionUnavailableError("choice requires named options")
            if not all(k.strip() and v.strip() for k, v in self.criteria.items()):
                raise DecisionUnavailableError("choice options cannot be empty")
            body["criteria"] = dict(self.criteria)
        elif self.kind == "score":
            if not isinstance(self.criteria, tuple) or not 2 <= len(self.criteria) <= 64:
                raise DecisionUnavailableError("score requires an ordered rubric")
            if not all(level.strip() for level in self.criteria):
                raise DecisionUnavailableError("rubric levels cannot be empty")
            body["criteria"] = list(self.criteria)
        else:
            raise DecisionUnavailableError("unknown decision primitive")
        return body


@dataclass(frozen=True)
class Answer:
    kind: Primitive
    value: bool | str | float
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class DecisionResult:
    model: str
    answers: dict[str, Answer]
    input_tokens: int | None
    rate_limits: dict[str, str] = field(default_factory=dict)

    def note(self, name: str) -> str:
        return f"Decided by {self.model}, p={self.answers[name].confidence:.2f}"


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionUnavailableError("decision probability must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise DecisionUnavailableError("decision probability is outside its bounds")
    return float(value)


def _distribution(row: dict[str, Any], keys: set[str]) -> dict[str, float]:
    raw = row.get("probabilities")
    if not isinstance(raw, dict) or set(raw) != keys:
        raise DecisionUnavailableError("decision options do not match the question")
    probabilities = {key: _probability(value) for key, value in raw.items()}
    if not math.isclose(sum(probabilities.values()), 1, abs_tol=0.001):
        raise DecisionUnavailableError("decision probabilities do not sum to one")
    return probabilities


def _answer(question: Question, row: Any) -> Answer:
    if not isinstance(row, dict) or row.get("type") != question.kind:
        raise DecisionUnavailableError("decision primitive does not match the question")
    if question.kind == "noul":
        yes = _probability(row.get("noul"))
        return Answer("noul", yes >= 0.5, max(yes, 1 - yes), {"yes": yes, "no": 1 - yes})
    criteria = question.criteria
    keys = (
        set(criteria)
        if isinstance(criteria, dict)
        else {str(i) for i in range(len(criteria or ()))}
    )
    probabilities = _distribution(row, keys)
    confidence = min(max(probabilities.values()), _probability(row.get("confidence")))
    if question.kind == "choice":
        value = row.get("choice")
        if value not in probabilities or probabilities[value] < max(probabilities.values()):
            raise DecisionUnavailableError("decision choice disagrees with its probabilities")
        return Answer("choice", str(value), confidence, probabilities)
    expected = sum(int(key) * probability for key, probability in probabilities.items())
    value = row.get("score")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not math.isclose(value, expected, abs_tol=0.002)
    ):
        raise DecisionUnavailableError("decision score disagrees with its probabilities")
    return Answer("score", expected, confidence, probabilities)


def parse_result(body: Any, questions: dict[str, Question]) -> DecisionResult:
    if not isinstance(body, dict) or body.get("model") not in {"d1:free", "d1"}:
        raise DecisionUnavailableError("unrecognized decision model response")
    rows = body.get("answers")
    if not isinstance(rows, dict) or set(rows) != set(questions):
        raise DecisionUnavailableError("decision answers do not match the requested questions")
    answers = {name: _answer(question, rows[name]) for name, question in questions.items()}
    usage = body.get("usage")
    tokens = None
    if usage is not None:
        if (
            not isinstance(usage, dict)
            or type(usage.get("input_tokens")) is not int
            or usage["input_tokens"] < 0
            or type(usage.get("output_tokens")) is not int
            or usage["output_tokens"] != 0
        ):
            raise DecisionUnavailableError("invalid decision usage")
        tokens = usage["input_tokens"]
    return DecisionResult(str(body["model"]), answers, tokens)
