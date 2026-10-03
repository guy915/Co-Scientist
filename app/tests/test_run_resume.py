"""Tests for run lifecycle 1."""

from __future__ import annotations

import asyncio
import types
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import engine_adapter, store, task_worker
from app.config import settings
from app.engine_tasks import support as engine_tasks_support
from app.human_input import (
    SCIENTIST_MANUAL_ORIGIN,
    admit_human_hypothesis,
    build_human_review,
)
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.runs import lifecycle as runs_lifecycle
from app.runs.lifecycle import _prepare_resume_state
from app.safety import SafetyDecision
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client
from tests._client import make_client as _client
from tests._engine_tasks_helpers import (
    _Generator,
    _install_fake_engine_llm,
    _install_runtime,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
)
from tests._llm_fake_backend import install_completion_backend
from tests._process_mode_helpers import FakeProcessMode

# Tests for scientist-in-the-loop hypotheses and reviews (Milestone 7).


def test_admitted_human_hypothesis_carries_authorship() -> None:
    """A safe scientist hypothesis is admitted with authorship provenance."""
    result = admit_human_hypothesis(
        text="Inhibiting kinase X reduces AML tumor growth via apoptosis.",
        author="dr-jane",
    )
    assert result.admitted
    assert result.hypothesis is not None
    assert result.hypothesis["origin"] == SCIENTIST_MANUAL_ORIGIN
    assert result.hypothesis["author"] == "dr-jane"
    # Enters at generation 0 with no parent, like a generated root.
    assert result.hypothesis["generation"] == 0
    assert result.hypothesis["parent_id"] is None


def test_human_hypothesis_uses_same_safety_path_no_bypass() -> None:
    """An unsafe scientist hypothesis is blocked; authorship is no bypass.

    This is the key M7 invariant: human hypotheses use the same safety path.
    """
    result = admit_human_hypothesis(
        text="Weaponize the pathogen to enhance transmissibility in humans.",
        author="dr-jane",
    )
    assert not result.admitted
    assert result.hypothesis is None
    assert result.safety_review.blocks_tournament


def test_admission_serializes_for_audit() -> None:
    """The admission decision serializes with author + safety provenance."""
    result = admit_human_hypothesis(
        text="Blocking receptor Y restores immune surveillance.",
        author="dr-lee",
    )
    d = result.to_dict()
    assert d["author"] == "dr-lee"
    assert d["admitted"] is True
    safety = d["safety"]
    assert isinstance(safety, dict) and "policy_version" in safety


def test_human_review_validates_verdict() -> None:
    """A scientist review is built with a validated verdict and authorship."""
    review = build_human_review(
        hypothesis_id="h1",
        author="dr-jane",
        verdict="Support",
        critique="Strong mechanistic grounding.",
    )
    assert review.verdict == "support"
    d = review.to_dict()
    assert d["reviewer_agent"] == "scientist"
    assert d["author"] == "dr-jane"


def test_human_review_rejects_bad_verdict() -> None:
    """An unrecognized verdict is rejected."""
    with pytest.raises(ValueError):
        build_human_review(
            hypothesis_id="h1",
            author="x",
            verdict="maybe",
            critique="",
        )


# Scientist-in-the-loop endpoints (Milestone 7): manual hypotheses + reviews.
#
# Covers POST /api/runs/{id}/hypotheses and /reviews: a scientist hypothesis
# passes the same safety path (no bypass), is persisted with authorship
# provenance and a screened safety_status, and appears in the run's hypotheses;
# a scientist review lands in the shared reviews table attributed to its author.


def _new_run(client: Any, headers: dict[str, str] | None = None) -> str:
    res = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Scientist-in-the-loop goal"},
    )
    return str(res.json()["id"])


