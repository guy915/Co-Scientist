"""Holds our rendered prompts to the eight Google published verbatim.

Google published exactly eight prompts (paper appendix Figures A.1-A.8).
They are transcribed byte-exact in ``docs/CORPUS-EXTRACTION.md`` Appendix A.
``prompts/templates/README.md`` maps each to the template derived from
it. That mapping records *derivation*, never line-by-line preservation --
which is how an instruction ended up stated in the opposite of the
published sense and stayed that way for months.

**The contract these tests enforce.** Every assertable fragment of a
published prompt must appear, as a normalized literal substring, in the
prompt our real builders render, and the fragments must appear in
published order. Normalization is whitespace collapse, case folding, and
removal of markdown emphasis -- nothing more. **A paraphrase does not
pass.** Rewording a published sentence "in our own voice" is exactly the
drift this file exists to stop; if a published sentence genuinely cannot
be carried, the divergence belongs in ``templates/README.md`` and in an
explicit skip here, not in a loosened matcher.

Matching runs against the *rendered* prompt, not the static template: published
text can live in a Python builder rather than in the markdown (until 2026-09-06
``prompts/ranking.py::_format_review_context`` carried the "Disregard these
scores" sentence that ``ranking.md`` had no literal match for -- both are now
deleted, and the sentence is static text in ``ranking_pairwise.md`` and
``ranking_debate.md``), and template text can be a slot that renders nothing.
``tests/_published_prompt_fixtures.py`` drives the real builders with a fully
populated fixture; ``test_every_slot_rendered`` fails first if that fixture
leaves a slot empty, so a fixture bug cannot masquerade as a fidelity gap.

Fragments, not whole sentences, are the unit: a published sentence with a
``{placeholder}`` in the middle is split at the placeholder and each side
matched separately, since our slot names differ from Google's. Leading
enumerators (``1.``, ``a.``, ``*``) are stripped before matching, so a
renumbered step fails on its content rather than on its number --
numbering divergence is reported by the ordering test instead.
"""

from __future__ import annotations

import functools
import re
import unicodedata

import pytest

from tests._published_corpus import corpus_available, published_prompt
from tests._published_prompt_fixtures import Rendered
from tests._published_prompt_renders import render_all, unrendered_slots

# Every check here reads the corpus, and the presence parametrization
# reads it at collection time -- where ``pytest.skip`` would be a
# collection error rather than a skip. Both guards below are therefore
# needed, not one belt-and-braces pair.
pytestmark = pytest.mark.skipif(
    not corpus_available(),
    reason="engine checked out without the reference corpus",
)

PUBLISHED_STEMS = (
    "generation-01-hypothesis-after-literature-review",
    "generation-02-hypothesis-after-scientific-debate",
    "reflection-03-generate-observations",
    "ranking-04-pairwise-comparison",
    "ranking-05-comparison-via-scientific-debate",
    "evolution-06-feasibility-improvement",
    "evolution-07-out-of-the-box-thinking",
    "meta-review-08-meta-review-generation",
)

_FENCE = re.compile(r"^```.*?$", re.MULTILINE)
_ENUMERATOR = re.compile(r"^\s*(?:\d+\.|[a-z]\.|[*-])\s+")
# Split before a numbered/lettered/bulleted item or a new capitalized
# sentence, but never immediately after an enumerator's own period -- the
# two negative lookbehinds keep "1." and "a." attached to what follows.
_SENTENCE_SPLIT = re.compile(
    r'(?<!\s\d\.)(?<![\s(][a-z]\.)(?<=[.:"])\s+'
    r"(?=(?:\d+\.\s|[a-z]\.\s|[*-]\s|[A-Z#]))"
)
# A paper placeholder. The closing "}" is optional-by-alternation because
# reflection-03's final line opens "{provide reasoning..." and closes with
# ")" -- a typo in the published source, reproduced verbatim in the
# extract.
_PLACEHOLDER = re.compile(r"\{[^{}]*?[})]")
_EMPHASIS = re.compile(r"[*`]+")
# Typographic quotes, spelled by code point: ruff rejects the literal
# characters as visually ambiguous (RUF001).
_QUOTE_FOLDS = (
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2018", "'"),
    ("\u2019", "'"),
)


