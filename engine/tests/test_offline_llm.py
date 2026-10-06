from __future__ import annotations

import json
import uuid
from typing import Any

import jsonschema
import litellm
import pytest

from co_scientist import models
from co_scientist.agents.reflection.review import _review_from_response
from co_scientist.agents.reflection.review_gate import _disposition_for
from co_scientist.agents.supervisor.supervisor_decision import _DECISION_SCHEMA
from co_scientist.llm.request.backend import active_backend
from co_scientist.offline import llm as offline_llm
from co_scientist.schemas import _PROMPT_SCHEMA_MAP
from co_scientist.schemas.generation import GENERATION_SCHEMA
from co_scientist.schemas.planning import META_REVIEW_SCHEMA
from co_scientist.schemas.review import (
    _SCORE_CRITERIA,
    FULL_REVIEW_SCHEMA,
    RANKING_SCHEMA,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
)
from tests._mcp import isolate_offline_router

_GOAL = "Identify repurposable drugs for hepatic fibrosis"
_BATCH_PROMPT = (
    "**Hypothesis 1:** first.\n**Hypothesis 2:** second.\n"
    "**Hypothesis 3:** third.\n"
)


@pytest.fixture(autouse=True)
def _offline_isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """The installed router is process-wide and must be restored between
    tests."""
    isolate_offline_router(monkeypatch)


async def _ask(name: str, schema: dict[str, Any], prompt: str) -> str:
    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": name, "schema": schema},
        },
    )
    content: str = response.choices[0].message.content
    return content


async def _answer(name: str, schema: dict[str, Any], prompt: str) -> Any:
    parsed = json.loads(await _ask(name, schema, prompt))
    jsonschema.validate(instance=parsed, schema=schema)
    return parsed


async def test_the_router_answers_offline_models_and_passes_the_rest_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "stub-result"

    monkeypatch.setattr(litellm, "acompletion", stub)
    offline_llm.install_offline_router()
    offline_llm.install_offline_router()
    routed = active_backend()
    messages = [{"role": "user", "content": "hi"}]

    local = await routed.complete(
        model=offline_llm.DEFAULT_OFFLINE_MODEL, messages=messages
    )
    remote = await routed.complete(
        model="gemini/gemini-2.5-flash", messages=messages
    )

    assert local.choices[0].message.content
    assert remote == "stub-result"
    assert [call["model"] for call in calls] == ["gemini/gemini-2.5-flash"]
    offline_llm.install_offline_router()
    assert active_backend() is routed, "installing again does not re-wrap"


@pytest.mark.parametrize(
    ("name", "schema", "prompt"),
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
            "Live shared memory:\n"
            '{"iteration": 0, "pool_grew_since_proximity": false}',
        ),
        (
            "hypothesis_batch_review",
            REVIEW_BATCH_SCHEMA["schema"],
            _BATCH_PROMPT,
        ),
    ],
)
async def test_offline_answers_are_valid_for_the_schema_they_were_asked(
    name: str, schema: dict[str, Any], prompt: str
) -> None:
    await _answer(name, schema, prompt)


async def test_offline_filler_is_deterministic_and_varies_with_the_prompt() -> (
    None
):
    schema = GENERATION_SCHEMA["schema"]

    first = await _ask("hypothesis_generation", schema, "Explain mechanism.")
    again = await _ask("hypothesis_generation", schema, "Explain mechanism.")
    other = await _ask("hypothesis_generation", schema, "Another prompt.")

    assert first == again
    assert first != other
    for entry in json.loads(first)["hypotheses"]:
        assert isinstance(entry["category"], str)
        assert entry["category"]


async def test_offline_batch_review_is_sized_to_the_hypotheses_asked() -> None:
    parsed = await _answer(
        "hypothesis_batch_review", REVIEW_BATCH_SCHEMA["schema"], _BATCH_PROMPT
    )

    assert len(parsed["reviews"]) == 3
    summaries = [review["review_summary"] for review in parsed["reviews"]]
    assert len(set(summaries)) == len(summaries), "distinct leaves avoid dedup"


async def test_offline_review_scores_clear_the_viable_gate() -> None:
    """The boundary score classifies as revision and skips the mature-review
    cascade."""
    parsed = await _answer(
        "hypothesis_review", REVIEW_SCHEMA["schema"], "Review this."
    )

    review = _review_from_response(parsed)
    assert (
        _disposition_for(review, ("scientific_soundness", "novelty"))
        == "viable"
    )
    assert set(offline_llm._REVIEW_SCORE_FIELDS) == {
        *_SCORE_CRITERIA,
        "overall_score",
    }, "new score axes silently get boundary scores otherwise"


async def test_offline_filler_supplies_optional_fields_of_named_schemas() -> (
    None
):
    full = await _answer(
        "full_review", FULL_REVIEW_SCHEMA["schema"], "Full-review this."
    )
    meta = await _answer(
        "meta_review", META_REVIEW_SCHEMA["schema"], "Meta-review this pool."
    )
    batch = await _answer(
        "hypothesis_batch_review", REVIEW_BATCH_SCHEMA["schema"], _BATCH_PROMPT
    )

    assert full["go_no_go_recommendation"]
    assert full["time_to_verdict"]
    assert meta["main_research_directions"]
    rec = meta["strategic_recommendations"][0]
    assert rec["time_estimate"]
    assert rec["phase_label"]
    assert rec["recommended_idea"]
    assert all(
        "comparative_notes" not in review for review in batch["reviews"]
    ), "optional filling is opt-in by schema, never a global policy"


def _optional_property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    schema_type = schema.get("type", "object")
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required") or properties.keys())
        for name, prop_schema in properties.items():
            if name not in required:
                names.add(name)
            names |= _optional_property_names(prop_schema)
    elif schema_type == "array":
        names |= _optional_property_names(schema.get("items", {}))
    return names


def test_the_optional_field_hints_track_the_schemas_they_name() -> None:
    """Hand-mirrored names must follow schema renames and additions, and use
    the schema's own name rather than its prompt-template name."""
    hints = offline_llm._OPTIONAL_FIELD_HINTS
    for name, schema in (
        ("full_review", FULL_REVIEW_SCHEMA),
        ("meta_review", META_REVIEW_SCHEMA),
    ):
        assert set(hints[name]) == _optional_property_names(schema["schema"])
    known = {schema.get("name") for schema in _PROMPT_SCHEMA_MAP.values()}
    assert set(hints) <= known


def test_run_scoped_hypothesis_ids_are_deterministic_unique_and_scoped() -> (
    None
):
    random_ids = {models.Hypothesis(text=f"idea {n}").id for n in range(5)}
    assert len(random_ids) == 5
    assert all(uuid.UUID(value).version == 4 for value in random_ids)

    seed = models.run_seed_material("run-1", _GOAL)
    with models.run_scoped_hypothesis_ids(seed):
        first = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]
    with models.run_scoped_hypothesis_ids(seed):
        second = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]

    assert first == second
    assert len(set(first)) == 3
    assert models.Hypothesis(text="after").id not in first
    assert models.run_seed_material("a", "bc") != models.run_seed_material(
        "ab", "c"
    )