def test_scientist_hypothesis_admitted_with_authorship(
    isolated_db: str,
) -> None:
    """A submitting caller's own identity attributes their contribution.

    ``author`` in the body is a required field, but ``runs/contrib.py``
    prefers the caller's own ``X-Client-ID`` over it whenever the caller
    has one -- which every owner of a real run now does, run creation
    itself refusing an identity-less caller (see
    ``app.auth.require_client_scope``). The two must agree here for the
    same reason they always have for any explicitly-identified caller.
    """
    headers = {"X-Client-ID": "dr-smith"}
    client = _client()
    run_id = _new_run(client, headers)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        headers=headers,
        json={
            "statement": "Inhibiting kinase X reduces AML growth by apoptosis.",
            "author": "dr-smith",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admitted"] is True
    assert body["author"] == "dr-smith"

    # It appears in the run's hypotheses with scientist provenance + a screened
    # safety status (same path as generated hypotheses, not left 'pending').
    hyps = client.get(f"/api/runs/{run_id}/hypotheses", headers=headers).json()[
        "hypotheses"
    ]
    manual = next(h for h in hyps if h["id"] == body["id"])
    assert manual["created_by_agent"] == "scientist_manual"
    assert manual["author"] == "dr-smith"
    assert manual["safety_status"] == "allow"
    pending = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    assert pending[-1]["kind"] == "steering"
    assert pending[-1]["meta"]["kind"] == "manual_hypothesis"


def test_scientist_unsafe_hypothesis_is_blocked_not_persisted(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={
            "statement": (
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
            "author": "bad-actor",
        },
    )
    assert res.status_code == 200
    body = res.json()
    # No bypass for human authorship: the unsafe hypothesis is not admitted.
    assert body["admitted"] is False
    assert body["safety"]["outcome"] == "prohibited"

    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    assert all(h["created_by_agent"] != "scientist_manual" for h in hyps)


def test_scientist_review_lands_in_reviews_table(isolated_db: str) -> None:
    """A review lands attributed to the submitting caller's own identity.

    See ``test_scientist_hypothesis_admitted_with_authorship`` on why the
    caller's own identity, not the body's ``author`` field, is what lands
    in the review summary -- the two are made to agree here.
    """
    headers = {"X-Client-ID": "dr-lee"}
    client = _client()
    run_id = _new_run(client, headers)
    hyp = client.post(
        f"/api/runs/{run_id}/hypotheses",
        headers=headers,
        json={"statement": "A safe, testable hypothesis.", "author": "dr-lee"},
    ).json()

    res = client.post(
        f"/api/runs/{run_id}/reviews",
        headers=headers,
        json={
            "hypothesis_id": hyp["id"],
            "author": "dr-lee",
            "verdict": "support",
            "critique": "Well grounded; suggest a control arm.",
        },
    )
    assert res.status_code == 200
    assert res.json()["recorded"] is True

    reviews = client.get(f"/api/runs/{run_id}/reviews", headers=headers).json()[
        "reviews"
    ]
    scientist = [r for r in reviews if r["reviewer_agent"] == "scientist"]
    assert len(scientist) == 1
    assert "dr-lee" in scientist[0]["summary"]
    messages = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    assert messages[-1]["meta"]["kind"] == "human_review"
    assert messages[-1]["applied"] is False


def test_scientist_review_rejects_invalid_verdict(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    hyp = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={"statement": "A safe, testable hypothesis.", "author": "dr-lee"},
    ).json()
    res = client.post(
        f"/api/runs/{run_id}/reviews",
        json={
            "hypothesis_id": hyp["id"],
            "author": "dr-lee",
            "verdict": "maybe",
            "critique": "",
        },
    )
    assert res.status_code == 422


def test_scientist_review_rejects_unknown_hypothesis(isolated_db: str) -> None:
    """A review must target a hypothesis that exists (no dangling rows)."""
    client = _client()
    run_id = _new_run(client)
    res = client.post(
        f"/api/runs/{run_id}/reviews",
        json={
            "hypothesis_id": "does-not-exist",
            "author": "dr-lee",
            "verdict": "support",
            "critique": "",
        },
    )
    assert res.status_code == 404


def test_scientist_review_rejects_cross_run_hypothesis(
    isolated_db: str,
) -> None:
    """A review cannot target a hypothesis owned by a different run."""
    client = _client()
    run_a = _new_run(client)
    run_b = _new_run(client)
    hyp_b = client.post(
        f"/api/runs/{run_b}/hypotheses",
        json={"statement": "A safe hypothesis in run B.", "author": "dr-lee"},
    ).json()

    # Post a review to run A referencing run B's hypothesis.
    res = client.post(
        f"/api/runs/{run_a}/reviews",
        json={
            "hypothesis_id": hyp_b["id"],
            "author": "dr-lee",
            "verdict": "support",
            "critique": "",
        },
    )
    assert res.status_code == 404
    # No mismatched review row leaked into run A.
    assert client.get(f"/api/runs/{run_a}/reviews").json()["reviews"] == []


def test_attachment_indexed_and_searchable(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={
            "title": "Persister cell review",
            "text": (
                "Drug-tolerant persister cells survive EGFR inhibition via "
                "a reversible transcriptional program and mitochondrial "
                "priming."
            ),
            "consent": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["indexed"] is True

    # The attachment is retrievable from the run's private corpus.
    hits = client.get(
        f"/api/runs/{run_id}/attachments/search",
        params={"q": "persister mitochondrial priming"},
    ).json()["results"]
    assert hits
    assert hits[0]["title"] == "Persister cell review"


def test_attachment_requires_consent(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={"title": "Doc", "text": "Some text.", "consent": False},
    )
    assert res.status_code == 422


def test_attachment_rejects_oversized_text(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)
    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={"title": "Big", "text": "x" * 200_001, "consent": True},
    )
    # The request-model max_length bound rejects it before any storage.
    assert res.status_code == 422


def test_pasted_and_uploaded_attachments_emit_same_audit_event(
    isolated_db: str,
) -> None:
    """A pasted-text attachment must audit identically to an uploaded file.

    Both endpoints persist evidence and steer the run with the same
    contribution kind (see runs/contrib.py); the event log must not treat
    one as invisible while recording the other.
    """
    client = _client()
    run_id = _new_run(client)

    pasted = client.post(
        f"/api/runs/{run_id}/attachments",
        json={
            "title": "Pasted note",
            "text": "Persister cells tolerate EGFR inhibition reversibly.",
            "consent": True,
        },
    ).json()
    uploaded = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={
            "file": ("assay.md", b"Kinase X reduced growth.", "text/markdown")
        },
        data={"consent": "true"},
    ).json()

    events = client.get(f"/api/runs/{run_id}/events?stream=false").json()
    attachment_events = [
        e for e in events["events"] if e["type"] == "scientist.attachment"
    ]
    assert [e["payload"]["evidence_id"] for e in attachment_events] == [
        pasted["id"],
        uploaded["id"],
    ]
    assert attachment_events[0]["payload"]["title"] == "Pasted note"
    assert attachment_events[1]["payload"]["title"] == "assay.md"


# App-level checkpoint + resume: derived-data clearing and pause semantics.
#
# Engine resume itself (restore a persisted ``WorkflowState`` and continue from
# the last checkpoint without redoing completed work) is covered end-to-end in
# ``test_resume_engine.py``, including the durable pause/resume path in
# ``test_runs_edge.py`` (test
# ``test_engine_queue_can_pause_and_resume_without_process_handle``).
# This file covers the surrounding store + endpoint seams that resume relies on:
# ``clear_run_derived_data`` preserving scientist contributions while dropping
# agent artifacts, event-seq continuity across a resume boundary, and the
# resume/pause endpoint guards.


def _seed_agent_artifacts(run_id: str) -> str:
    """Persist agent-authored hypothesis + review + retrieved evidence."""
    agent_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Agent idea",
            statement="An agent-generated hypothesis.",
            created_by_agent="generation",
        )
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=agent_id,
            reviewer_agent="reflection",
            summary="agent review",
            critique="agent critique",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Retrieved paper",
            source="pubmed",
            abstract="x",
        )
    )
    return agent_id