def _normalize(text: str) -> str:
    """Fold a prompt to the form both sides are compared in."""
    folded = unicodedata.normalize("NFKC", text)
    for curly, straight in _QUOTE_FOLDS:
        folded = folded.replace(curly, straight)
    folded = _EMPHASIS.sub("", folded)
    return re.sub(r"\s+", " ", folded).strip().lower()


def _fenced_body(text: str) -> str:
    """Return the prompt body inside the extract's code fence."""
    parts = _FENCE.split(text)
    assert len(parts) >= 2, "published extract has no fenced prompt body"
    return parts[1].strip("\n")


def _drop_caption(body: str) -> str:
    """Drop the figure caption the paper prints above each prompt.

    Two of the eight are rendered as one run-on paragraph, so their
    caption is a prefix of the first line rather than a line of its own.
    """
    first, _, rest = body.partition("\n")
    if not first.startswith("Prompt for"):
        return body
    if " You are " in first:
        return first[first.index(" You are ") + 1 :] + (
            "\n" + rest if rest else ""
        )
    return rest


def _join_continuations(body: str) -> list[str]:
    """Join lines the paper wrapped mid-sentence back into one unit."""
    units: list[str] = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if units and not units[-1].endswith((".", ":", "!", "?")):
            units[-1] = f"{units[-1]} {line}"
        else:
            units.append(line)
    return units


def _strip_enumerators(unit: str) -> str:
    """Remove every leading list marker from one unit."""
    previous = ""
    while previous != unit:
        previous = unit
        unit = _ENUMERATOR.sub("", unit)
    return unit.strip()


def _is_assertable(fragment: str) -> bool:
    """True for a fragment specific enough to assert on.

    A one-word fragment is too weak to prove anything, except when it is
    a section label the published prompt ends with a colon ("Goal:").
    """
    return len(fragment.split()) >= 2 or fragment.endswith(":")


def _fragments(unit: str) -> list[str]:
    """Split one published unit at its placeholders into matchable parts."""
    parts = (_normalize(part) for part in _PLACEHOLDER.split(unit))
    return [part for part in parts if part and _is_assertable(part)]


@functools.cache
def published_fragments(stem: str) -> tuple[str, ...]:
    """Return one published prompt's assertable fragments, in order."""
    body = _drop_caption(_fenced_body(published_prompt(stem)))
    body = body.replace("\\*", "*")
    fragments: list[str] = []
    for unit in _join_continuations(body):
        for piece in _SENTENCE_SPLIT.split(unit):
            fragments.extend(_fragments(_strip_enumerators(piece)))
    return tuple(fragments)


def find_fragment(text: str, fragment: str, start: int = 0) -> int:
    """Locate a published fragment at a token boundary in ``text``.

    A plain substring search lets a short published label match inside a
    longer word of ours -- "Instructions:" inside "Additional
    instructions:" -- which reports a missing section as a reordered one.
    The fragment must therefore begin where a word does.
    """
    pattern = re.compile(r"(?<![0-9a-z])" + re.escape(fragment))
    match = pattern.search(text, start)
    return match.start() if match else -1


def contains_fragment(text: str, fragment: str) -> bool:
    """True when ``text`` carries the published fragment."""
    return find_fragment(text, fragment) >= 0


@functools.cache
def _rendered() -> dict[str, Rendered]:
    return render_all()


def _union(stem: str) -> str:
    """The normalized text of every counterpart of one published prompt."""
    return _normalize(_rendered()[stem].union)


def _primary(stem: str) -> str:
    """The normalized text of the counterpart that owns published order."""
    return _normalize(_rendered()[stem].primary.text)


def _presence_cases() -> list[tuple[str, str]]:
    if not corpus_available():
        return []
    return [
        (stem, fragment)
        for stem in PUBLISHED_STEMS
        for fragment in published_fragments(stem)
    ]


# --- harness guards ----------------------------------------------------


@pytest.mark.parametrize("stem", PUBLISHED_STEMS)
def test_every_slot_rendered(stem: str) -> None:
    """No counterpart may reach a fidelity check with an unfilled slot.

    An unfilled ``{{slot}}`` would read as a missing published sentence,
    so this failing means the fixture is wrong, not the prompt.
    """
    leftovers = {
        part.name: unrendered_slots(part.text)
        for part in _rendered()[stem].counterparts
        if unrendered_slots(part.text)
    }
    assert not leftovers, f"fixture left slots unrendered: {leftovers}"


