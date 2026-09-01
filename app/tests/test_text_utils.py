"""Tests for app.text_utils.readable_experiment_summary (R14-20)."""

from app.text_utils import readable_experiment_summary


def test_collapses_numbered_steps_and_bolded_criteria_to_one_line() -> None:
    text = (
        "1. Script the pipeline.\n"
        "2. Calibrate against ground truth.\n"
        "**Go:** AUC >= 0.8.\n"
        "**No-Go:** AUC < 0.6."
    )
    assert readable_experiment_summary(text) == (
        "Script the pipeline. Calibrate against ground truth."
        " Go: AUC >= 0.8. No-Go: AUC < 0.6."
    )


def test_plain_paragraph_passes_through_unchanged() -> None:
    assert (
        readable_experiment_summary("A single free-text paragraph.")
        == "A single free-text paragraph."
    )


def test_empty_string_returns_empty() -> None:
    assert readable_experiment_summary("") == ""


def test_whitespace_only_returns_empty() -> None:
    assert readable_experiment_summary("   \n  \n") == ""


def test_leaves_bold_text_other_than_go_no_go_markers_untouched() -> None:
    """Only the two known Go/No-Go markers are unbolded, nothing else."""
    text = "1. Use the **primary** readout.\n**Go:** it clears threshold."
    assert readable_experiment_summary(text) == (
        "Use the **primary** readout. Go: it clears threshold."
    )