def _seed_scientist_artifacts(run_id: str) -> str:
    """Persist scientist hypothesis + human review + an attachment."""
    manual_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Human idea",
            statement="A scientist-authored hypothesis.",
            created_by_agent="scientist_manual",
            author="dr-who",
        )
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=manual_id,
            reviewer_agent="scientist",
            summary="human review",
            critique="looks promising",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Attached doc",
            source="attachment",
            abstract="notes",
        )
    )
    return manual_id


def test_resume_preserves_scientist_contributions(isolated_db: str) -> None:
    """Clearing derived data keeps human hypotheses/reviews/attachments."""
    run = store.create_run(
        "Human input survives resume", "express", "engine", {}
    )
    _seed_agent_artifacts(run.id)
    manual_id = _seed_scientist_artifacts(run.id)

    store.clear_run_derived_data(run.id)

    # The human hypothesis, review, and attachment survive; agent artifacts go.
    hyps = store.list_hypotheses(run.id)
    assert [h["id"] for h in hyps] == [manual_id]
    reviews = store.list_reviews(run.id)
    assert len(reviews) == 1 and reviews[0]["reviewer_agent"] == "scientist"
    evidence = store.list_evidence(run.id)
    assert [e["source"] for e in evidence] == ["attachment"]


def test_publication_replay_preserves_task_history_and_scientist_input(
    isolated_db: str,
) -> None:
    """Finalizer cleanup removes drain rows without erasing durable history."""
    run = store.create_run("Publication replay", "express", "engine", {})
    manual_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Human idea",
            statement="Scientist idea",
            created_by_agent="scientist_manual",
        )
    )
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Agent idea",
            statement="Agent idea",
            created_by_agent="generation",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id, title="Private", source="attachment", abstract="x"
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id, title="Paper", source="pubmed", abstract="y"
        )
    )
    store.append_event(run.id, "scientific_task", {"task": "ranking"})
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run.id,
            stage="intake",
            decision="allow",
            reason="",
            matches=[],
        )
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.finalize",
            inputs={},
            idempotency_key="finalize-test",
        ),
        db_path=isolated_db,
    )

    store.clear_publication_artifacts(run.id, db_path=isolated_db)

    assert [item["id"] for item in store.list_hypotheses(run.id)] == [manual_id]
    assert [item["source"] for item in store.list_evidence(run.id)] == [
        "attachment"
    ]
    assert len(store.list_events(run.id)) == 1
    assert len(store.list_safety_decisions(run.id)) == 1
    assert len(store.list_tasks(run.id, db_path=isolated_db)) == 1


def test_resume_reassigns_event_seqs_above_last_checkpoint(
    isolated_db: str,
) -> None:
    """Event seqs after a resume continue above the checkpoint high-water mark.

    ``clear_run_derived_data`` empties ``run_events``, but a client holding
    ``?after=N`` from before the resume must not silently miss the resumed
    run's events. The checkpoint's ``last_event_seq`` floors the next seq.
    """
    run = store.create_run("Seq continuity", "express", "engine", {})
    for i in range(5):
        store.append_event(run.id, "log", {"i": i})
    high_water = store.latest_event_seq(run.id)
    assert high_water == 5

    # A checkpoint records the high-water mark, then a resume clears events.
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="pause", schema_version=1, last_event_seq=high_water, state={}
        ),
    )
    store.clear_run_derived_data(run.id)
    assert store.list_events(run.id) == []

    # The next event continues strictly above the pre-resume high-water mark,
    # so an ?after=5 reconnect still receives it.
    seq = store.append_event(run.id, "status", {"status": "resuming"})
    assert seq == high_water + 1
    assert store.list_events(run.id, after_seq=high_water)[0]["seq"] == seq


def test_resume_endpoint_requires_a_checkpoint(isolated_db: str) -> None:
    """Resuming a run with no checkpoint is a 409 (nothing to resume from)."""
    client = _client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "No checkpoint yet"}
    ).json()["id"]
    res = client.post(f"/api/runs/{run_id}/resume")
    assert res.status_code == 409


def test_pause_endpoint_404_when_not_active(isolated_db: str) -> None:
    """Pausing a run that is not running in this process is a 404."""
    client = _client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Not active"}
    ).json()["id"]
    res = client.post(f"/api/runs/{run_id}/pause")
    assert res.status_code == 404