@pytest.mark.parametrize("stem", PUBLISHED_STEMS)
def test_published_prompt_yields_fragments(stem: str) -> None:
    """Extraction must produce fragments; zero would pass every check."""
    assert len(published_fragments(stem)) >= 5


# --- (b) ABSENT: published text missing from our rendered prompt -------


@pytest.mark.parametrize(
    ("stem", "fragment"),
    _presence_cases(),
    ids=lambda value: value[:60],
)
def test_published_fragment_is_present(stem: str, fragment: str) -> None:
    """Every published fragment appears verbatim in our rendered prompt."""
    assert contains_fragment(_union(stem), fragment), (
        f"published {stem} states {fragment!r}; our rendered prompt does not"
    )


# --- (c) REORDERED: published ordering our prompt breaks ---------------


@pytest.mark.parametrize("stem", PUBLISHED_STEMS)
def test_published_order_is_preserved(stem: str) -> None:
    """Fragments we do carry appear in the published order.

    Only fragments actually present are checked, so a missing sentence is
    reported once (by the presence test) rather than twice.
    """
    text = _primary(stem)
    cursor = 0
    out_of_order: list[str] = []
    for fragment in published_fragments(stem):
        if not contains_fragment(text, fragment):
            continue
        index = find_fragment(text, fragment, cursor)
        if index < 0:
            out_of_order.append(fragment)
            continue
        cursor = index + len(fragment)
    assert not out_of_order, (
        f"{stem}: present but out of published order: {out_of_order}"
    )


# --- (c) CONTRADICTED: wording that states the published opposite ------
#
# One guard per inversion found by the audit. Each asserts the
# contradicting wording is *absent*; none of them is satisfied by adding
# the published sentence alongside the contradiction, which is how the
# ranking scores instruction survived its first fix attempt.


def test_ranking_does_not_tell_the_judge_to_consider_the_scores() -> None:
    """A.4 says disregard the review scores, so we must not say consider."""
    text = _union("ranking-04-pairwise-comparison")
    assert "consider these scores" not in text


def test_observation_start_phrase_is_not_narrowed() -> None:
    """A.3 mandates a literal opening phrase for each observation.

    The published phrase is 'would we see this observation if the
    hypothesis was true:'. Appending a qualifier changes the literal the
    reviewer is told to emit, so the instruction diverges from the
    published protocol even where nothing parses the emitted phrase.
    """
    text = _union("reflection-03-generate-observations")
    assert (
        "would we see this observation if the hypothesis was true, and"
        " not otherwise:" not in text
    )


def test_summary_start_phrase_is_not_replaced() -> None:
    """A.3's summary step mandates its own literal opening phrase."""
    text = _union("reflection-03-generate-observations")
    assert (
        "taken as a whole, does the hypothesis explain observations that"
        " known mechanisms cannot:" not in text
    )


def test_meta_review_does_not_order_per_proposal_evaluation() -> None:
    """A.8 forbids evaluating individual proposals.

    Our template carries that directive and then asks for a per-idea
    comparison table, which is the evaluation the directive forbids.
    """
    text = _union("meta-review-08-meta-review-generation")
    assert "compare the candidate ideas against each other" not in text


# --- (d) OURS WITHOUT COUNTERPART: invented text, delete candidates ----
#
# Not contradictions: the published prompt states no opposite. Each is a
# mechanic we added that the published prompt leaves to its own
# termination rule, kept as a guard so a deletion is verified rather than
# assumed.


def test_debate_does_not_order_the_panel_to_discard_two_ideas() -> None:
    """A.2 asks for three hypotheses and never orders a cull.

    The published procedure converges on one finalized idea at
    termination, so narrowing is implicit in it; ordering the panel to
    drop two of the three within a turn makes a within-turn elimination
    out of what the paper leaves to the debate's own end condition.
    """
    text = _union("generation-02-hypothesis-after-scientific-debate")
    assert "filter out the worse 2" not in text
