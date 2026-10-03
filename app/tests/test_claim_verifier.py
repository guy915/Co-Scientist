from __future__ import annotations

import types
from typing import Any

import pytest

from app.claims import EntailmentLabel, EvidencePassage, assess_claim
from app.claims.verifier import _entailment_prompt, make_llm_assessor

from ._llm_fake_backend import install_completion_backend


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    # Repeated claims use different fake replies; cache isolation prevents
    # replaying an earlier test verdict.
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_completion(content: str) -> Any:

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, completion: Any) -> None:
    install_completion_backend(monkeypatch, completion)


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
    # json_object mode permits a single citation object instead of an array.
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

    async def _raising(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    _install(monkeypatch, _raising)
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth in AML.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.verification_method == "deterministic_lexical"
    assert result.supporting_passages


def test_malformed_json_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _fake_completion("not json at all"))
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth in AML.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS


def test_no_passages_is_insufficient_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def _should_not_be_called(**_kwargs: Any) -> Any:
        raise AssertionError("the provider must not be called")

    _install(monkeypatch, _should_not_be_called)
    assessor, _ = make_llm_assessor("deepseek/deepseek-chat")
    draft = assessor("some claim", [])
    assert draft.label is EntailmentLabel.INSUFFICIENT
    assert draft.verification_method == "no_evidence"


def test_prompt_renders_evidence_before_the_claim() -> None:
    # Put recurring evidence before changing claims so provider caching sees a
    # stable prefix.
    prompt = _entailment_prompt(
        "Kinase X inhibition reduces tumor growth.", [_PASSAGE]
    )
    assert prompt.index("EVIDENCE:") < prompt.index("CLAIM:")


def test_prompt_size_is_bounded_by_the_retrieved_passages() -> None:
    # Chunk-based retrieval bounds prompts independently of full article length.
    from app.claims.assessor import _DEFAULT_RETRIEVAL_TOP_K
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
    assert len(passages) > _DEFAULT_RETRIEVAL_TOP_K

    from app.claims import retrieve_passages

    retrieved = retrieve_passages(claim, passages)
    rendered = "\n\n".join(p.text for p in retrieved)
    # Exclude separator bytes from this bound; each overlap prefix contributes
    # one joining space.
    per_chunk_bound = CHUNK_MAX_CHARS + CHUNK_OVERLAP_CHARS + 1
    bound = _DEFAULT_RETRIEVAL_TOP_K * per_chunk_bound
    assert len(rendered) <= bound


def test_call_reaches_the_engine_completion_boundary_with_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    # Entailment is classification; unrestricted reasoning can consume the
    # entire answer budget.
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
    # Models with mandatory reasoning need the smallest supported capped tier
    # rather than a literal disable.
    # Raising output floors only funds longer reasoning without an answer.
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
    from co_scientist.constants import MODEL_PRICING
    from co_scientist.llm.admission import free_policy as free_catalog

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
    free_catalog.install_catalog_reader(
        free_catalog.CatalogReader(lambda: catalog)
    )
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
    # Thinking already starts disabled; retain plain re-asks for parse failures.
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
