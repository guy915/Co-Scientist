"""What the chat can see about a run's progress and its finished report.

Covers ``app.qa_run_state``: the live-progress facts gathered while a run
executes, the report synthesis carried once it completes, and the idea
index that replaces dumping every idea into the prompt.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from app import qa_run_state, store
from app.store.models import RunRow


def _event(activity: str | None, event_type: str = "engine") -> dict[str, Any]:
    payload = {"activity": activity} if activity else {}
    return {"seq": 1, "type": event_type, "payload": payload, "created_at": 1.0}


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------


def test_consecutive_events_of_one_activity_collapse_to_one_step() -> None:
    # A tournament wave is dozens of events of one kind; rendered raw it
    # would be the whole step narrative and crowd out everything before it.
    events = [
        _event("drafting"),
        _event("tournament"),
        _event("tournament"),
        _event("tournament"),
        _event("review"),
    ]
    assert qa_run_state._collapse_steps(events) == [
        "drafting",
        "tournament",
        "review",
    ]


def test_step_narrative_names_unclassified_events_by_type() -> None:
    # 'other' covers both a genuinely unclassifiable event and every
    # control-plane one, and the latter has a perfectly good name already.
    steps = qa_run_state._collapse_steps([_event("other", "lifecycle")])
    assert steps == ["lifecycle"]


def test_status_events_are_not_steps() -> None:
    assert qa_run_state._collapse_steps([_event(None, "status")]) == []


# ---------------------------------------------------------------------------
# gather_run_progress
# ---------------------------------------------------------------------------


def _seed_running_run() -> RunRow:
    """Create a real run row (the autouse isolated_db fixture owns the file)."""
    run = store.create_run("A goal", "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING)
    return dataclasses.replace(run, status="running")


def test_elapsed_is_measured_from_execution_start_not_draft_creation() -> None:
    # A plan drafted before lunch and started after it did not spend the
    # lunch break working, so the run row's created_at is the wrong clock.
    run = _seed_running_run()
    store.append_event(run.id, "lifecycle", {"event": "queued"})
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {"ideas": 2}, conn, now=time.time() + 120.0
        )

    assert progress.elapsed_seconds is not None
    assert 110.0 < progress.elapsed_seconds < 130.0
    assert progress.idea_count == 2
    assert progress.is_running


def test_a_run_that_never_started_reports_no_elapsed_time() -> None:
    run = _seed_running_run()
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {}, conn, now=time.time()
        )

    assert progress.elapsed_seconds is None
    assert "not started yet" in qa_run_state.render_progress(progress)


def test_only_meta_review_notes_count_as_conclusions() -> None:
    # Per-hypothesis reviews are critiques of one idea; the meta-review is
    # the only synthesis the store holds before a report exists.
    run = _seed_running_run()
    reviews = [
        {"reviewer_agent": "review", "summary": "one idea's critique"},
        {"reviewer_agent": "meta_review", "summary": "the pattern so far"},
    ]
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, reviews, {}, conn, now=time.time()
        )

    assert progress.conclusions == ["the pattern so far"]


def test_a_finished_run_stops_its_elapsed_clock() -> None:
    # The clock stops at completion; a run finished an hour ago still
    # reports how long it took, not how long ago it was.
    run = _seed_running_run()
    store.append_event(run.id, "lifecycle", {"event": "queued"})
    run = dataclasses.replace(
        run, status="completed", completed_at=time.time() + 60.0
    )
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {}, conn, now=time.time() + 9_000.0
        )

    assert progress.elapsed_seconds is not None
    assert progress.elapsed_seconds < 120.0
    assert not progress.is_running


def test_progress_renders_the_current_step_only_while_running() -> None:
    running = qa_run_state.RunProgress(
        status="running",
        elapsed_seconds=90.0,
        idea_count=4,
        evidence_count=7,
        match_count=2,
        active_task="engine.node.ranking",
        completed_tasks=11,
        queued_tasks=3,
        steps=["drafting", "tournament"],
        conclusions=[],
    )
    rendered = qa_run_state.render_progress(running)

    assert "Ideas generated so far: 4" in rendered
    assert "engine.node.ranking" in rendered
    assert "drafting, tournament" in rendered
    # A finished run has no current step, and saying "between steps" of one
    # that ended reads as a run still going.
    finished = qa_run_state.render_progress(
        qa_run_state.RunProgress(
            status="completed",
            elapsed_seconds=90.0,
            idea_count=4,
            evidence_count=7,
            match_count=2,
            active_task=None,
            completed_tasks=11,
            queued_tasks=0,
            steps=[],
            conclusions=[],
        )
    )
    assert "Current step" not in finished
    assert "completed" in finished


# ---------------------------------------------------------------------------
# report facts
# ---------------------------------------------------------------------------


def _payload() -> dict[str, Any]:
    return {
        "idea_count": 22,
        "hypothesis_count": 8,
        "verified_count": 3,
        "evidence_count": 47,
        "research_overview": {
            "summary": "The run converged on lipid repair.",
            "specific_aims": ["Aim one", "Aim two"],
        },
        "meta_review": {
            "common_strengths": ["mechanistic detail"],
            "common_weaknesses": ["thin controls"],
            "strategic_recommendations": [
                {
                    "focus_area": "Validation",
                    "recommendation": "run isogenic controls",
                    "justification": "because",
                },
                "a bare recommendation",
            ],
        },
        "agent_insights": {"key_findings": ["GPX4-independent repair"]},
    }


def test_report_facts_carry_the_synthesis_and_every_count() -> None:
    facts = qa_run_state.build_report_facts(_payload())

    assert facts.summary == "The run converged on lipid repair."
    assert facts.aims == ["Aim one", "Aim two"]
    assert facts.key_findings == ["GPX4-independent repair"]
    assert facts.weaknesses == ["thin controls"]
    # The three idea counts name different things and must not collapse
    # into one another.
    assert facts.counts["idea_count"] == 22
    assert facts.counts["hypothesis_count"] == 8
    assert facts.counts["verified_count"] == 3


def test_structured_and_bare_recommendations_both_render() -> None:
    facts = qa_run_state.build_report_facts(_payload())
    assert facts.recommendations == [
        "Validation: run isogenic controls",
        "a bare recommendation",
    ]


def test_report_facts_tolerate_a_payload_with_nothing_in_it() -> None:
    # A run whose generation failed still finalizes, and its report's
    # sections are empty rather than absent.
    facts = qa_run_state.build_report_facts({})
    assert qa_run_state.render_report(facts).startswith("Ideas explored: 0")


def test_rendered_report_carries_each_section() -> None:
    rendered = qa_run_state.render_report(
        qa_run_state.build_report_facts(_payload())
    )
    assert "Overview: The run converged on lipid repair." in rendered
    assert "- Aim one" in rendered
    assert "Recommended next steps" in rendered


# ---------------------------------------------------------------------------
# idea index
# ---------------------------------------------------------------------------


def test_idea_index_names_every_idea_not_just_the_leaders() -> None:
    # The index is what tells the model which ideas it can look up; an idea
    # it cannot see exists is one it will never search for.
    ideas = [
        {"title": f"Idea {n}", "elo_rating": 1200 + n, "status": "active"}
        for n in range(12)
    ]
    index = qa_run_state.render_idea_index(ideas)
    assert index.count("\n") == 11
    assert "- Idea 11 (Elo 1211, active)" in index


def test_idea_index_says_how_many_it_could_not_name() -> None:
    ideas = [{"title": f"Idea {n}"} for n in range(45)]
    index = qa_run_state.render_idea_index(ideas)
    assert "...and 5 more (search to reach them)" in index


def test_idea_index_carries_a_verification_verdict_when_there_is_one() -> None:
    index = qa_run_state.render_idea_index(
        [
            {
                "title": "H",
                "status": "active",
                "verification_verdict": "supported",
            }
        ]
    )
    assert "supported" in index


def test_a_half_empty_recommendation_renders_without_a_dangling_colon() -> None:
    # A model that puts the whole recommendation in `focus_area` must not
    # render as a heading followed by a colon and nothing at all.
    facts = qa_run_state.build_report_facts(
        {
            "meta_review": {
                "strategic_recommendations": [
                    {
                        "focus_area": "Centre on homeostasis",
                        "recommendation": "",
                    },
                    {"focus_area": "", "recommendation": "Run the controls"},
                ]
            }
        }
    )
    assert facts.recommendations == [
        "Centre on homeostasis",
        "Run the controls",
    ]
