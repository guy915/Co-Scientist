from __future__ import annotations

import json
import uuid
from typing import Any

import jsonschema
import pytest

from co_scientist import models
from co_scientist.agents.reflection.review import _review_from_response
from co_scientist.agents.reflection.review_gate import _disposition_for
from co_scientist.offline import llm as offline_llm
from co_scientist.schemas.review import (
    _SCORE_CRITERIA,
    REVIEW_SCHEMA,
)
from tests._mcp import isolate_offline_router

_GOAL = "Identify repurposable drugs for hepatic fibrosis"


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
