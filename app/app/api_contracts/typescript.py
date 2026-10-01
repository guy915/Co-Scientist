"""Render the contract JSON Schema subset as deterministic TypeScript."""

from __future__ import annotations

import json
import re
from typing import Any


def reference(schema: dict[str, Any]) -> str:
    """Resolve one local JSON Schema reference."""
    return str(schema["$ref"]).rsplit("/", 1)[-1]


def properties(schema: dict[str, Any]) -> list[str]:
    """Render declared properties, preserving optional versus nullable."""
    required = schema.get("required", [])
    fields = []
    for name, value in schema.get("properties", {}).items():
        key = (
            name
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name)
            else json.dumps(name)
        )
        optional = "" if name in required else "?"
        fields.append(f"  {key}{optional}: {type_expression(value)};")
    if schema.get("x-open-config"):
        # JSON config admits arbitrary persisted keys as well as typed setup.
        fields.append(
            "  [key: string]: JsonValue | RunSetupConfig | undefined;"
        )
    return fields


def type_expression(schema: dict[str, Any]) -> str:
    """Translate a type; reject unsupported keywords rather than weaken it."""
    if "$ref" in schema:
        return reference(schema)
    if "anyOf" in schema:
        return " | ".join(type_expression(value) for value in schema["anyOf"])
    if "enum" in schema or "const" in schema:
        values = schema.get("enum", [schema.get("const")])
        return " | ".join(json.dumps(value) for value in values)
    return structured_type(schema)


def structured_type(schema: dict[str, Any]) -> str:
    """Translate scalars and containers after union/reference handling."""
    kind = schema.get("type")
    scalars = {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }
    if kind in scalars:
        return scalars[kind]
    if kind == "array":
        element = type_expression(schema["items"])
        element = f"({element})" if " | " in element else element
        return f"{element}[]"
    if kind == "object":
        return object_type(schema)
    if not schema or set(schema) <= {"title", "description"}:
        return "unknown"
    raise ValueError(f"Unsupported wire schema: {schema}")


def object_type(schema: dict[str, Any]) -> str:
    """Render fixed properties or a dictionary's value constraint."""
    if "properties" in schema:
        return "{\n" + "\n".join(properties(schema)) + "\n}"
    extra = schema.get("additionalProperties", {})
    value = type_expression(extra) if isinstance(extra, dict) else "unknown"
    # A recursive alias through Record triggers TS2456; use an object index.
    if value == "JsonValue":
        return f"{{[key: string]: {value}}}"
    return f"Record<string, {value}>"


def references(schema: Any) -> set[str]:
    """Find local references recursively for generated module imports."""
    if isinstance(schema, dict):
        found = {reference(schema)} if "$ref" in schema else set()
        for value in schema.values():
            found.update(references(value))
        return found
    if isinstance(schema, list):
        return set().union(*(references(value) for value in schema))
    return set()


def declaration(name: str, schema: dict[str, Any]) -> str:
    """Emit one named interface or alias."""
    if "properties" in schema:
        body = "\n".join(properties(schema))
        return f"export interface {name} {{\n{body}\n}}"
    return f"export type {name} = {type_expression(schema)};"
