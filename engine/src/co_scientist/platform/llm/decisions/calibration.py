import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class LabeledDecision:
    confidence: float
    agrees: bool


def agreement_lower_bound(labels: list[LabeledDecision], threshold: float) -> float:
    differences = [-float(row.confidence >= threshold and not row.agrees) for row in labels]
    if len(differences) < 2:
        return -1
    return statistics.mean(differences) - 1.645 * statistics.stdev(differences) / math.sqrt(
        len(differences)
    )


def choose_threshold(
    labels: list[LabeledDecision], *, tolerance: float = 0.02, minimum_labels: int = 100
) -> float | None:
    # Agreement with a reference judge is not independently labeled correctness.
    if len(labels) < minimum_labels or not 0 <= tolerance < 1:
        return None
    for row in labels:
        if not math.isfinite(row.confidence) or not 0 <= row.confidence <= 1:
            raise ValueError("invalid calibration confidence")
    candidates = sorted({row.confidence for row in labels if row.confidence > 0.5})
    for threshold in candidates:
        if agreement_lower_bound(labels, threshold) >= -tolerance:
            return threshold
    return None


def expected_calibration_error(labels: list[LabeledDecision]) -> float | None:
    if not labels:
        return None
    error = 0.0
    for index in range(10):
        group = [row for row in labels if min(int(row.confidence * 10), 9) == index]
        if group:
            accuracy = statistics.mean(float(row.agrees) for row in group)
            confidence = statistics.mean(row.confidence for row in group)
            error += len(group) / len(labels) * abs(accuracy - confidence)
    return error
