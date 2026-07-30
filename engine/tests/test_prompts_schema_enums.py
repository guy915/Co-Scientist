"""Every closed enum a schema declares is named by the prompt that fills it.

A prompt that describes a closed enum in its own words instead of naming the
values ("state whether it is well-supported, uncertain, or likely false")
gets answered in those words: the reviewer replied "unsupported", the value
was not one of supported/uncertain/likely_false, and the whole response was
rejected and re-requested. The prompt's wording is the instruction the model
actually follows, so it has to carry the literal tokens.
"""

import pathlib
from typing import Any

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
