"""Discover exported wire contracts without copying their fields or aliases."""

from types import ModuleType
from typing import Any

from pydantic import TypeAdapter
from typing_extensions import is_typeddict

from app.api_contracts import common, interviews, reports, runs, science

GROUPS: tuple[ModuleType, ...] = (common, interviews, reports, runs, science)


def contracts() -> dict[str, dict[str, Any]]:
    """Return the backend contracts grouped by generated frontend module."""
    result: dict[str, dict[str, Any]] = {}
    for module in GROUPS:
        aliases = module.__annotations__
        owned = {
            name: value
            for name, value in vars(module).items()
            if not name.startswith("_")
            and (
                name in aliases
                or (is_typeddict(value) and value.__module__ == module.__name__)
            )
        }
        result[module.__name__.rsplit(".", 1)[-1]] = owned
    result["common"].update(
        RunStatus=common.RunStatus, JsonValue=common.JsonValue
    )
    return result


def schemas() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Collect every root and referenced schema with its owning group."""
    definitions: dict[str, dict[str, Any]] = {}
    owners: dict[str, str] = {}
    for group, values in contracts().items():
        for name, value in values.items():
            schema = TypeAdapter(value).json_schema()
            definitions.update(schema.pop("$defs", {}))
            if "$ref" not in schema:
                definitions[name] = schema
            owners[name] = group
    return definitions, owners
