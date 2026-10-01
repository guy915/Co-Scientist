"""Backend-owned runs wire models, also used to generate frontend types."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, with_config
from typing_extensions import NotRequired, TypedDict

from app.api_contracts.common import (
    LegacyRunProfile,
    RunConfig,
    RunMode,
    RunStatus,
)


@with_config(ConfigDict(extra="allow"))
class RunExecutionProgress(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    determinate: bool
    completed_tasks: int
    total_tasks: int
    fraction: float | None
    active_task: str | None
    queued_tasks: int


@with_config(ConfigDict(extra="allow"))
class Run(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    id: str
    research_goal: str
    title: NotRequired[str | None]
    run_mode: NotRequired[RunMode]
    profile: LegacyRunProfile
    status: RunStatus
    provider: Literal["mock"] | Literal["engine"]
    config: RunConfig
    is_demo: NotRequired[bool]
    llm_backend: NotRequired[str | None]
    execution_policy: NotRequired[Literal["standard", "campaign"]]
    created_at: float
    updated_at: float
    completed_at: float | None
    error: str | None
    top_elo: NotRequired[float | None]
    top_hypotheses: NotRequired[list[str] | None]
    latest_stage: NotRequired[str | None]
    awaiting_decision_count: NotRequired[int]
    execution_progress: NotRequired[RunExecutionProgress]


@with_config(ConfigDict(extra="allow"))
class RunSummary(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    events: int
    hypotheses: int
    evidence: int
    matches: int
    reviews: int


@with_config(ConfigDict(extra="allow"))
class RunWithSummary(Run):
    """JSON contract; omitted fields stay omitted."""

    summary: RunSummary
    failure_kind: NotRequired[str | None]


@with_config(ConfigDict(extra="allow"))
class ReportShare(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    id: str
    run_id: str
    token: NotRequired[str]
    created_at: float


@with_config(ConfigDict(extra="allow"))
class SharedRun(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    research_goal: str
    title: NotRequired[str | None]
    run_mode: NotRequired[RunMode]


@with_config(ConfigDict(extra="allow"))
class QaSource(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    n: int
    evidence_id: str
    title: str
    url: NotRequired[str | None]
    source: NotRequired[str | None]
    year: NotRequired[float | None]
    state: str
    passage: NotRequired[str | None]


@with_config(ConfigDict(extra="allow"))
class MessageMetadata(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    sources: NotRequired[list[QaSource]]
    reasoning: NotRequired[str]
    fallback: NotRequired[bool]


@with_config(ConfigDict(extra="allow"))
class RunMessage(TypedDict):
    """JSON contract; omitted fields stay omitted."""

    id: int
    run_id: str
    sender: Literal["user"] | Literal["system"]
    content: str
    kind: str
    created_at: float
    applied: bool
    meta: MessageMetadata | None
    applied_at: NotRequired[float | None]
    applied_decision: NotRequired[str | None]
