"""Tests for citing evidence by bracketed passage number.

Split out of ``test_claim_verifier.py`` when this file passed the
module-size budget. The prompt no longer shows an evidence id to cite
(see ``claims.verifier._render_passages``); the judge instead cites a
passage's bracketed position in the rendered list, and ``claims.span``
resolves that number back to the passage it names -- these tests pin
both the successful resolution and the drop-and-log path for a number
naming a passage that was never shown.
"""

from __future__ import annotations

import logging
import types
from typing import Any

import pytest

from app.claims import EntailmentLabel, EvidencePassage, assess_claim
from app.claims.span import _locate_all
from app.claims.verifier import make_llm_assessor

from ._llm_fake_backend import install_completion_backend


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    """Force every call in this file to miss the engine's response cache.

    See ``test_claim_verifier.py``'s identical fixture for why.
    """
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_completion(content: str) -> Any:
    """Return a fake provider answer yielding ``content``."""

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, completion: Any) -> None:
    """Install the fake engine completion backend."""
    install_completion_backend(monkeypatch, completion)


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_citation_by_passage_number_resolves_to_that_passage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict citing "3" (a string) resolves to the third shown passage.

    The prompt no longer shows an evidence id to cite (see
    ``_render_passages``); the judge cites the passage's bracketed
    number instead, exactly as ``claims.span`` already resolves.
    """
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '[{"passage": "3", "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        ),
    )
    passages = [
        EvidencePassage(evidence_id="ev-a", text="Unrelated filler one."),
        EvidencePassage(evidence_id="ev-b", text="Unrelated filler two."),
        _PASSAGE,
    ]
    assessor, _ = make_llm_assessor("deepseek/deepseek-chat")
    draft = assessor(
        "Kinase X inhibition reduces tumor growth.",
        passages,
    )
    spans = _locate_all(draft.supporting, passages)
    assert [s.evidence_id for s in spans] == [_PASSAGE.evidence_id]


def test_out_of_range_passage_number_is_dropped_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A citation naming a passage never shown is dropped, not trusted.

    The prompt only shows one passage here, so "9" is out of range; the
    quote is also nowhere in that passage, so the fallback verbatim
    search cannot rescue it either -- this is a genuine drop, not a
    mis-cited-but-locatable quote.
    """
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '[{"passage": 9, "quote": "cures every disease"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with caplog.at_level(logging.WARNING, logger="app.claims.span"):
        result = assess_claim(
            "Kinase X inhibition reduces tumor growth.",
            [_PASSAGE],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()
    assert "could not be located" in caplog.text