# App-level double-resume-cycle coverage (CKPT-FAILINJECT-001).
#
# The engine-level ``test_double_restart_preserves_pool_and_completes``
# proves two consecutive checkpoint/restore cycles survive on a bare
# ``WorkflowState``. Nothing at the app layer replayed that composition
# against the *durable task queue* -- the mock-era ``test_double_resume_is_
# stable`` covered it but was dropped with the mock workflow, and the
# single-interruption coverage that replaced it
# (``test_resume_engine.py``, ``test_runs_edge.py::
# test_engine_queue_can_pause_and_resume_without_process_handle``) never
# went further than one pause/resume.
#
# Drives the durable task queue one task at a time
# (``task_worker.run_once``) rather than relying on the embedded worker's
# own background timing, so both pause boundaries land at a known point
# in the run instead of racing a thread -- the app-layer analogue of the
# engine test's precise ``_pre_orchestrator_index`` cut point.


_WORKER = "double-resume-test"


async def _advance(run_id: str, count: int, db_path: str) -> None:
    """Execute exactly ``count`` ready durable tasks for ``run_id``."""
    for _ in range(count):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished (or stalled) earlier than the test expects"


async def _advance_until_pool_nonempty(
    run_id: str, db_path: str, *, cap: int = 30
) -> set[str]:
    """Run tasks one at a time until the checkpointed pool is non-empty.

    A fixed task count would hard-code the exact shape of generation's
    fan-out (strategy items + an aggregate that is the one commit
    actually merging hypotheses into state), which is not this test's
    concern and would make it brittle to that shape changing. Bounded so
    a run that never grows a pool fails loudly instead of hanging.
    """
    for _ in range(cap):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished before its pool ever grew"
        pool = _checkpoint_hypothesis_ids(run_id, db_path)
        if pool:
            return pool
    raise AssertionError(f"pool still empty after {cap} tasks")


def _pause_and_resume(client: Any, run_id: str) -> None:
    """One durable pause/resume cycle over HTTP, asserting both succeed."""
    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/api/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"


def _checkpoint_hypothesis_ids(run_id: str, db_path: str) -> set[str]:
    """Read the hypothesis ids out of the run's latest raw checkpoint.

    Indexes the stored envelope directly (``checkpoint["state"]`` is
    ``co_scientist.checkpoint.serialize_workflow_state``'s own envelope,
    whose payload sits one level further under its own ``"state"`` key)
    rather than going through ``restore_workflow_state``, since this only
    needs to read ids, not reconstruct live ``Hypothesis`` objects.
    """
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    payload = checkpoint["state"]["state"]
    return {str(h["id"]) for h in payload.get("hypotheses") or []}


@pytest.mark.asyncio
async def test_two_resume_cycles_still_complete_with_pool_intact(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two pause/resume cycles on one run still reach a completed report.

    Embedded worker execution is disabled so nothing but this test's own
    ``task_worker.run_once`` calls advances the run -- the same technique
    ``test_engine_queue_can_pause_and_resume_without_process_handle`` uses
    for a single cycle, extended here to two, through to completion, with
    an explicit check that the pool captured before the second
    interruption survives into the published report.
    """
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = client.post(
        "/api/runs",
        json={"research_goal": "Double resume coverage", "tier": "express"},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    # First interruption: right after bootstrap, before any checkpoint
    # has ever needed to be resumed from at all.
    await _advance(run_id, 1, isolated_db)
    _pause_and_resume(client, run_id)

    # Second interruption: after enough further work that the pool is no
    # longer empty, so there is something real to prove survives.
    pool_before = await _advance_until_pool_nonempty(run_id, isolated_db)
    _pause_and_resume(client, run_id)

    # Drain the rest of the run to completion, still entirely by hand.
    await task_worker.run_run_until_idle(run_id, _WORKER, db_path=isolated_db)

    final_run = store.get_run(run_id, db_path=isolated_db)
    assert final_run is not None
    assert final_run.status == "completed", final_run.error
    report = store.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    final_ids = {
        str(row["id"])
        for row in store.list_hypotheses(run_id, db_path=isolated_db)
    }
    # The drain (engine_adapter.drain.persist_final_state) writes each
    # hypothesis under its own engine-assigned id, so this is a genuine
    # identity check, not just a non-empty-pool one.
    assert pool_before <= final_ids


# App-level resume launcher over the durable run path.
#
# The streaming resume surface (``run_workflow`` with ``resume=True``) has been
# retired; every real run now resumes through the durable node executor. These
# tests cover the app's resume *launcher* (``runs.lifecycle._launch_resume`` and
# its ``_prepare_resume_state`` decision): an engine checkpoint is a true resume
# that preserves derived data, a legacy mock envelope re-bootstraps a fresh
# offline run, and neither drives blocking run work on the API event loop. The
# durable node executor's own checkpoint/resume mechanics are covered in
# ``test_task_worker_resume.py`` and ``test_engine_tasks.py``.


def _seed_stale_mock_run(run_id: str) -> str:
    """Persist stale mock-era artifacts a re-bootstrap must clear.

    Returns the id of the stale agent-authored hypothesis.
    """
    stale_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Stale agent idea",
            statement="A hypothesis from the retired mock run.",
            created_by_agent="generation",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id, title="Old mock paper", source="pubmed", abstract="x"
        )
    )
    return stale_id


def _save_legacy_mock_checkpoint(run_id: str) -> None:
    """Save a pre-flip mock envelope checkpoint (not engine WorkflowState)."""
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="iteration_1",
            schema_version=1,
            last_event_seq=store.latest_event_seq(run_id),
            state={
                "provider": "mock",
                "run_mode": "express",
                "iteration": 1,
                "config": {"tier": "express"},
            },
        ),
    )


def _save_engine_checkpoint(run_id: str) -> None:
    """Save an engine-tagged checkpoint (``provider="engine"``).

    ``_prepare_resume_state`` only inspects the checkpoint's provider tag to
    decide the resume mode; it never restores the state (the durable worker
    does that later), so a minimal engine-tagged envelope is enough to
    exercise the true-resume branch.
    """
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="engine_task:node",
            schema_version=1,
            last_event_seq=store.latest_event_seq(run_id),
            state={"provider": "engine", "state": {"hypotheses": []}},
        ),
    )


def _assert_rebootstrapped_completed(run_id: str, stale_id: str) -> None:
    """Assert a legacy resume cleared stale data and completed durably.

    (1) the stale mock-era hypothesis is gone, (2) durable engine tasks drove
    the run, (3) fresh hypotheses were generated, ranked, and published.
    """
    final_hyps = store.list_hypotheses(run_id)
    assert stale_id not in {h["id"] for h in final_hyps}
    assert any(
        task.task_type.startswith("engine.")
        for task in store.list_tasks(run_id)
    )
    assert final_hyps
    report = store.get_latest_report(run_id)
    assert report is not None
    assert report["payload"]["leaderboard"]
    final = store.get_run(run_id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value


def _enqueue_paused_blocking_task(run_id: str, db_path: str) -> None:
    """Enqueue one blocking engine task and leave the run paused."""
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.test.blocking",
            inputs={},
            idempotency_key="blocking:0",
        ),
        db_path=db_path,
    )
    store.pause_run_tasks(run_id, db_path=db_path)
    store.update_run_status(run_id, store.RunStatus.PAUSED)


def _install_blocking_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the task executor with a synchronous ~1s blocking cost.

    Stands in for the worker's real synchronous cost: a large json.dumps plus
    a committed SQLite write, run directly on the caller's loop.
    """
    import time as _time

    from app import engine_tasks

    async def _execute(
        _task: Any, *, db_path: str | None = None
    ) -> dict[str, bool]:
        _time.sleep(1.0)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)


