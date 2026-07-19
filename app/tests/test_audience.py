"""Tests for the audience context loader.

The contract these pin changed deliberately. The loader used to serve a short
hand-written profile to the run path and a longer reference to chat, both
summarised from the group's document rather than taken from it. What reached
a run was therefore a paraphrase that had dropped the group's people, its
mathematics, and its collaborators. The document is now shipped verbatim and
in full to every surface, so these tests assert fidelity rather than brevity.
"""

from __future__ import annotations

from pathlib import Path

from app import audience


def _document() -> str:
    """Read the bundled document straight from disk, bypassing the loader."""
    path = Path(audience.__file__).parent / "content" / "sbi_ucd_context.md"
    return path.read_text(encoding="utf-8")


def test_context_is_the_document_verbatim() -> None:
    """The scientist's document reaches the model unaltered.

    This is the whole point of the loader: not "some context about SBI" but
    exactly the text the group wrote. Any transformation -- summarising,
    truncating, reformatting -- is the regression.
    """
    assert audience.audience_context("sbi_ucd") == _document().strip()


def test_every_surface_gets_the_same_document() -> None:
    """Chat, the interview, and the run path all read one source.

    They were once served different texts, which is how a run could carry a
    thinner briefing than a chat answer about the same group.
    """
    assert audience.audience_chat_context(
        "sbi_ucd"
    ) == audience.audience_context("sbi_ucd")


def test_other_audiences_return_empty() -> None:
    for value in ("general", "google", None, "bogus"):
        assert audience.audience_context(value) == ""
        assert audience.audience_chat_context(value) == ""


def test_document_carries_the_substance_the_summary_dropped() -> None:
    """Guards the specific content a hand-written summary loses first.

    Each of these was verifiably absent while the summary was shipping: the
    team beyond the two PIs, the formal definitions behind the group's own
    methods, the collaborators, and the institutional facts.
    """
    text = audience.audience_context("sbi_ucd")
    for person in ("Kolch", "Imoto", "Kashdan", "Sevrin", "Carmody", "Borodin"):
        assert person in text, f"team member {person} missing from context"
    for concept in (
        "State Transition Vector",
        "Dynamic Phenotype Descriptor",
        "Modular Response Analysis",
        "Bayesian",
    ):
        assert concept in text, f"method {concept} missing from context"
    for collaborator in ("Kramnik", "Schwartz", "Westerhoff"):
        assert collaborator in text, f"collaborator {collaborator} missing"
    assert "Science Foundation Ireland" in text


def test_document_keeps_its_mathematics() -> None:
    """The formulae survive: they are why the reference exists at all."""
    text = audience.audience_context("sbi_ucd")
    assert "r_{ij}" in text
    assert "\\mathbf{n}_s" in text


def test_encoding_is_repaired() -> None:
    """No mojibake reaches the prompt.

    The source document arrived double-encoded (em dashes as 'a-euro-"'). It
    is repaired on the way in, so the model reads punctuation rather than
    escape soup.
    """
    text = audience.audience_context("sbi_ucd")
    assert "â€”" not in text
    assert "—" in text


def test_pattern_and_values_exposed() -> None:
    assert audience.VALID_AUDIENCES == ("general", "google", "sbi_ucd")
    assert audience.AUDIENCE_PATTERN == "^(general|google|sbi_ucd)$"
