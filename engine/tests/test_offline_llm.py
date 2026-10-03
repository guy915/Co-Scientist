"""Offline contracts for offline llm."""

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
from tests._mcp import isolate_offline_router, make_offline_generator


@pytest.fixture
def _offline_llm_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time."""
    isolate_offline_router(monkeypatch)


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


@pytest.mark.usefixtures("_offline_llm_isolate_offline_router")
class TestOfflineLlm:
    def test_is_offline_model_checks_the_prefix(self) -> None:
        """Only ``offline/``-prefixed model names are routed."""
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
        """An ``offline/`` model never reaches the original acompletion."""
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

    async def test_offline_meta_review_fills_main_research_directions(
        self,
    ) -> None:
        """R14-27: the required narrative-directions field is never left empty.

        ``main_research_directions`` is required (unlike the roadmap-step
        fields ``test_offline_optional_fields.py`` hints in), so the generic
        filler must already populate it via one leaf draw -- this is what lets
        ``report.markdown.meta_review``'s renderer show a populated section on
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

    async def test_offline_acompletion_sizes_batch_review_to_hypothesis_count(
        self,
    ) -> None:
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

    async def test_offline_review_scores_clear_the_viable_gate(self) -> None:
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

    def test_review_score_fields_matches_the_schema_criteria(self) -> None:
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

    async def test_offline_filler_supplies_the_required_category(self) -> None:
        """Required categories produce deterministic offline values (K7).

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
        """A second ``install_offline_router`` call does not double-wrap."""
        offline_llm.install_offline_router()
        routed_once = active_backend()

        offline_llm.install_offline_router()

        assert active_backend() is routed_once

    async def test_install_offline_router_idempotency_does_not_lose_passthrough(
        self,
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

        await active_backend().complete(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert len(calls) == 1

    async def test_end_to_end_offline_generator_run_yields_hypotheses(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A real graph run through the runtime router, no fake content path.

        Mirrors the shape of ``tests/test_integration_pipeline.py`` but installs
        only the runtime router (``install_offline_router``); every response is
        produced by the production ``offline_acompletion``, never by
        ``tests._llm_fake``'s monkeypatch-based fake. MCP is genuinely
        unavailable
        (no server listening) and literature review is explicitly disabled, so
        only
        ``call_llm``/``call_llm_json`` are exercised --
        ``supervisor_model_name``
        defaults to ``model_name``, so every model name the graph reads is the
        same
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


@pytest.fixture
def _offline_optional_fields_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time."""
    isolate_offline_router(monkeypatch)


def _optional_property_names(schema: dict[str, Any]) -> set[str]:
    """Walks a schema fragment, collecting every optional property name.

    Mirrors what ``offline.schema_fill``'s traversal treats as optional: a
    property declared in an object node's ``properties`` but absent from
    that node's own ``required`` list, at any nesting depth (inside array
    items included) -- the same scope ``_OPTIONAL_FIELD_HINTS`` values
    apply over, since a hinted name is filled wherever it appears in the
    schema, not just at the top level.
    """
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


@pytest.mark.usefixtures("_offline_optional_fields_isolate_offline_router")
class TestOfflineOptionalFields:
    async def test_offline_full_review_fills_the_go_no_go_verdict_fields(
        self,
    ) -> None:
        """``full_review``'s optional Go/No-Go framing is filled, not omitted.

        Both fields are optional in ``FULL_REVIEW_SCHEMA``, so the generic
        filler used to leave them out of every offline response --
        ``drain.reviews._verdict_detail`` then had nothing to read, and
        ``VerdictLines`` (ideas_detail_review_findings.tsx) never rendered on
        an offline run (docs/decisions/2026-09-02-offline-optional-field-
        reach.md).
        """
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
        """``meta_review``'s optional roadmap-step fields are filled.

        ``time_estimate``/``phase_label``/``recommended_idea`` are optional in
        ``META_REVIEW_SCHEMA``'s ``strategic_recommendations[]`` items, so they
        used to be absent from every offline response --
        ``report.markdown.meta_review._render_recommendation`` never printed
        the phase prefix, time-estimate suffix, or "Recommended idea:" line on
        an offline run.
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
        rec = parsed["strategic_recommendations"][0]
        assert isinstance(rec["time_estimate"], str) and rec["time_estimate"]
        assert isinstance(rec["phase_label"], str) and rec["phase_label"]
        assert (
            isinstance(rec["recommended_idea"], str) and rec["recommended_idea"]
        )

    async def test_optional_field_hints_stays_scoped_to_named_schemas(
        self,
    ) -> None:
        """A schema outside ``_OPTIONAL_FIELD_HINTS`` fills no optional field.

        Proof the capability is opt-in per schema, not a global "fill every
        optional" switch (the design constraint the ADR and the comment above
        ``_OPTIONAL_FIELD_HINTS`` both call out). ``comparative_notes`` is
        optional in ``REVIEW_BATCH_SCHEMA``, which carries no entry.
        """
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
        """A hinted schema's entry must fill *every* optional property it has.

        ``_OPTIONAL_FIELD_HINTS`` hand-mirrors each schema's own ``optional=``
        declarations (schemas/builders.py), so a rename, a field made
        required, or a new optional property added to one of these two
        schemas without a matching update here would silently drift -- the
        same class of gap ``test_offline_llm.
        test_review_score_fields_matches_the_schema_criteria`` guards against
        for the review score fields.
        """
        for schema_name, schema in (
            ("full_review", FULL_REVIEW_SCHEMA),
            ("meta_review", META_REVIEW_SCHEMA),
        ):
            assert set(offline_llm._OPTIONAL_FIELD_HINTS[schema_name]) == (
                _optional_property_names(schema["schema"])
            )

    def test_optional_field_hints_keys_are_real_schema_names(self) -> None:
        """Optional field hints use actual schema names.

        ``_schema_response`` looks the hint up by a schema's own ``"name"``
        field, not by the prompt-template name
        ``schemas.registry._PROMPT_SCHEMA_MAP`` is keyed by -- so this checks
        against every schema's own name instead.
        """
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
    """Isolates ``install_offline_router``'s state to one test at a time."""
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


