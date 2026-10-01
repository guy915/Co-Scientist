"""Tests for the LLM (NLI) entailment assessor (app/claim_verifier.py).

The assessor is exercised end-to-end against a real provider by the golden run;
here the litellm boundary is faked so the prompt/parse/guard behavior is proven
offline: a valid verdict with a real quote yields a located support span, a
hallucinated quote is downgraded, and any provider/parse failure falls back to
the deterministic assessor rather than breaking grounding. The unfounded-
CONTRADICTS guard (subject overlap + negation-marker check) moved to
``test_claim_verifier_contradiction.py`` when this file passed the
module-size budget, and the cite-by-passage-number tests to
``test_claim_verifier_citations.py`` for the same reason.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.claim_verifier import _entailment_prompt, make_llm_assessor
from app.claims import EntailmentLabel, EvidencePassage, assess_claim


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    """Force every call in this file to miss the engine's response cache.

    ``claim_verifier`` now routes through ``call_llm_json`` with caching
    on (by design -- see its module docstring), and several tests here
    reuse the exact same claim/passage pair with a *different* faked
    reply to prove a different code path. Without this, the second such
    test would silently replay the first test's cached response instead
    of calling the fake at all.
    """
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_completion(content: str) -> Any:
    """Return a stand-in for litellm.acompletion yielding ``content``."""

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, completion: Any) -> None:
    """Patch the engine's completion boundary (``litellm.acompletion``).

    ``app.claim_verifier`` routes through ``co_scientist.llm.call_llm_json``
    now (see the module docstring), so the boundary to fake is the
    engine's own -- exactly what every other engine LLM test patches.
    """
    import litellm

    monkeypatch.setattr(litellm, "acompletion", completion)


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_assessor_id_names_the_model() -> None:
    _, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    assert assessor_id == "llm:deepseek/deepseek-chat"


def test_valid_supports_verdict_locates_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supports verdict citing a real quote yields a located support span."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '[{"passage": 1, "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.verification_method == "model_primary"
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert (
        _PASSAGE.text[span.start : span.end]
        == span.quote
        == "reduces tumor growth"
    )


def test_partial_verdict_locates_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial verdict citing a real quote yields a located support span."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "partial", "supporting": '
            '[{"passage": 1, "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition halts tumor growth entirely.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.PARTIAL
    span = result.supporting_passages[0]
    assert _PASSAGE.text[span.start : span.end] == span.quote


def test_hallucinated_quote_downgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supports verdict whose quote is absent becomes insufficient."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '[{"passage": 1, "quote": "cures every disease"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_supporting_as_single_object_not_wrapped_in_list_still_locates_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A "supporting" object, not wrapped in a list, still yields a span.

    ``json_object`` mode (no schema enforcement) lets a model plausibly
    write the single supporting citation directly rather than wrapping it
    in a one-element array; the entailment call must recover it rather
    than silently treating the claim as having no supporting evidence.
    """
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '{"passage": 1, "quote": "reduces tumor growth"}, '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.quote == "reduces tumor growth"


def test_provider_error_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising provider falls back to the deterministic assessor."""

    async def _raising(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    _install(monkeypatch, _raising)
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    # The deterministic fallback still finds strong topical support here.
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth in AML.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.verification_method == "deterministic_lexical"
    assert result.supporting_passages  # deterministic located a span


def test_malformed_json_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unparseable model output falls back rather than trusting a bad parse."""
    _install(monkeypatch, _fake_completion("not json at all"))
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth in AML.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    # Falls back; deterministic finds support for this overlapping pair.
    assert result.label is EntailmentLabel.SUPPORTS


def test_no_passages_is_insufficient_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no candidate passages the assessor short-circuits."""

    async def _should_not_be_called(**_kwargs: Any) -> Any:
        raise AssertionError("litellm.acompletion must not be called")

    _install(monkeypatch, _should_not_be_called)
    assessor, _ = make_llm_assessor("deepseek/deepseek-chat")
    draft = assessor("some claim", [])
    assert draft.label is EntailmentLabel.INSUFFICIENT
    assert draft.verification_method == "no_evidence"


def test_prompt_renders_evidence_before_the_claim() -> None:
    """Evidence precedes the claim so recurring passages form a stable prefix.

    Regression for the production ordering (claim first) that defeated the
    response cache: two calls sharing every retrieved passage but citing a
    different claim shared no cacheable prefix, since the varying part came
    first.
    """
    prompt = _entailment_prompt(
        "Kinase X inhibition reduces tumor growth.", [_PASSAGE]
    )
    assert prompt.index("EVIDENCE:") < prompt.index("CLAIM:")


def test_prompt_size_is_bounded_by_the_retrieved_passages() -> None:
    """Rendered evidence never exceeds the retrieval budget's own bound.

    Regression for whole-article "passages": five 40k-char articles used to
    mean a ~200k-char prompt. With chunking, retrieval hands the prompt at
    most ``top_k`` chunks, each near ``CHUNK_MAX_CHARS`` (plus the small
    overlap), so the evidence block is bounded by ``k * (max + overlap)``
    regardless of how long the source articles are.
    """
    from app.claims_assessor import _DEFAULT_RETRIEVAL_TOP_K
    from app.evidence_chunking import (
        CHUNK_MAX_CHARS,
        CHUNK_OVERLAP_CHARS,
        chunk_evidence_passage,
    )

    claim = "Kinase X inhibition reduces tumor growth in AML cell lines."
    body = (
        claim + " Filler discussion sentence unrelated to the claim. "
    ) * 400
    passages: list[EvidencePassage] = []
    for i in range(3):
        passages.extend(
            chunk_evidence_passage(
                f"article-{i}",
                head_text=f"Title {i}.",
                body_text=body,
                source="pubmed",
                url=f"https://example.org/{i}",
            )
        )
    assert len(passages) > _DEFAULT_RETRIEVAL_TOP_K  # retrieval must narrow

    from app.claims import retrieve_passages

    retrieved = retrieve_passages(claim, passages)
    rendered = "\n\n".join(p.text for p in retrieved)
    # +1 per chunk for the overlap prefix's joining space (see
    # CHUNK_OVERLAP_CHARS); the "\n\n".join separators are additional and
    # deliberately excluded -- this bounds the evidence text itself.
    per_chunk_bound = CHUNK_MAX_CHARS + CHUNK_OVERLAP_CHARS + 1
    bound = _DEFAULT_RETRIEVAL_TOP_K * per_chunk_bound
    assert len(rendered) <= bound


def test_call_reaches_the_engine_completion_boundary_with_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The assessor's call is sent to the resolved model via the engine seam.

    Thinking/reasoning-argument shaping is the engine's own responsibility
    now (``co_scientist.llm.request.thinking``, exercised by the engine's own
    tests) -- this only pins that this module's call reaches that seam at
    all, with the model this assessor was built for.
    """
    seen: dict[str, Any] = {}

    async def _capturing_completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        message = types.SimpleNamespace(
            content='{"label": "insufficient", "supporting": [], '
            '"contradicting": []}'
        )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    _install(monkeypatch, _capturing_completion)
    assessor, _ = make_llm_assessor("deepseek/deepseek-v4-flash")
    assessor("some claim", [_PASSAGE])

    assert seen["model"] == "deepseek/deepseek-v4-flash"


