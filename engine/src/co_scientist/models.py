# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Data models for hypothesis generation workflow.

These models maintain compatibility with the original AI-CoScientist
while providing clean type safety for LangGraph.
"""

import enum
from dataclasses import dataclass, field
from typing import Any


class GenerationMethod(str, enum.Enum):
    """How a hypothesis was generated."""

    DEBATE = "debate"
    LITERATURE_TOOLS = "literature_tools"


@dataclass
class HypothesisReview:
    """Review of a hypothesis with scores and feedback."""

    review_summary: str
    scores: dict[str, int]  # scientific_soundness, novelty, relevance, etc.
    safety_ethical_concerns: str
    detailed_feedback: dict[str, str]
    constructive_feedback: str
    overall_score: float


@dataclass
class Hypothesis:
    """A research hypothesis with associated metadata.

    Attributes:
        text: The dense technical hypothesis formulation
        explanation: Step-by-step layman explanation of the hypothesis
        literature_grounding: Explicit grounding in literature review with
            [P1]/[KG1]-style citation keys
        experiment: Practical experiment design to test the hypothesis
        novelty_validation: Summary of search queries used to validate
            novelty and findings (tool-based generation only)
        enrichments: Post-generation enrichment data from configured tools
            (e.g., related CVEs)
        citation_map: Resolves inline citation keys to full source metadata.
            Paper entries: {"type": "paper", "title": ..., "url": ...,
            "authors": [...], "year": ...}
            KG entries: {"type": "knowledge_graph", "display": ...,
            "tool_id": ..., "data": {...}}
        score: Overall quality score (0-100)
        elo_rating: Elo rating from tournament selection
        reviews: List of reviews received
        similarity_cluster_id: Cluster ID from proximity analysis
        evolution_history: List of refinement summaries
        reflection_notes: Reflection analysis from literature comparison
        generation_method: Method used to generate ('debate' or
            'literature_tools')
        debate_id: Debate ID for debate-generated hypotheses
            (None for literature)
        win_count: Tournament wins
        loss_count: Tournament losses
        total_matches: Total tournament matches
    """

    text: str
    explanation: str | None = None
    literature_grounding: str | None = None
    experiment: str | None = None
    novelty_validation: str | None = None
    enrichments: dict[str, Any] = field(default_factory=dict)
    citation_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    score: float = 0.0
    elo_rating: int = 1200  # Starting Elo rating
    reviews: list[HypothesisReview] = field(default_factory=list)
    similarity_cluster_id: str | None = None
    similarity_degree: str | None = None  # 'high', 'medium', or 'low'
    evolution_history: list[str] = field(default_factory=list)
    reflection_notes: str | None = None
    # 'debate' or 'literature_tools'
    generation_method: GenerationMethod | None = None
    debate_id: None | (
        int) = None  # None for literature-generated, 0-N for debate-generated
    win_count: int = 0
    loss_count: int = 0

    @property
    def total_matches(self) -> int:
        """Total tournament matches played."""
        return self.win_count + self.loss_count

    @property
    def win_rate(self) -> float:
        """Win rate percentage (0-100)."""
        if self.total_matches == 0:
            return 0.0
        return (self.win_count / self.total_matches) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        generation_method = (self.generation_method.value
                             if self.generation_method else None)
        return {
            "text":
                self.text,  # Also referred to as "hypothesis" in other contexts
            "explanation": self.explanation,
            "literature_grounding": self.literature_grounding,
            "experiment": self.experiment,
            # "literature_review_used": self.literature_review_used,
            "novelty_validation": self.novelty_validation,
            "enrichments": self.enrichments,
            "citation_map": self.citation_map,
            "score": self.score,
            "elo_rating": self.elo_rating,
            "reviews": [{
                "review_summary": r.review_summary,
                "scores": r.scores,
                "safety_ethical_concerns": r.safety_ethical_concerns,
                "detailed_feedback": r.detailed_feedback,
                "constructive_feedback": r.constructive_feedback,
                "overall_score": r.overall_score,
            } for r in self.reviews],
            "similarity_cluster_id": self.similarity_cluster_id,
            "evolution_history": self.evolution_history,
            "reflection_notes": self.reflection_notes,
            "generation_method": generation_method,
            "debate_id": self.debate_id,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "total_matches": self.total_matches,
            "win_rate": self.win_rate,
        }


@dataclass
class ExecutionMetrics:
    """Metrics for workflow execution."""

    total_time: float = 0.0
    hypothesis_count: int = 0
    reviews_count: int = 0
    tournaments_count: int = 0
    evolutions_count: int = 0
    llm_calls: int = 0  # Total LLM calls made
    phase_times: dict[str, float] = field(default_factory=dict)


def create_metrics_update(
    hypothesis_count: int | None = None,
    reviews_count_delta: int = 0,
    tournaments_count_delta: int = 0,
    evolutions_count_delta: int = 0,
    llm_calls_delta: int = 0,
    total_time: float | None = None,
    phase_times: dict[str, float] | None = None,
) -> ExecutionMetrics:
    """Create new ExecutionMetrics with ONLY the deltas (not cumulative).

    The merge_metrics reducer will add these deltas to the existing state.
    Do NOT pass base metrics - only pass the increments from this node.

    Args:
        hypothesis_count: new total hypothesis count
            (replaces via max(), not adds)
        reviews_count_delta: number of reviews to add (delta only)
        tournaments_count_delta: number of tournaments to add (delta only)
        evolutions_count_delta: number of evolutions to add (delta only)
        llm_calls_delta: number of llm calls to add (delta only)
        total_time: new total time (only set if > 0)
        phase_times: new phase times dict (merged with existing)

    Returns:
        new ExecutionMetrics object with ONLY deltas
    """
    return ExecutionMetrics(
        hypothesis_count=hypothesis_count
        if hypothesis_count is not None else 0,
        reviews_count=reviews_count_delta,
        tournaments_count=tournaments_count_delta,
        evolutions_count=evolutions_count_delta,
        llm_calls=llm_calls_delta,
        total_time=total_time if total_time is not None else 0.0,
        phase_times=phase_times if phase_times is not None else {},
    )


@dataclass
class Article:
    """A literature article with extracted content and metadata.

    Note: In PubMed-only mode, `content` and `pdf_links` are unused.
    Fulltext content is accessed directly by PaperQA from HTML files.
    """

    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citations: int = 0
    abstract: str | None = None
    # unused in PubMed-only mode (PaperQA reads HTML files directly)
    content: str | None = None
    source_id: str | None = None
    source: str = "pubmed"  # default changed to "pubmed" (was "google_scholar")
    pdf_links: list[str] = field(
        default_factory=list)  # unused in PubMed-only mode (HTML-only)
    # flag indicating if this article was analyzed by the agent
    used_in_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "title": self.title,
            "url": self.url,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "citations": self.citations,
            "abstract": self.abstract,
            "content": self.content,
            "source_id": self.source_id,
            "source": self.source,
            "pdf_links": self.pdf_links,
            "used_in_analysis": self.used_in_analysis,
        }
