"""Offline-router sizing hooks for the research-overview schema's arrays.

Split from ``test_offline_llm`` on size; that module keeps the router's
other coverage (passthrough, determinism, the fail-loud schema set,
review-score overrides, the end-to-end graph run). Both tests here cover
``offline_llm._research_overview_directions_length``, the one array-
length hook covering two distinct fields of the same schema.
"""

import json

import jsonschema

from co_scientist import offline_llm
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_SCHEMA


async def test_offline_acompletion_sizes_directions_past_the_preview_gate() -> (
    None
):
    """``research_directions`` is sized past the report's preview gate.

    ``report/markdown/overview.py::_render_directions_preview`` renders
    nothing below two named directions, so a single-item array would make
    the overview's preview list silently vanish on every offline run.
    """
    schema = RESEARCH_OVERVIEW_SCHEMA["schema"]

    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[
            {
                "role": "user",
                "content": "Top-ranked hypotheses (highest Elo first):\n"
                "1. (Elo 1200) first.\n",
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "research_overview",
                "schema": schema,
            },
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    jsonschema.validate(instance=parsed, schema=schema)
    directions = parsed["overview"]["research_directions"]
    assert len(directions) >= 2
    titles = [d["title"] for d in directions]
    assert all(titles)
    assert len(set(titles)) == len(titles)


async def test_offline_acompletion_sizes_unexpected_research_directions() -> (
    None
):
    """``unexpected_research_directions`` is sized past the one-item default.

    Task B: without this hint an offline run's demo would show exactly
    one unexpected direction, from the generic filler's default -- this
    sizes it to the schema's own bound instead, matching MASH's own
    published exemplar (three named bullets).
    """
    schema = RESEARCH_OVERVIEW_SCHEMA["schema"]

    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[
            {
                "role": "user",
                "content": "Top-ranked hypotheses (highest Elo first):\n"
                "1. (Elo 1200) first.\n",
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "research_overview",
                "schema": schema,
            },
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    jsonschema.validate(instance=parsed, schema=schema)
    directions = parsed["unexpected_research_directions"]
    assert len(directions) == 3
    titles = [d["title"] for d in directions]
    assert all(titles)
    assert len(set(titles)) == len(titles)
