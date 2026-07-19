"""Tests for the audience context loader."""

from __future__ import annotations

from app import audience


def test_sbi_ucd_returns_nonempty_context() -> None:
    text = audience.audience_context("sbi_ucd")
    assert "SBI" in text
    assert len(text) > 0


def test_other_audiences_return_empty() -> None:
    assert audience.audience_context("general") == ""
    assert audience.audience_context("google") == ""
    assert audience.audience_context(None) == ""
    assert audience.audience_context("bogus") == ""
    assert audience.audience_reference("general") == ""
    assert audience.audience_reference(None) == ""
    assert audience.audience_chat_context("google") == ""


def test_run_path_context_stays_within_budget() -> None:
    """The everywhere-tier stays small, because it is paid for per call.

    audience_context rides run_setup_guidance into generation, reflection,
    evolution, meta-review and every tournament comparison, and ranking is
    roughly quadratic in the hypothesis count. Depth belongs in the
    reference, which only chat loads. The bound is deliberately loose --
    it catches someone pasting the full lab overview in here, not ordinary
    editing.
    """
    text = audience.audience_context("sbi_ucd")
    assert len(text) < 4000, "run-path context has grown into a document"


def test_chat_context_carries_the_reference_too() -> None:
    """Chat is one call per question, so it gets profile plus reference."""
    profile = audience.audience_context("sbi_ucd")
    reference = audience.audience_reference("sbi_ucd")
    combined = audience.audience_chat_context("sbi_ucd")
    assert profile in combined
    assert reference in combined
    # The reference is the deeper of the two, and is chat-only.
    assert len(reference) > len(profile)


def test_maintainer_comments_do_not_reach_the_model() -> None:
    """Both files open with an HTML comment aimed at whoever edits them.

    It explains injection sites and token budgets -- noise in a prompt, and
    confusing noise at that, since it discusses the cost of the very call it
    would be riding in.
    """
    for text in (
        audience.audience_context("sbi_ucd"),
        audience.audience_reference("sbi_ucd"),
    ):
        assert "<!--" not in text
        assert "token" not in text.split("\n")[0].lower()
    # The prose survives the strip.
    assert audience.audience_context("sbi_ucd").startswith("# Research")


def test_reference_defines_the_group_s_own_methods() -> None:
    """A chat question about cSTAR/MRA vocabulary is answerable from it."""
    reference = audience.audience_reference("sbi_ucd").lower()
    for term in ("dynamic phenotype descriptor", "state transition vector"):
        assert term in reference


def test_pattern_and_values_exposed() -> None:
    assert audience.VALID_AUDIENCES == ("general", "google", "sbi_ucd")
    assert audience.AUDIENCE_PATTERN == "^(general|google|sbi_ucd)$"