async def _run(run_id: str) -> dict[str, Any]:
    """Executes one small offline run end to end.

    Args:
        run_id: The run identity the id stream is derived from.

    Returns:
        The generation result dict.
    """
    generator = make_offline_generator()
    return await generator.generate_hypotheses(
        _GOAL,
        opts={"enable_literature_review_node": False},
        run_id=run_id,
        stream=False,
    )


async def _streamed_run(run_id: str) -> dict[str, Any]:
    """Executes one small offline run through the streaming API.

    Args:
        run_id: The run identity the id stream is derived from.

    Returns:
        The last streamed cumulative state.
    """
    generator = make_offline_generator()
    last: dict[str, Any] = {}
    async for _node, state in generator.generate_hypotheses(
        _GOAL,
        opts={"enable_literature_review_node": False},
        run_id=run_id,
        stream=True,
    ):
        last = state
    return last


def _ids(result: dict[str, Any]) -> list[str]:
    """Returns the result's hypothesis ids in order."""
    return [hyp["id"] for hyp in result["hypotheses"]]


def _texts(result: dict[str, Any]) -> list[str]:
    """Returns the result's hypothesis texts in order."""
    return [hyp["text"] for hyp in result["hypotheses"]]


@pytest.mark.usefixtures("_offline_reproducibility_isolate_offline_router")
class TestOfflineReproducibility:
    async def test_identical_offline_runs_produce_identical_ids_and_counts(
        self,
    ) -> None:
        """Two runs of the same offline inputs are the same run."""
        first = await _run("reproducible-run")
        second = await _run("reproducible-run")

        assert _ids(first), "the run produced no hypotheses to compare"
        assert len(_ids(first)) == len(_ids(second))
        assert _ids(first) == _ids(second)
        assert _texts(first) == _texts(second)

    async def test_offline_run_reproduces_its_derived_work(self) -> None:
        """Reproducibility reaches the nodes an id divergence used to break.

        The divergence entered through the debate transcript and came out as
        a different tournament record and a different evolution verdict, so
        those have to match too -- equal hypothesis counts alone would not
        have caught the original defect.

        Deliberately absent: ``metrics``, ``execution_time``, and
        ``proximity_graph``, which carry wall-clock readings (the graph
        stamps ``updated_at``) and so differ between any two runs by
        construction. Reproducibility is a claim about a run's decisions, not
        about how long it took.
        """
        first = await _run("derived-work-run")
        second = await _run("derived-work-run")

        assert first["debate_transcripts"] == second["debate_transcripts"]
        assert first["tournament_matchups"] == second["tournament_matchups"]
        assert first["evolution_details"] == second["evolution_details"]
        assert first["task_history"] == second["task_history"]
        assert first["research_overview"] == second["research_overview"]

    async def test_streaming_offline_runs_reproduce_and_release_the_scope(
        self,
    ) -> None:
        """The streaming path reproduces too, and lets its id scope go.

        Streaming holds the scope open across every yield, so entry and exit
        can land in different consumer contexts. Two runs matching is what
        proves the exit took effect: a scope left installed would carry its
        ordinal stream into the second run and shift every id.
        """
        first = await _streamed_run("streamed-run")
        second = await _streamed_run("streamed-run")

        assert _ids(first), "the run produced no hypotheses to compare"
        assert _ids(first) == _ids(second)
        assert uuid.UUID(models.Hypothesis(text="after").id).version == 4

    async def test_distinct_run_ids_never_share_a_hypothesis_id(self) -> None:
        """Ids stay unique across runs, including runs live at once.

        The seed is per-run precisely so reproducibility cannot be bought
        with a fixed seed, which would hand two concurrent runs the same ids.
        """
        first = await _run("run-a")
        second = await _run("run-b")

        assert not set(_ids(first)) & set(_ids(second))

    def test_hypotheses_draw_random_ids_outside_a_run(self) -> None:
        """Nothing changes for a hypothesis built outside a seeded run."""
        ids = {models.Hypothesis(text=f"idea {n}").id for n in range(5)}

        assert len(ids) == 5
        assert all(uuid.UUID(value).version == 4 for value in ids)

    def test_run_scoped_ids_are_deterministic_unique_and_scoped(self) -> None:
        """The minter repeats across blocks, never within one, and cleans up."""
        seed = models.run_seed_material("run-1", _GOAL)
        with models.run_scoped_hypothesis_ids(seed):
            first = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]
        with models.run_scoped_hypothesis_ids(seed):
            second = [models.Hypothesis(text=f"idea {n}").id for n in range(3)]

        assert first == second
        assert len(set(first)) == 3
        # The block restores the default draw rather than leaving its minter
        # installed for whatever the caller does next.
        assert models.Hypothesis(text="after").id not in first

    def test_run_seed_material_separates_its_two_inputs(self) -> None:
        """No pair of inputs can be concatenated into another pair's seed."""
        assert models.run_seed_material("a", "bc") != models.run_seed_material(
            "ab", "c"
        )
