"""Prompts describe the JSON their schema will actually accept.

Where a prompt and its schema disagree, the prompt wins -- it is the
instruction the model follows -- and the schema then rejects the answer and
buys the same content a second time. Both guards here pin a shape that
failed in production: a closed enum described in the prompt's own words
("well-supported, uncertain, or likely false") came back as "unsupported",
and a closed object whose keys only ever appeared in the appended schema
came back with an eighth key the model made up.
"""

import pathlib
from typing import Any

from co_scientist.schemas.ranking import RANKING_SCHEMA
from co_scientist.schemas.registry import _PROMPT_SCHEMA_MAP

_TEMPLATES = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "co_scientist"
    / "prompts"
    / "templates"
)


def _enum_values(node: Any, path: str = "") -> list[tuple[str, list[Any]]]:
    """Collects (property path, enum values) for every enum in a schema."""
    if not isinstance(node, dict):
        return []
    found: list[tuple[str, list[Any]]] = []
    if "enum" in node:
        found.append((path or "<root>", node["enum"]))
    for name, subschema in (node.get("properties") or {}).items():
        found += _enum_values(subschema, f"{path}.{name}" if path else name)
    if "items" in node:
        found += _enum_values(node["items"], path + "[]")
    return found


def test_prompts_name_the_enum_values_their_schema_accepts() -> None:
    unnamed: list[str] = []
    for prompt_name, schema in sorted(_PROMPT_SCHEMA_MAP.items()):
        template = _TEMPLATES / f"{prompt_name}.md"
        assert template.exists(), f"{prompt_name} has no template"
        text = template.read_text()
        for path, values in _enum_values(schema.get("schema", schema)):
            missing = [str(v) for v in values if str(v) not in text]
            if missing:
                unnamed.append(f"  {prompt_name}.md: {path} omits {missing}")
    assert not unnamed, "prompts that do not name their enum values:\n" + (
        "\n".join(unnamed)
    )


def test_ranking_prompt_names_every_comparison_field() -> None:
    """Both tournament prompts name the keys their judgment allows.

    judgment_explanation is closed, and its keys appeared nowhere but the
    schema block appended to the prompt -- the criteria the prompt itself
    lists are prose headings ("Novelty and originality"). A judge asked
    for comparisons in one vocabulary and given keys in another answered
    with a key of its own invention, which cost the match a second call.
    Both published ranking prompts answer against this one schema, so
    both must name every key.
    """
    explanation = RANKING_SCHEMA["schema"]["properties"]["judgment_explanation"]
    for name in ("ranking_pairwise", "ranking_debate"):
        template = (_TEMPLATES / f"{name}.md").read_text()
        for field in explanation["required"]:
            assert field in template, f"{name}.md does not name {field}"
