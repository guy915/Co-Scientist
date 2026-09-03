"""R12-15/MO-4: per-assumption support renders as Google's published prose.

``docs/CORPUS-EXTRACTION.md:4135-4141``
(``validated-outputs/kira6-detailed-output-validated.md``'s "Reasoning
about assumptions") prints each assumption's support as "Plausible:",
"Plausible, but requires careful investigation:", or "Unknown:" -- not
this schema's closed enum name (``supported``/``uncertain``/
``likely_false``, ``engine/src/co_scientist/schemas/review.py``). Two of
the three values mirror that wording directly; the third does not --
Google's own exemplar never marks an assumption the evidence actively
contradicts, only ones nothing has tested yet, so ``likely_false`` keeps
an honest label of its own rather than a mismatched "Unknown". See
``_ASSUMPTION_SUPPORT_LABELS``'s own comment in ``drain_reviews.py``.
"""

from __future__ import annotations

from app.engine_adapter.drain_reviews import (
    _append_full_critique,
    _assumption_line,
)


def test_supported_renders_as_the_published_plausible_label() -> None:
    line = _assumption_line(
        {"assumption": "KIRA6 inhibits IRE1a.", "support": "supported"}
    )

    assert line == "Assumption (Plausible): KIRA6 inhibits IRE1a."


def test_uncertain_renders_as_the_published_careful_investigation_label() -> (
    None
):
    line = _assumption_line(
        {
            "assumption": "AML cells are more ER-stress sensitive.",
            "support": "uncertain",
        }
    )

    assert line == (
        "Assumption (Plausible, but requires careful investigation):"
        " AML cells are more ER-stress sensitive."
    )


def test_likely_false_renders_as_implausible_not_the_published_unknown() -> (
    None
):
    """A genuine negative verdict must not read as merely "Unknown".

    Google's "Unknown:" marks an assumption nothing has tested yet
    ("limited safety data exists... unknown and needs experiments to
    verify"), not one the evidence contradicts -- reusing that word for
    `likely_false` ("the evidence points against it",
    full_review.md/deep_verification.md) would understate the verdict.
    """
    line = _assumption_line(
        {
            "assumption": "The drug is non-toxic at the proposed dose.",
            "support": "likely_false",
        }
    )

    assert line == (
        "Assumption (Implausible): The drug is non-toxic at the proposed dose."
    )
    assert "Unknown" not in line


def test_missing_support_falls_back_to_unrated() -> None:
    line = _assumption_line({"assumption": "An untagged assumption."})

    assert line == "Assumption (unrated): An untagged assumption."


def test_reasoning_is_appended_after_the_label() -> None:
    line = _assumption_line(
        {
            "assumption": "KIRA6 inhibits IRE1a.",
            "support": "supported",
            "reasoning": "Prior work in other cell types supports this.",
        }
    )

    assert line == (
        "Assumption (Plausible): KIRA6 inhibits IRE1a. —"
        " Prior work in other cell types supports this."
    )


def test_an_unnamed_assumption_renders_nothing() -> None:
    assert _assumption_line({"support": "supported"}) is None


def test_the_full_review_critique_carries_the_published_labels() -> None:
    critique = "\n".join([])
    lines: list[str] = []
    _append_full_critique(
        lines,
        {
            "correctness": "Sound.",
            "assumptions": [
                {"assumption": "A", "support": "supported"},
                {"assumption": "B", "support": "uncertain"},
                {"assumption": "C", "support": "likely_false"},
            ],
        },
    )
    critique = "\n".join(lines)

    assert "Assumption (Plausible): A" in critique
    assert (
        "Assumption (Plausible, but requires careful investigation): B"
        in critique
    )
    assert "Assumption (Implausible): C" in critique