async def _worst_loop_stall(stop: asyncio.Event) -> float:
    """Return the worst delay the loop imposed on a 10ms sleep until stopped."""
    import time as _time

    worst = 0.0
    while not stop.is_set():
        started = _time.monotonic()
        await asyncio.sleep(0.01)
        worst = max(worst, _time.monotonic() - started - 0.01)
    return worst


def test_prepare_resume_state_keeps_derived_data_for_engine_checkpoint(
    isolated_db: str,
) -> None:
    """An engine checkpoint is a true resume that preserves derived data.

    The engine persists artifacts only at the final drain, so a mid-run
    interruption left only events + the checkpoint; clearing would discard the
    pre-orchestrator events a true resume never re-emits.
    """
    run = store.create_run("Engine checkpoint resume", "standard", "engine", {})
    stale_id = _seed_stale_mock_run(run.id)
    _save_engine_checkpoint(run.id)
    assert engine_adapter.is_engine_checkpoint(
        store.get_latest_checkpoint(run.id)
    )

    true_resume = _prepare_resume_state(run.id)

    assert true_resume is True
    # Derived data survives (not cleared) and the checkpoint is retained.
    assert stale_id in {h["id"] for h in store.list_hypotheses(run.id)}
    assert store.get_latest_checkpoint(run.id) is not None


async def test_launch_resume_rebootstraps_legacy_mock_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy mock-envelope resume re-runs fresh through the durable path.

    Covers ``runs.lifecycle._launch_resume``'s non-engine-checkpoint fallback
    -- the exact path a production resume of an old ``provider="mock"`` run
    takes after the mock's retirement. There is no persisted engine
    WorkflowState to restore, so the launcher clears the run's stale derived
    data and re-bootstraps it through the durable worker as a fresh offline
    engine run, rather than the old in-process re-derive. Proves (1) the
    stale mock-era artifacts are cleared, (2) the durable bootstrap task
    drives the run, and
    (3) it completes with a ranked, published report.
    """
    _install_fake_engine_llm(monkeypatch)
    run = store.create_run(
        "Legacy mock resume", "express", "mock", {"tier": "express"}
    )

    # Stale mock-era artifacts a re-bootstrap must clear, plus a legacy mock
    # envelope checkpoint (not an engine WorkflowState) -- the fallback trigger.
    stale_id = _seed_stale_mock_run(run.id)
    _save_legacy_mock_checkpoint(run.id)
    assert not engine_adapter.is_engine_checkpoint(
        store.get_latest_checkpoint(run.id)
    )
    # An interrupted run is left non-terminal; the launcher requires that.
    store.update_run_status(run.id, store.RunStatus.PAUSED)

    await runs_lifecycle._launch_resume(run.id)
    await asyncio.gather(*list(runs_lifecycle._resume_tasks))

    # Legacy checkpoint => stale data cleared; re-bootstrapped run completes.
    _assert_rebootstrapped_completed(run.id, stale_id)


async def test_resume_does_not_execute_run_work_on_the_event_loop(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming a run must leave the API's event loop free to serve requests.

    The durable worker does synchronous SQLite writes and serializes whole
    WorkflowState blobs, so driving it with ``create_task`` runs that
    blocking work on the API loop. Starting a run has always handed the
    cohort to a thread; resume did not, so a boot carrying interrupted runs
    stopped answering /health, Railway killed the container mid-run, and the
    next boot inherited one more interrupted run -- a spiral in which runs
    only advanced during the doomed startup window.
    """
    run = store.create_run("loop freedom", "standard", "engine", {})
    _enqueue_paused_blocking_task(run.id, isolated_db)
    _install_blocking_execute(monkeypatch)

    stop = asyncio.Event()
    probe = asyncio.create_task(_worst_loop_stall(stop))
    await runs_lifecycle._launch_resume(run.id)
    await asyncio.gather(*list(runs_lifecycle._resume_tasks))
    stop.set()
    worst_stall = await probe

    assert worst_stall < 0.5, (
        f"event loop stalled {worst_stall:.2f}s while a resumed run executed"
    )


