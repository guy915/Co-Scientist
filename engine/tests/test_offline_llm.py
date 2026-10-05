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
from co_scientist.schemas.generation import GENERATION_SCHEMA
from co_scientist.schemas.planning import META_REVIEW_SCHEMA
from co_scientist.schemas.review import (
    FULL_REVIEW_SCHEMA,
    RANKING_SCHEMA,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
)
from tests._mcp import isolate_offline_router


@pytest.fixture
def _offline_llm_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed router is process-wide and must be restored between
    tests."""
    isolate_offline_router(monkeypatch)


def _install_recording_router(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    escaped_calls: list[dict[str, Any]] = []

    async def _recording_original(**kwargs: Any) -> Any:
        escaped_calls.append(kwargs)
        return await offline_llm.offline_acompletion(**kwargs)

    monkeypatch.setattr(litellm, "acompletion", _recording_original)
    offline_llm.install_offline_router()
    return escaped_calls


@pytest.mark.usefixtures("_offline_llm_isolate_offline_router")
class TestOfflineLlm:
    def test_is_offline_model_checks_the_prefix(self) -> None:
        assert offline_llm.is_offline_model(offline_llm.DEFAULT_OFFLINE_MODEL)
        assert offline_llm.is_offline_model("offline/anything")
        assert not offline_llm.is_offline_model("gemini/gemini-2.5-flash")
        assert not offline_llm.is_offline_model("deepseek/deepseek-chat")

    async def test_router_passthrough_calls_original_for_non_offline_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[dict[str, Any]] = []

        async def _stub(**kwargs: Any) -> str:
            calls.append(kwargs)
            return "stub-result"

        monkeypatch.setattr(litellm, "acompletion", _stub)
        offline_llm.install_offline_router()

        result = await active_backend().complete(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert result == "stub-result"
        assert len(calls) == 1
        assert calls[0]["model"] == "gemini/gemini-2.5-flash"

    async def test_router_answers_offline_model_without_reaching_original(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[dict[str, Any]] = []

        async def _stub(**kwargs: Any) -> str:
            calls.append(kwargs)
            return "stub-result"

        monkeypatch.setattr(litellm, "acompletion", _stub)
        offline_llm.install_offline_router()

        response = await active_backend().complete(
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
        self, schema_name: str, schema: dict[str, Any], prompt: str
    ) -> None:
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

    async def test_offline_meta_review_fills_main_research_directions(
        self,
    ) -> None:
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

    async def test_offline_acompletion_sizes_batch_review_to_hypothesis_count(
        self,
    ) -> None:
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
        # Distinct leaves avoid text dedup; the hypothesis echo is absent, so
        # use summary leaves.
        texts = [review["review_summary"] for review in parsed["reviews"]]
        assert len(set(texts)) == len(texts)

    async def test_offline_review_scores_clear_the_viable_gate(self) -> None:
        """The boundary score classifies as revision and skips the mature-
        review cascade."""
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

    def test_review_score_fields_matches_the_schema_criteria(self) -> None:
        """The hand-mirrored axes must track schema changes or new axes
        silently get boundary scores."""
        from co_scientist.schemas.review import _SCORE_CRITERIA

        assert set(offline_llm._REVIEW_SCORE_FIELDS) == {
            *_SCORE_CRITERIA,
            "overall_score",
        }

    async def test_offline_filler_supplies_the_required_category(self) -> None:
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

        assert first["hypotheses"], (
            "filler must produce at least one hypothesis"
        )
        for entry in first["hypotheses"]:
            assert isinstance(entry["category"], str)
            assert entry["category"]
        assert (
            first["hypotheses"][0]["category"]
            == second["hypotheses"][0]["category"]
        )

    async def test_offline_acompletion_is_deterministic_for_identical_calls(
        self,
    ) -> None:
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

        assert (
            first.choices[0].message.content
            == second.choices[0].message.content
        )

    async def test_offline_acompletion_differs_for_different_prompts(
        self,
    ) -> None:
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

        assert (
            first.choices[0].message.content
            != second.choices[0].message.content
        )

    def test_install_offline_router_is_idempotent(self) -> None:
        offline_llm.install_offline_router()
        routed_once = active_backend()

        offline_llm.install_offline_router()

        assert active_backend() is routed_once

    async def test_install_offline_router_idempotency_does_not_lose_passthrough(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[dict[str, Any]] = []

        async def _stub(**kwargs: Any) -> str:
            calls.append(kwargs)
            return "stub-result"

        monkeypatch.setattr(litellm, "acompletion", _stub)
        offline_llm.install_offline_router()
        offline_llm.install_offline_router()

        await active_backend().complete(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert len(calls) == 1


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


@pytest.mark.usefixtures("_offline_llm_isolate_offline_router")
class TestOfflineOptionalFields:
    async def test_offline_full_review_fills_the_go_no_go_verdict_fields(
        self,
    ) -> None:
        schema = FULL_REVIEW_SCHEMA["schema"]

        response = await offline_llm.offline_acompletion(
            model=offline_llm.DEFAULT_OFFLINE_MODEL,
            messages=[
                {"role": "user", "content": "Full-review this hypothesis."}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "full_review", "schema": schema},
            },
        )

        parsed = json.loads(response.choices[0].message.content)
        jsonschema.validate(instance=parsed, schema=schema)
        assert isinstance(parsed["go_no_go_recommendation"], str)
        assert parsed["go_no_go_recommendation"]
        assert isinstance(parsed["time_to_verdict"], str)
        assert parsed["time_to_verdict"]

    async def test_offline_meta_review_fills_the_roadmap_step_fields(
        self,
    ) -> None:
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
        rec = parsed["strategic_recommendations"][0]
        assert isinstance(rec["time_estimate"], str) and rec["time_estimate"]
        assert isinstance(rec["phase_label"], str) and rec["phase_label"]
        assert (
            isinstance(rec["recommended_idea"], str) and rec["recommended_idea"]
        )

    async def test_optional_field_hints_stays_scoped_to_named_schemas(
        self,
    ) -> None:
        """Optional filling is opt-in by schema, never a global all-fields
        policy."""
        schema = REVIEW_BATCH_SCHEMA["schema"]

        response = await offline_llm.offline_acompletion(
            model=offline_llm.DEFAULT_OFFLINE_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "**Hypothesis 1:** first.\n**Hypothesis 2:** second."
                    ),
                }
            ],
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
        assert parsed["reviews"], "filler must produce at least one review"
        for review in parsed["reviews"]:
            assert "comparative_notes" not in review

    def test_optional_field_hints_matches_the_schemas_full_optional_set(
        self,
    ) -> None:
        """Hand-mirrored optional names must track schema renames and
        additions."""
        for schema_name, schema in (
            ("full_review", FULL_REVIEW_SCHEMA),
            ("meta_review", META_REVIEW_SCHEMA),
        ):
            assert set(offline_llm._OPTIONAL_FIELD_HINTS[schema_name]) == (
                _optional_property_names(schema["schema"])
            )

    def test_optional_field_hints_keys_are_real_schema_names(self) -> None:
        """Hints use the schema's own name, not its prompt-template name."""
        from co_scientist.schemas import _PROMPT_SCHEMA_MAP

        known_names = {
            schema.get("name") for schema in _PROMPT_SCHEMA_MAP.values()
        }
        assert set(offline_llm._OPTIONAL_FIELD_HINTS) <= known_names


_GOAL = "Identify repurposable drugs for hepatic fibrosis"


@pytest.fixture
def _offline_reproducibility_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


@pytest.mark.usefixtures("_offline_reproducibility_isolate_offline_router")
class TestOfflineReproducibility:
    def test_hypotheses_draw_random_ids_outside_a_run(self) -> None:
        ids = {models.Hypothesis(text=f"idea {n}").id for n in range(5)}

        assert len(ids) == 5
        assert all(uuid.UUID(value).version == 4 for value in ids)

    def test_run_scoped_ids_are_deterministic_unique_and_scoped(self) -> None:
        seed = models.run_seed_material("run-1", _GOAL)
        with models.run_scoped_hypothesis_ids(seed):
            first = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]
        with models.run_scoped_hypothesis_ids(seed):
            second = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]

        assert first == second
        assert len(set(first)) == 3
        assert models.Hypothesis(text="after").id not in first

    def test_run_seed_material_separates_its_two_inputs(self) -> None:
        assert models.run_seed_material("a", "bc") != models.run_seed_material(
            "ab", "c"
        )
