"""HTTP envelopes for the JSON surfaces consumed by the workbench."""

from typing_extensions import TypedDict

from app.api_contracts.runs import ReportShare, Run, RunMessage
from app.api_contracts.science import (
    ClaimEvidenceRow,
    Evidence,
    Hypothesis,
    HypothesisOutcome,
    MatchRow,
    ProximityEdge,
    Review,
    SafetyDecision,
)


class RunsResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    runs: list[Run]


class HypothesesResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    hypotheses: list[Hypothesis]


class EvidenceResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    evidence: list[Evidence]


class MatchesResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    matches: list[MatchRow]


class ProximityResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    proximity: list[ProximityEdge]


class ReviewsResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    reviews: list[Review]


class SafetyResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    safety: list[SafetyDecision]


class OutcomesResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    outcomes: list[HypothesisOutcome]


class ClaimsResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    claim_evidence: list[ClaimEvidenceRow]


class MessagesResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    messages: list[RunMessage]


class SharesResponse(TypedDict):
    """Named collection envelope returned by the HTTP API."""

    shares: list[ReportShare]