# A final safety block is terminal even when its checkpoint still exists.


@pytest.mark.asyncio
async def test_resume_rejects_final_safety_block_after_finalize_succeeded(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume must preserve a completed finalizer's safety block."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    owner_headers = {"X-Client-ID": "final-safety-block-owner"}
    created = owner.post(
        "/api/runs",
        headers=owner_headers,
        json={
            "research_goal": "Study a final-stage safety block",
            "tier": "express",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    store.update_run_status(
        run_id, store.RunStatus.RUNNING, db_path=isolated_db
    )

    predecessor = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.overview",
            inputs={},
            idempotency_key="completed-overview",
        ),
        db_path=isolated_db,
    )
    previous_claim = store.claim_task(
        "resume-safety-fixture", run_id=run_id, db_path=isolated_db
    )
    assert previous_claim is not None and previous_claim.id == predecessor.id
    assert store.complete_task(
        predecessor.id,
        "resume-safety-fixture",
        {},
        db_path=isolated_db,
    )

    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(
        run_id,
        state,
        stage=f"engine_task:{predecessor.id}",
        db_path=isolated_db,
    )
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_seq = store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{predecessor.id}",
            schema_version=checkpoint["schema_version"],
            last_event_seq=checkpoint["last_event_seq"],
            state={
                **checkpoint["state"],
                "resume_successor": engine_tasks_support.FINALIZE_TASK,
            },
        ),
        db_path=isolated_db,
    )
    finalizer = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{engine_tasks_support.FINALIZE_TASK}:after:{predecessor.id}",
            dependencies=(predecessor.id,),
        ),
        db_path=isolated_db,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))

    async def fake_drain(
        *_: Any, **__: Any
    ) -> tuple[Any, float, dict[str, Any]]:
        drained = SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )
        return drained, 1.0, {}

    async def block_final_report(*_: Any, **__: Any) -> SafetyDecision:
        return SafetyDecision(
            stage="final",
            decision="block",
            reason="Final-stage policy blocked this report.",
        )

    built = report_build._BuiltReport(
        payload={
            "idea_count": 1,
            "leaderboard": [
                {"title": "Safe fixture", "statement": "A report."}
            ],
        },
        markdown="# Final safety fixture",
        facts=[],
        exclusion_tally={},
    )

    async def fake_build_report(*_: Any, **__: Any) -> Any:
        return built

    _install_runtime(monkeypatch).drain_final_state = fake_drain
    monkeypatch.setattr(
        report_finalize, "build_report_content", fake_build_report
    )
    _install_runtime(monkeypatch).screen = block_final_report

    assert await task_worker.run_once(
        "final-safety-worker", run_id=run_id, db_path=isolated_db
    )
    blocked = store.get_run(run_id, db_path=isolated_db)
    completed_finalize = store.get_task(finalizer.id, db_path=isolated_db)
    assert (
        blocked is not None and blocked.status == store.RunStatus.BLOCKED.value
    )
    assert completed_finalize is not None
    assert completed_finalize.status == "completed"
    final_decision = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert len(final_decision) == 1 and final_decision[0]["decision"] == "block"
    assert store.get_latest_report(run_id, db_path=isolated_db) is None

    outsider = owner.post(
        f"/api/runs/{run_id}/resume",
        headers={"X-Client-ID": "different-owner"},
    )
    assert outsider.status_code == 404

    response = owner.post(f"/api/runs/{run_id}/resume", headers=owner_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "run was blocked; create a new run"
    saved = store.get_run(run_id, db_path=isolated_db)
    assert saved is not None and saved.status == store.RunStatus.BLOCKED.value
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert [(task.task_type, task.status) for task in tasks] == [
        ("engine.node.overview", "completed"),
        (engine_tasks_support.FINALIZE_TASK, "completed"),
    ]
    events_response = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=owner_headers
    )
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    safety_event = next(
        event for event in events if event["type"] == "safety.final"
    )
    blocked_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "blocked"
    )
    assert safety_event["seq"] < blocked_event["seq"]
    status_events = [event for event in events if event["type"] == "status"]
    assert status_events[-1]["payload"]["status"] == "blocked"
    assert not any(
        event["payload"].get("status") == "resuming" for event in events
    )


