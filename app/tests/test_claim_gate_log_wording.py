"""The claim gate's log lines agree with the report's verified count.

The gate fails a hypothesis for any unsupported categorical claim, while the
report badges it "Unverified" only when no claim at all has support. The log
used to call every gate failure "published unverified", so one run logged
"2 of 5 hypotheses published unverified" beside a report with
``verified_count=5`` (run 34b29088, 2026-09-27).
"""

from __future__ import annotations

import logging

import pytest

from app import store
from app.claims import ClaimAssessment, EntailmentLabel
from app.claims.grounding import persist_grounding
from tests._store_helpers import _add


def _assessment(claim: str, label: EntailmentLabel) -> ClaimAssessment:
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=(),
        contradicting_passages=(),
        assessor="deterministic",
    )


def test_partly_supported_failure_is_not_logged_as_unverified(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    run = store.create_run("gate wording", "standard", "engine", {})
    partly = _add(run.id, "Partly supported", "A causes B.", isolated_db)
    bare = _add(run.id, "Unsupported", "C causes D.", isolated_db)
    caplog.set_level(logging.INFO, logger="app.claims.grounding")

    result = persist_grounding(
        run.id,
        [
            (
                partly,
                [
                    (_assessment("A binds X.", EntailmentLabel.SUPPORTS), ""),
                    (
                        _assessment(
                            "A causes B.", EntailmentLabel.INSUFFICIENT
                        ),
                        "",
                    ),
                ],
            ),
            (
                bare,
                [
                    (
                        _assessment(
                            "C causes D.", EntailmentLabel.INSUFFICIENT
                        ),
                        "",
                    )
                ],
            ),
        ],
        db_path=isolated_db,
    )

    assert result.blocked_ids == {partly, bare}
    assert (
        f"Hypothesis {partly} did not clear the claim gate "
        "(published with unsupported claims flagged)"
    ) in caplog.text
    assert (
        f"Hypothesis {bare} did not clear the claim gate (published unverified)"
    ) in caplog.text
    assert "2 of 2 hypotheses failed (1 published unverified" in caplog.text
    assert "No hypothesis cleared the claim gate" not in caplog.text
