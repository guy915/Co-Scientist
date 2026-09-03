"""Tests for the deterministic offline LLM router.

Covers the router's passthrough behavior for non-``offline/`` models, the
schema-valid shape of ``offline_acompletion``'s responses for a
representative set of fail-loud schemas, its determinism contract (byte-
identical output for identical calls, differing output for differing
prompts), the idempotency of ``install_offline_router``, and an
end-to-end run of the real compiled graph that answers every call through
the runtime router rather than ``tests._llm_fake``'s monkeypatch-based
fake (that test still monkeypatches ``litellm.acompletion``, but only to
record and prove nothing escapes the router -- not to generate content).
"""

import json
from typing import Any

import jsonschema
import litellm
import pytest

from co_scientist import llm_request, offline_llm
from co_scientist.agents.reflection.review_gate import _disposition_for
from co_scientist.agents.reflection.review_helpers import (
    _review_from_response,
)
from co_scientist.agents.supervisor.supervisor_decision import (
    _DECISION_SCHEMA,
)
from co_scientist.schemas.generation import GENERATION_SCHEMA
from co_scientist.schemas.meta_review_schema import META_REVIEW_SCHEMA
from co_scientist.schemas.ranking import RANKING_SCHEMA
from co_scientist.schemas.review import REVIEW_BATCH_SCHEMA, REVIEW_SCHEMA
from tests._offline_helpers import (
    isolate_offline_router,
    make_offline_generator,
)


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time."""
    isolate_offline_router(monkeypatch)


def test_is_offline_model_checks_the_prefix() -> None:
    """Only ``offline/``-prefixed model names are routed."""
    assert offline_llm.is_offline_model(offline_llm.DEFAULT_OFFLINE_MODEL)
    assert offline_llm.is_offline_model("offline/anything")
    assert not offline_llm.is_offline_model("gemini/gemini-2.5-flash")
    assert not offline_llm.is_offline_model("deepseek/deepseek-chat")


async def test_router_passthrough_calls_original_for_non_offline_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-``offline/`` model reaches the original acompletion callable."""
    calls: list[dict[str, Any]] = []

    async def _stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "stub-result"

    monkeypatch.setattr(litellm, "acompletion", _stub)
    offline_llm.install_offline_router()

    result = await litellm.acompletion(
        model="gemini/gemini-2.5-flash",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == "stub-result"
    assert len(calls) == 1
    assert calls[0]["model"] == "gemini/gemini-2.5-flash"


async def test_router_answers_offline_model_without_reaching_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``offline/`` model never reaches the original acompletion."""
    calls: list[dict[str, Any]] = []

    async def _stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "stub-result"

    monkeypatch.setattr(litellm, "acompletion", _stub)
    offline_llm.install_offline_router()

    response = await litellm.acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert not calls
    assert response.choices[0].message.content


@pytest.mark.parametrize(
    ("schema_name", "schema", "prompt"),
    [
        (
            "hypothesis_generation",
            GENERATION_SCHEMA["schema"],
            "Generate hypotheses for how protein X folds.",
        ),
        (
            "ranking_judgment",
            RANKING_SCHEMA["schema"],
            "Judge hypothesis A against hypothesis B.",
        ),
        (
            "supervisor_allocation",
            _DECISION_SCHEMA["schema"],
            (
                "Live shared memory:\n"
                '{"iteration": 0, "pool_grew_since_proximity": false}'
            ),
        ),
    ],
)
async def test_offline_acompletion_returns_schema_valid_json(
    schema_name: str, schema: dict[str, Any], prompt: str
) -> None:
    """``offline_acompletion`` fills every fail-loud schema validly."""
    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema},
        },
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)
    jsonschema.validate(instance=parsed, schema=schema)


async def test_offline_meta_review_fills_main_research_directions() -> None:
    """R14-27: the required narrative-directions field is never left empty.

    ``main_research_directions`` is required (unlike the roadmap-step
    fields ``test_offline_optional_fields.py`` hints in), so the generic
    filler must already populate it via one leaf draw -- this is what lets
    ``report_markdown_meta_review``'s renderer show a populated section on
    every offline run, including every curated demo, with no
    ``_OPTIONAL_FIELD_HINTS`` entry needed.
    """
    schema = META_REVIEW_SCHEMA["schema"]

    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[{"role": "user", "content": "Meta-review this pool."}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "meta_review", "schema": schema},
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    jsonschema.validate(instance=parsed, schema=schema)
    assert isinstance(parsed["main_research_directions"], str)
    assert parsed["main_research_directions"]


async def test_offline_acompletion_sizes_batch_review_to_hypothesis_count() -> (
    None
):
    """The batch-review "reviews" array is sized from the prompt's markers.

    ``review_node`` maps array entries back to hypotheses (by their
    ``hypothesis_index`` when valid, else by position), so a short response
    is invalid; this proves the ``_ARRAY_LENGTH_HINTS`` wiring ported from
    the test fake still recovers the count from "**Hypothesis N:**" markers
    in the prompt.
    """
    schema = REVIEW_BATCH_SCHEMA["schema"]
    prompt = (
        "**Hypothesis 1:** first.\n"
        "**Hypothesis 2:** second.\n"
        "**Hypothesis 3:** third.\n"
    )

    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "hypothesis_batch_review",
                "schema": schema,
            },
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    jsonschema.validate(instance=parsed, schema=schema)
    assert len(parsed["reviews"]) == 3
    # Every review's string leaves are unique within this one response, even
    # though the whole response is a deterministic function of its inputs:
    # the dedup reducer collapses hypotheses with equal normalized text, so
    # colliding leaves across array entries would be a real defect. The
    # entries no longer echo the hypothesis text (audit E15), so uniqueness
    # is checked on the summary leaf instead.
    texts = [review["review_summary"] for review in parsed["reviews"]]
    assert len(set(texts)) == len(texts)


async def test_offline_review_scores_clear_the_viable_gate() -> None:
    """An offline review's scores land past ``NEEDS_REVISION_SCORE``.

    Every offline review's every score used to default to exactly
    ``NEEDS_REVISION_SCORE`` (the initial gate's ``<=`` boundary), so
    ``review_gate._disposition_for`` classified every offline-reviewed
    hypothesis ``needs_revision`` and none ever reached ``viable`` --
    which is what gates Reflection's full/simulation/recurrent cascade
    (``mature_reviews.reviews_needed``). Runs the real response through
    the real converter and gate, rather than asserting on raw score
    values, so a change to either boundary is what this test actually
    exercises.
    """
    schema = REVIEW_SCHEMA["schema"]

    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[{"role": "user", "content": "Review this hypothesis."}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "hypothesis_review", "schema": schema},
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    jsonschema.validate(instance=parsed, schema=schema)
    review = _review_from_response(parsed)
    assert (
        _disposition_for(review, ("scientific_soundness", "novelty"))
        == "viable"
    )


def test_review_score_fields_matches_the_schema_criteria() -> None:
    """``_REVIEW_SCORE_FIELDS`` must track the schema's scored axes exactly.

    It hand-mirrors ``schemas.review``'s private ``_SCORE_CRITERIA`` (a
    deliberate mirror across the module's own privacy boundary -- see the
    comment above ``_REVIEW_SCORE_FIELDS``), so a ninth scored axis added
    to the schema without a matching update here would silently default
    through ``_SCALAR_DEFAULTS`` to ``NEEDS_REVISION_SCORE`` and re-break
    the viable gate the surrounding tests pin fixed. Importing the private
    name is deliberate: this test exists to catch exactly the drift that
    privacy boundary would otherwise hide.
    """
    from co_scientist.schemas.review import _SCORE_CRITERIA

    assert set(offline_llm._REVIEW_SCORE_FIELDS) == {
        *_SCORE_CRITERIA,
        "overall_score",
    }


async def test_offline_filler_supplies_the_required_category() -> None:
    """Making ``category`` required made the offline filler deterministic (K7).

    The filler satisfies every required property, so a required category
    comes back filled -- and identically filled on every identical call.
    While the field was optional the filler omitted it, and an offline run
    produced hypotheses with no category at all.
    """
    kwargs: dict[str, Any] = {
        "model": offline_llm.DEFAULT_OFFLINE_MODEL,
        "messages": [
            {"role": "user", "content": "Generate hypotheses for goal G."}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "hypothesis_generation",
                "schema": GENERATION_SCHEMA["schema"],
            },
        },
    }

    first = json.loads(
        (await offline_llm.offline_acompletion(**kwargs))
        .choices[0]
        .message.content
    )
    second = json.loads(
        (await offline_llm.offline_acompletion(**kwargs))
        .choices[0]
        .message.content
    )

    assert first["hypotheses"], "filler must produce at least one hypothesis"
    for entry in first["hypotheses"]:
        assert isinstance(entry["category"], str)
        assert entry["category"]
    assert (
        first["hypotheses"][0]["category"]
        == second["hypotheses"][0]["category"]
    )


async def test_offline_acompletion_is_deterministic_for_identical_calls() -> (
    None
):
    """Identical (model, prompt, schema) calls produce identical content."""
    kwargs = {
        "model": offline_llm.DEFAULT_OFFLINE_MODEL,
        "messages": [{"role": "user", "content": "Explain the mechanism."}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "hypothesis_generation",
                "schema": GENERATION_SCHEMA["schema"],
            },
        },
    }

    first = await offline_llm.offline_acompletion(**kwargs)
    second = await offline_llm.offline_acompletion(**kwargs)

    assert first.choices[0].message.content == second.choices[0].message.content


async def test_offline_acompletion_differs_for_different_prompts() -> None:
    """Different prompts (same model and schema) produce different content."""
    base_kwargs = {
        "model": offline_llm.DEFAULT_OFFLINE_MODEL,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "hypothesis_generation",
                "schema": GENERATION_SCHEMA["schema"],
            },
        },
    }

    first = await offline_llm.offline_acompletion(
        messages=[{"role": "user", "content": "Prompt A"}], **base_kwargs
    )
    second = await offline_llm.offline_acompletion(
        messages=[{"role": "user", "content": "Prompt B"}], **base_kwargs
    )

    assert first.choices[0].message.content != second.choices[0].message.content


def test_install_offline_router_is_idempotent() -> None:
    """A second ``install_offline_router`` call does not double-wrap."""
    offline_llm.install_offline_router()
    routed_once = litellm.acompletion
    supports_once = llm_request._supports_json_schema_response_format

    offline_llm.install_offline_router()

    assert litellm.acompletion is routed_once
    assert llm_request._supports_json_schema_response_format is supports_once


async def test_install_offline_router_idempotency_does_not_lose_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling install twice still passes non-offline calls through once.

    Guards against a subtler double-wrap than object identity alone would
    catch: even if a second install produced a new (but equally-shaped)
    wrapper, a real double-wrap would invoke the underlying stub twice per
    call. This asserts exactly one invocation.
    """
    calls: list[dict[str, Any]] = []

    async def _stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "stub-result"

    monkeypatch.setattr(litellm, "acompletion", _stub)
    offline_llm.install_offline_router()
    offline_llm.install_offline_router()

    await litellm.acompletion(
        model="gemini/gemini-2.5-flash",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert len(calls) == 1


def _install_recording_router(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    """Install the offline router over a recording passthrough stub.

    Before installing the router, ``litellm.acompletion`` is replaced with a
    recording stub; the router captures it as its passthrough target for any
    non-offline model. The stub still answers through ``offline_acompletion``
    so a run is unaffected if something did leak, but recording every call it
    receives turns "the run completed" into actual proof that zero calls
    escaped the offline router rather than an assumption resting on
    ``supervisor_model_name``'s default.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        The list every escaped non-offline call would be appended to.
    """
    escaped_calls: list[dict[str, Any]] = []

    async def _recording_original(**kwargs: Any) -> Any:
        escaped_calls.append(kwargs)
        return await offline_llm.offline_acompletion(**kwargs)

    monkeypatch.setattr(litellm, "acompletion", _recording_original)
    offline_llm.install_offline_router()
    return escaped_calls


async def test_end_to_end_offline_generator_run_yields_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real graph run through the runtime router, no fake content path.

    Mirrors the shape of ``tests/test_integration_pipeline.py`` but installs
    only the runtime router (``install_offline_router``); every response is
    produced by the production ``offline_acompletion``, never by
    ``tests._llm_fake``'s monkeypatch-based fake. MCP is genuinely unavailable
    (no server listening) and literature review is explicitly disabled, so only
    ``call_llm``/``call_llm_json`` are exercised -- ``supervisor_model_name``
    defaults to ``model_name``, so every model name the graph reads is the same
    offline one.
    """
    escaped_calls = _install_recording_router(monkeypatch)

    result = await make_offline_generator().generate_hypotheses(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
        stream=False,
    )

    assert not escaped_calls, (
        "a call reached the original acompletion instead of being routed "
        f"to offline_acompletion: {escaped_calls[0].get('model')!r}"
    )

    hypotheses = result["hypotheses"]
    assert isinstance(hypotheses, list)
    assert len(hypotheses) >= 2
    for hyp in hypotheses:
        assert isinstance(hyp, dict)
        assert hyp["text"]
        assert isinstance(hyp["reviews"], list) and hyp["reviews"]

    assert result["meta_review"]["summary"]
    assert result["research_overview"]["overview"]
    assert result["metrics"]["llm_calls"] > 0