def test_entailment_call_disables_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entailment call carries thinking disabled from the first attempt.

    A production run (b82f9162, 2026-09-06) spent an 18000-token budget
    entirely on reasoning and answered nothing -- judging a claim against
    a handful of passages is classification, not a task a chain of
    thought earns its keep on (root AGENTS.md gotcha).
    """
    seen: dict[str, Any] = {}

    async def _capturing_completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        message = types.SimpleNamespace(
            content='{"label": "insufficient", "supporting": [], '
            '"contradicting": []}'
        )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    _install(monkeypatch, _capturing_completion)
    assessor, _ = make_llm_assessor("deepseek/deepseek-v4-flash")
    assessor("some claim", [_PASSAGE])

    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}


def test_entailment_call_on_the_free_chain_does_not_disable_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deployed free-chain primary never receives a bare disable.

    Production run b82f9162 (2026-09-06 04:39:30 UTC): every batched
    entailment call against ``openrouter/minimax/minimax-m3:free``
    (``app.config``'s default model on every tier) failed on both
    attempts with ``"Reasoning is mandatory for this endpoint and cannot
    be disabled"``, because ``enable_thinking=False`` reached the wire as
    a literal ``reasoning: {"enabled": False}``. The engine now redirects
    that to the smallest reasoning tier the gateway exposes for a model
    declared unable to honour a disable (``ModelProfile
    .reasoning_can_disable``) -- and bounds it in the request itself.
    Funding the redirect instead was tried and lost: production measured
    ~20-21k reasoning tokens against the 18000-token floor (run 323ff72c,
    2026-09-06 06:57 UTC) and then 24547 against the 24000-token floor
    raised to answer that (run 6760ce63), each raise met by a
    proportionally longer chain of thought. Entailment is a
    classification judgement, so the wire now carries a cap on the
    reasoning and the ordinary thinking floor on the budget.
    """
    from co_scientist.constants import (
        MINIMAL_REASONING_MAX_TOKENS,
        THINKING_FLOOR_MAX_TOKENS,
    )

    seen: dict[str, Any] = {}

    async def _capturing_completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        message = types.SimpleNamespace(
            content='{"label": "insufficient", "supporting": [], '
            '"contradicting": []}'
        )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    _install(monkeypatch, _capturing_completion)
    from co_scientist.constants_pricing import MODEL_PRICING
    from co_scientist.llm.admission import free_catalog

    catalog = {
        model.removeprefix("openrouter/"): {
            "pricing": {
                "prompt": str(price.prompt_usd_per_million),
                "completion": str(price.completion_usd_per_million),
            },
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        }
        for model, price in MODEL_PRICING.items()
        if model.startswith("openrouter/")
    }
    monkeypatch.setattr(free_catalog, "_snapshot", None)
    monkeypatch.setattr(free_catalog, "_fetch_catalog", lambda: catalog)
    assessor, _ = make_llm_assessor("openrouter/minimax/minimax-m3:free")
    assessor("some claim", [_PASSAGE])

    assert seen["extra_body"]["reasoning"] == {
        "enabled": True,
        "max_tokens": MINIMAL_REASONING_MAX_TOKENS,
    }
    assert seen["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


def test_entailment_answerless_first_attempt_still_yields_a_real_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parse failure on attempt 1 still yields a real verdict, not a fallback.

    With thinking disabled from the first attempt, ``max_attempts=3``
    keeps a plain re-ask available for a schema/parse failure -- the
    escalation ladder's own top rung (turning thinking off) is moot here
    since it already is off.
    """
    calls = {"n": 0}

    async def _flaky_completion(**_kwargs: Any) -> Any:
        calls["n"] += 1
        content = (
            "not valid json"
            if calls["n"] == 1
            else '{"label": "supports", "supporting": '
            '[{"passage": 1, "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        )
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    _install(monkeypatch, _flaky_completion)
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert calls["n"] == 2
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.assessor == assessor_id
