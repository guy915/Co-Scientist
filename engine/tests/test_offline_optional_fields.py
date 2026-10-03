"""Tests for the offline filler's scoped optional-field capability.

Split out of ``test_offline_llm.py`` (over the file-length ceiling) to give
``_OPTIONAL_FIELD_HINTS`` -- the per-schema-name declaration of which
optional properties the offline filler fills anyway, despite the schema
marking them optional -- its own themed home, alongside
``test_offline_content.py`` and ``test_offline_reproducibility.py``.

Covers: the two hinted schemas (``full_review``, ``meta_review``) actually
get their named fields filled; an unhinted schema
(``hypothesis_batch_review``) stays untouched, proving the capability is
scoped per schema rather than a blanket "fill every optional" switch; and a
drift guard pinning ``_OPTIONAL_FIELD_HINTS`` to each hinted schema's full
optional-property set and to real schema names.
"""

import json
from typing import Any

import jsonschema
import pytest

from co_scientist.offline import llm as offline_llm
from co_scientist.schemas.meta_review_schema import META_REVIEW_SCHEMA
from co_scientist.schemas.review import FULL_REVIEW_SCHEMA, REVIEW_BATCH_SCHEMA
from tests._offline_helpers import isolate_offline_router


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates ``install_offline_router``'s state to one test at a time."""
    isolate_offline_router(monkeypatch)


async def test_offline_full_review_fills_the_go_no_go_verdict_fields() -> None:
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
        messages=[{"role": "user", "content": "Full-review this hypothesis."}],
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


async def test_offline_meta_review_fills_the_roadmap_step_fields() -> None:
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
    assert isinstance(rec["recommended_idea"], str) and rec["recommended_idea"]


async def test_optional_field_hints_stays_scoped_to_named_schemas() -> None:
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


def test_optional_field_hints_matches_the_schemas_full_optional_set() -> None:
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


def test_optional_field_hints_keys_are_real_schema_names() -> None:
    """A typo'd key in ``_OPTIONAL_FIELD_HINTS`` would silently fill nothing.

    ``_schema_response`` looks the hint up by a schema's own ``"name"``
    field, not by the prompt-template name
    ``schemas.registry._PROMPT_SCHEMA_MAP`` is keyed by -- so this checks
    against every schema's own name instead.
    """
    from co_scientist.schemas import _PROMPT_SCHEMA_MAP

    known_names = {schema.get("name") for schema in _PROMPT_SCHEMA_MAP.values()}
    assert set(offline_llm._OPTIONAL_FIELD_HINTS) <= known_names
