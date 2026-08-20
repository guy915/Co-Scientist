"""A run that could search nothing has to say so.

Without a reachable literature server the graph routes around the
literature review and the observation reviews, deep research resolves to
no tier, and the deep reviews' probes refuse themselves. Every one of
those is correct behaviour and none of it is visible: the run completes,
the report reads like any other, and the only trace is a log line nobody
reads. These tests pin the fact the run now carries instead -- what it
lost, and what it had left.
"""

from __future__ import annotations

from typing import Any

from co_scientist.generator import _build_initial_state
from co_scientist.generator.initial_state import RunCapabilities, RunIdentity
from co_scientist.retrieval_degradation import (
    CAPABILITIES_LOST_WITHOUT_MCP,
    FLOOR_GROUP_CORPUS,
    FLOOR_NONE,
    FLOOR_RUN_ATTACHMENTS,
    MCP_UNREACHABLE,
    resolve_retrieval_degradation,
)


def _state(*, mcp_available: bool, opts: dict[str, Any] | None = None) -> Any:
    """An initial state for a run with or without a literature server."""
    return _build_initial_state(
        config_fields={},
        identity=RunIdentity(
            research_goal="reverse fibrosis", start_time=0.0, run_id="run-1"
        ),
        capabilities=RunCapabilities(mcp_available=mcp_available),
        opts=opts or {},
        user_inputs={},
    )


def test_a_run_that_can_retrieve_reports_nothing() -> None:
    """Absence is the healthy value, so no consumer has to special-case it."""
    assert _state(mcp_available=True)["retrieval_degradation"] is None


def test_a_run_that_cannot_retrieve_names_what_it_lost() -> None:
    """A run without literature looks exactly like one with it.

    A degraded run publishes ideas, reviews and a tournament exactly as a
    healthy one does. What it does not publish is any signal that none of
    it was checked against a paper, which is why the loss is enumerated
    rather than left as a single boolean.
    """
    degradation = _state(mcp_available=False)["retrieval_degradation"]

    assert degradation is not None
    assert degradation["reason"] == MCP_UNREACHABLE
    assert degradation["lost"] == list(CAPABILITIES_LOST_WITHOUT_MCP)
    assert "literature_review" in degradation["lost"]
    assert "deep_research" in degradation["lost"]


def test_with_no_documents_of_its_own_the_floor_is_nothing() -> None:
    """The plan expected a corpus floor here; there is not one.

    The group's papers stopped being a literature search source when the
    whole catalogue began arriving in run context instead, and the tool
    that reads one is served by the same server that just failed. So the
    honest answer for a run with no attachments is "nothing", and saying
    that is the point of the field.
    """
    degradation = _state(mcp_available=False)["retrieval_degradation"]

    assert degradation is not None
    assert degradation["floor"] == FLOOR_NONE


def test_a_run_with_attachments_still_has_those() -> None:
    """Private sources are searched in-process and survive the outage."""
    degradation = _state(
        mcp_available=False,
        opts={"context_enrichment_sources": [{"title": "a memo"}]},
    )["retrieval_degradation"]

    assert degradation is not None
    assert degradation["floor"] == FLOOR_RUN_ATTACHMENTS


def test_the_fact_is_plain_data() -> None:
    """It rides in checkpoints, which carry JSON and nothing else."""
    import json

    degradation = resolve_retrieval_degradation(
        mcp_available=False, private_sources=None
    )

    assert json.loads(json.dumps(degradation)) == degradation


def test_the_corpus_is_the_strongest_floor_and_keeps_research_alive() -> None:
    """The floor the plan assumed, now that it exists for real.

    It differs from the attachment floor in kind, not degree: attachments
    leave a run some text to cite, while the corpus is a search source,
    so the two capabilities that only need *a* source keep working. Any
    reader told merely that the run "degraded" would assume otherwise.
    """
    degradation = resolve_retrieval_degradation(
        mcp_available=False,
        private_sources=None,
        local_corpus=True,
    )

    assert degradation is not None
    assert degradation["floor"] == FLOOR_GROUP_CORPUS
    assert "deep_research" not in degradation["lost"]
    assert "review_evidence" not in degradation["lost"]
    # The four gated on the server itself are still gone.
    assert "literature_review" in degradation["lost"]
    assert "verification_probes" in degradation["lost"]


def test_the_corpus_outranks_attachments_as_the_reported_floor() -> None:
    """One floor is reported, and it names the strongest thing left."""
    degradation = resolve_retrieval_degradation(
        mcp_available=False,
        private_sources=[{"title": "a memo"}],
        local_corpus=True,
    )

    assert degradation is not None
    assert degradation["floor"] == FLOOR_GROUP_CORPUS


def test_a_healthy_run_reports_nothing_even_with_a_corpus() -> None:
    """The corpus is an ordinary source when the server is up."""
    assert (
        resolve_retrieval_degradation(
            mcp_available=True, private_sources=None, local_corpus=True
        )
        is None
    )