# Safety-decision adjudication and the resulting awaiting-decision status.
#
# Split out of ``test_runs.py`` (which grew past the file-length ceiling once
# these were added) to keep that file to run lifecycle: create, start,
# persistence, reopen.


def _run_with_held_decision(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, str]:
    """Create a run carrying one held intake safety decision."""
    from app import store

    created = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Review a sensitive research protocol"},
    ).json()
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=created["id"],
            stage="intake",
            decision="hold",
            reason="Context requires review.",
            matches=[],
            category="uncertain",
            policy_version="coscientist-safety-v2",
            requires_review=True,
        )
    )
    decision_id = store.list_safety_decisions(created["id"])[0]["id"]
    return created["id"], decision_id


def test_safety_adjudication_is_identified_and_single_use(
    isolated_db: str,
) -> None:
    """A held decision requires an identified reviewer and resolves once."""
    from app import store

    client = _client()
    headers = {"X-Client-ID": "reviewer-1"}
    run_id, decision_id = _run_with_held_decision(client, headers)

    anonymous = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        json={"resolution": "approved"},
    )
    # Ownership middleware hides the existence of another client's run.
    assert anonymous.status_code == 404

    approved = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200
    assert store.safety_stage_is_approved(
        run_id, "intake", "coscientist-safety-v2"
    )

    repeated = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409


