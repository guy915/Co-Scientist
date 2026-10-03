"""The per-idea negative-critique rollup (REVIEW-CRITIQUES-ROLLUP-001).

Google's published per-hypothesis documents close on a ``Critiques``
section -- "Here's a summary of the negative critiques from the
reviews:" over a synthesized bulleted rollup (corpus R10-8, the KIRA6
output). It is a per-idea rollup, distinct from the run-level meta-review
critique and from the verbatim ``All reviews`` block above it. Nothing
here calls a model: the synthesis was already done by the full review,
whose ``critical_flaws`` and ``validated_risks`` parts this gathers under
the published heading.
"""

from __future__ import annotations

from app.report.markdown.reviews import _render_critiques_rollup
from tests._review_block_helpers import _row, _summary_row


def test_critiques_rollup_renders_the_published_heading_and_label() -> None:
    """R10-8: the per-idea negative-critique section and its lead line."""
    lines = _render_critiques_rollup([_summary_row()])

    assert lines[0] == "#### Critiques"
    assert "Here's a summary of the negative critiques from the reviews:" in (
        lines
    )


def test_critiques_rollup_gathers_the_two_negative_summary_parts() -> None:
    """It rolls up critical flaws and validated risks, and nothing else.

    The other six parts are the idea's positives, verdict and
    feasibility; they stay in the Reviews summary block, not this
    negative-only rollup.
    """
    lines = _render_critiques_rollup([_summary_row()])

    assert "- The pore benchmark is wrong." in lines
    assert "- Parameter covariance is untreated." in lines
    assert "- The theoretical basis is right." not in lines
    assert "- Squarely on the goal." not in lines


def test_critiques_rollup_handles_a_string_valued_part() -> None:
    """A downgraded json_object model may answer a list part as one string."""
    lines = _render_critiques_rollup(
        [
            _row(
                "full_review",
                {"reviews_summary": {"critical_flaws": "Single prose flaw."}},
            )
        ]
    )

    assert "- Single prose flaw." in lines


def test_critiques_rollup_prefers_the_latest_full_review() -> None:
    """A recurrent review supersedes the earlier full review's summary."""
    stale = _row(
        "full_review",
        {"reviews_summary": {"critical_flaws": ["Stale flaw."]}},
    )
    fresh = _row(
        "recurrent_review",
        {"reviews_summary": {"critical_flaws": ["Fresh flaw."]}},
    )
    lines = _render_critiques_rollup([stale, fresh])

    assert "- Fresh flaw." in lines
    assert "- Stale flaw." not in lines


def test_critiques_rollup_renders_nothing_when_absent() -> None:
    """Omitted whole when the mature cascade never reached the idea.

    No ``reviews_summary`` at all, and a summary present but carrying
    neither negative part, both render nothing rather than an empty
    heading (R14-23).
    """
    assert _render_critiques_rollup([]) == []
    assert (
        _render_critiques_rollup(
            [_row("full_review", {"reviews_summary": {"conclusion": "Ship."}})]
        )
        == []
    )
    assert _render_critiques_rollup([_row("review", {})]) == []
