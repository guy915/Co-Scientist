"""A redact decision must remove the content, not just label it.

Both content gates recorded ``decision="redact"`` and then proceeded with the
untouched goal and the untouched report markdown, so the label was the only
thing redaction changed. These pin the effect: the matched spans are gone from
every persisted and emitted copy, and a redaction naming no span holds for
review rather than passing the original through.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import report_render, safety, store
from app.report_render import ReportRequest, finalize_report, make_emitter
from app.safety import REDACTED_PLACEHOLDER, SafetyDecision
from app.safety_redaction import redact_matched_spans, redact_payload_text

_DUAL_USE_GOAL = (
    "Map the dual-use risk surface of engineered metabolic pathways."
)


def test_redact_matched_spans_replaces_every_occurrence() -> None:
    """Each matched span is replaced, case-insensitively, everywhere."""
    text = "A Dual-Use programme is dual-use twice over."
    out = redact_matched_spans(text, ["dual-use"])
    assert "dual-use" not in out.lower()
    assert out.count(REDACTED_PLACEHOLDER) == 2


def test_redact_payload_text_walks_nested_structures() -> None:
    """Nested payload strings are redacted, non-strings left alone."""
    payload: dict[str, Any] = {
        "a": "a dual-use claim",
        "b": [{"c": "dual-use again"}, 3],
        "d": 7,
    }
    out = redact_payload_text(payload, ["dual-use"])
    assert "dual-use" not in repr(out).lower()
    assert out["d"] == 7
    assert out["b"][1] == 3


def test_unredactable_redaction_holds_for_review() -> None:
    """A redaction naming no span cannot be applied, so it must not pass."""
    decision = SafetyDecision(
        stage="final", decision="redact", reason="model verdict", matches=[]
    )
    resolved = safety.ensure_redactable(decision)
    assert resolved.decision == "hold"
    assert resolved.requires_review is True


def _seed_dual_use_run(db_path: str) -> Any:
    """Persist an offline-backed run whose goal trips the dual-use rule."""
    return store.create_run(
        _DUAL_USE_GOAL,
        "express",
        "engine",
        {"tier": "express"},
        store.RunCreateOptions(
            client_id="redaction-test",
            llm_backend="offline",
            db_path=db_path,
        ),
    )


async def test_final_redaction_scrubs_report_markdown_and_payload(
    isolated_db: str,
) -> None:
    """The published report carries no copy of the redacted span."""
    run = _seed_dual_use_run(isolated_db)
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="A benign restatement",
            statement="Metabolic flux rises under the tested condition.",
        ),
        db_path=isolated_db,
    )
    emit = make_emitter(run.id, db_path=isolated_db)
    events = [
        event
        async for event in finalize_report(
            run.id,
            ReportRequest(
                research_goal=_DUAL_USE_GOAL,
                run_mode="express",
                provider="engine",
                db_path=isolated_db,
            ),
            emit,
        )
    ]

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(d["decision"] == "redact" for d in decisions)
    saved = store.get_latest_report(run.id, db_path=isolated_db)
    assert saved is not None
    assert "dual-use" not in saved["markdown_text"].lower()
    assert REDACTED_PLACEHOLDER in saved["markdown_text"]
    assert "dual-use" not in repr(saved["payload"]).lower()
    # The audit record names the matched span on purpose -- a decision that
    # cannot say what it matched is not auditable. Every *content* copy of
    # the run, live and replayed, must be scrubbed.
    content = [e for e in events if not e["type"].startswith("safety.")]
    assert "dual-use" not in repr(content).lower()
    replayed = [
        e
        for e in store.list_events(run.id, db_path=isolated_db)
        if not e["type"].startswith("safety.")
    ]
    assert replayed
    assert "dual-use" not in repr(replayed).lower()


def test_report_render_exposes_the_redaction_helper() -> None:
    """The finalize path owns one redaction seam, not an inline copy."""
    assert callable(report_render._redacted_report)


@pytest.mark.parametrize("matches", [["dual-use"], ["DUAL-USE"]])
def test_redaction_is_case_insensitive(matches: list[str]) -> None:
    """Policy matches are reported verbatim; casing must not defeat them."""
    assert "dual" not in redact_matched_spans(_DUAL_USE_GOAL, matches).lower()