def test_held_hypothesis_adjudication_records_without_blocking(
    isolated_db: str,
) -> None:
    """A held-hypothesis hold resolves once and spares the run's lifecycle.

    Unlike intake/final holds, which gate the run's whole goal or report, a
    hypothesis-stage hold concerns one idea the engine already excluded from
    the pool and the report. Approving or rejecting it flips the recorded
    resolution exactly once, and the run itself is left alone.
    """
    from tests._drain_helpers import _held_final_state, _persist

    client = _client()
    headers = {"X-Client-ID": "held-reviewer"}
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Adjudicate hypotheses held for review"},
    ).json()
    run_id = created["id"]
    _persist(
        run_id=run_id, final_state=_held_final_state(), db_path=isolated_db
    )

    # The holds are retrievable through the safety endpoint the UI reads.
    listed = client.get(f"/api/runs/{run_id}/safety", headers=headers)
    assert listed.status_code == 200
    holds = [d for d in listed.json()["safety"] if d["decision"] == "hold"]
    assert len(holds) == 2

    approved = client.post(
        f"/api/runs/{run_id}/safety/{holds[0]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200

    rejected = client.post(
        f"/api/runs/{run_id}/safety/{holds[1]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert rejected.status_code == 200

    by_id = {
        d["id"]: d
        for d in client.get(
            f"/api/runs/{run_id}/safety", headers=headers
        ).json()["safety"]
    }
    assert by_id[holds[0]["id"]]["resolution"] == "approved"
    assert by_id[holds[1]["id"]]["resolution"] == "rejected"
    # Single-use, like every other held decision.
    repeated = client.post(
        f"/api/runs/{run_id}/safety/{holds[0]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409
    # The held ideas were never part of the published output, so neither
    # resolution blocks the run (an intake/final rejection would).
    assert (
        client.get(f"/api/runs/{run_id}", headers=headers).json()["status"]
        == "draft"
    )


def test_paused_run_with_unresolved_review_awaits_decision(
    isolated_db: str,
) -> None:
    """A paused run with an unresolved review decision awaits a person."""
    from app import store
    from app.store import RunStatus

    client = _client()
    headers = {"X-Client-ID": "awaiting-1"}
    run_id, _ = _run_with_held_decision(client, headers)
    store.update_run_status(run_id, RunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 1


def test_paused_run_without_unresolved_review_awaits_nothing(
    isolated_db: str,
) -> None:
    """A paused run with nothing left to review is not awaiting a person."""
    from app import store
    from app.store import RunStatus

    client = _client()
    headers = {"X-Client-ID": "awaiting-2"}
    run = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Explore a mundane pathway"},
    ).json()
    store.update_run_status(run["id"], RunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run['id']}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 0


def test_non_paused_run_with_unresolved_review_awaits_nothing(
    isolated_db: str,
) -> None:
    """A run merely holding a decision, not paused, is not "awaiting"."""
    client = _client()
    headers = {"X-Client-ID": "awaiting-3"}
    # _run_with_held_decision leaves the run in its created 'draft' status.
    run_id, _ = _run_with_held_decision(client, headers)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 0


def test_paused_run_with_resolved_review_awaits_nothing(
    isolated_db: str,
) -> None:
    """A paused run whose only hold was already resolved awaits no one."""
    from app import store
    from app.store import RunStatus

    client = _client()
    headers = {"X-Client-ID": "awaiting-4"}
    run_id, decision_id = _run_with_held_decision(client, headers)
    client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    store.update_run_status(run_id, RunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 0


# Endpoint tests for ``POST /api/runs/{id}/messages/started``.
#
# The Agent's spoken confirmation that a run has begun. Covers the two rows
# one call persists (the scientist's own prompt and the reply), the frame
# order a client reads, and the deterministic announcement that stands in
# whenever no model is reachable -- offline, or a provider that fails.


def _started_run_id() -> str:
    """Create a run (no engine work needed) and return its id."""
    c = _client()
    return str(
        c.post(
            "/api/runs",
            json={
                "research_goal": "Investigate ferroptosis in cancer",
                "tier": "express",
            },
        ).json()["id"]
    )


def _announce(run_id: str, prompt: str = "Start research") -> Any:
    """POST the announcement endpoint for ``run_id``.

    Returns ``Any``: TestClient's own httpx is vendored, so naming its
    Response type here binds the test to a second, incompatible httpx.
    """
    return _client().post(
        f"/api/runs/{run_id}/messages/started", json={"prompt": prompt}
    )


def _start_rows(run_id: str) -> list[store.MessageRow]:
    """Every persisted ``start`` row for the run, in order."""
    return [m for m in store.list_messages(run_id) if m.kind == "start"]


def test_announcement_persists_the_prompt_and_the_reply() -> None:
    """One call leaves both halves of the exchange on the run."""
    rid = _started_run_id()

    res = _announce(rid)

    assert res.status_code == 200
    rows = _start_rows(rid)
    assert [row.sender for row in rows] == ["user", "system"]
    assert rows[0].content == "Start research"
    assert rows[1].content.strip()


def test_announcement_streams_chunks_then_done() -> None:
    """The client reads prose chunks and a terminal ``done`` frame."""
    rid = _started_run_id()

    body = _announce(rid).text

    assert '"type": "chunk"' in body
    assert '"type": "done"' in body
    assert body.index('"type": "chunk"') < body.index('"type": "done"')
    assert '"type": "error"' not in body


def test_offline_announcement_is_marked_as_the_fallback() -> None:
    """With no model reachable the reply is the deterministic one."""
    rid = _started_run_id()

    body = _announce(rid).text

    assert '"fallback": true' in body
    assert _start_rows(rid)[1].meta == {"fallback": True}


def test_live_model_writes_the_announcement(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A reachable provider's own two sentences are what get persisted."""
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (_fake_litellm(["Your session is ", "under way."])).acompletion,
    )

    body = _announce(rid).text

    assert "under way." in body
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Your session is under way."
    assert reply.meta is None


def test_provider_failure_falls_back_without_an_error_frame(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """The run did start, so a failed announcement never reads as one."""
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (
            _fake_litellm([], raise_exc=RuntimeError("provider down"))
        ).acompletion,
    )

    body = _announce(rid).text

    assert '"type": "error"' not in body
    assert '"fallback": true' in body
    assert _start_rows(rid)[1].content.strip()


def test_announcement_404s_for_an_unknown_run() -> None:
    """An id nothing owns is a 404, not an empty announcement."""
    assert _announce("no-such-run").status_code == 404


def _thinking_litellm(reasoning: str, prose: str) -> types.SimpleNamespace:
    """A fake litellm whose stream reasons before it writes, as DeepSeek does.

    ``tests._client.fake_litellm`` streams content deltas only, so the
    reasoning channel needs its own stand-in.
    """

    async def _chunk_stream() -> AsyncIterator[Any]:
        for field, text in (
            ("reasoning_content", reasoning),
            ("content", prose),
        ):
            delta = SimpleNamespace(content=None, reasoning_content=None)
            setattr(delta, field, text)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _acompletion(**_kwargs: Any) -> AsyncIterator[Any]:
        return _chunk_stream()

    return types.SimpleNamespace(acompletion=_acompletion)


def test_reasoning_is_relayed_and_kept_with_the_reply(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """The announcement is a turn, so it shows and keeps its thinking."""
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (
            _thinking_litellm(
                "The run exists, so this confirms it.", "Under way."
            )
        ).acompletion,
    )

    body = _announce(rid).text

    assert '"type": "reasoning"' in body
    assert body.index('"type": "reasoning"') < body.index('"type": "chunk"')
    reply = _start_rows(rid)[1]
    assert reply.meta == {"reasoning": "The run exists, so this confirms it."}


def _thinking_only_then_answered_litellm(
    reasoning: str, prose: str, calls: list[dict[str, Any]]
) -> types.SimpleNamespace:
    """A fake litellm whose first stream reasons and writes nothing.

    The second call (thinking off, per ``calls``) answers normally --
    mirrors production 2026-09-06, where a stream relayed ~68k characters
    of chain of thought and ended with no answer at all.
    """

    async def _reasoning_only_stream() -> AsyncIterator[Any]:
        delta = SimpleNamespace(content=None, reasoning_content=reasoning)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _answered_stream() -> AsyncIterator[Any]:
        delta = SimpleNamespace(content=prose, reasoning_content=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _acompletion(**kwargs: Any) -> AsyncIterator[Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            return _reasoning_only_stream()
        return _answered_stream()

    return types.SimpleNamespace(acompletion=_acompletion)


def test_thinking_only_announcement_retries_before_the_fallback(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A stream that reasoned and wrote nothing gets a real answer, not copy.

    Confirms the retry the interview stream also gets (see
    ``test_interviews_model.test_thinking_only_turn_retries_once_with_
    thinking_off``): the announcement's own fixed fallback text is
    reserved for when the retry also comes back empty, not for every
    thinking-only stream.
    """
    rid = _started_run_id()
    fake_process_mode.online()
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    calls: list[dict[str, Any]] = []
    install_completion_backend(
        monkeypatch,
        (
            _thinking_only_then_answered_litellm(
                "brainstorming candidates at length...",
                "Research is under way.",
                calls,
            )
        ).acompletion,
    )

    body = _announce(rid).text

    assert len(calls) == 2
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Research is under way."
