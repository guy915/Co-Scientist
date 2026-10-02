"""Backend schemas, served endpoints and frontend types stay aligned."""

from __future__ import annotations

import json
import re
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from app.api_contracts.common import JsonValue, RunEventActivity
from app.api_contracts.generate import API_DIR, generated_files
from app.api_contracts.registry import contracts
from app.api_contracts.typescript import type_expression
from app.main import app
from app.store.event_activity import ACTIVITY_VALUES


def _tokens(source: str) -> list[str]:
    """Compare syntax while tolerating prettier's quotes and whitespace."""
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r",\s*}", "}", source)
    source = re.sub(r"=\s*\|", "=", source)
    tokens = re.findall(r""""[^"\n]*"|'[^'\n]*'|[\w$]+|[^\s]""", source)
    return [
        json.dumps(t[1:-1]) if t.startswith(("'", '"')) else t for t in tokens
    ]


def test_frontend_wire_types_are_generated_from_backend_contracts() -> None:
    for name, expected in generated_files().items():
        assert _tokens((API_DIR / name).read_text()) == _tokens(expected), (
            f"Regenerate {name}: cd app && python -m app.api_contracts.generate"
        )
    for name in ("run_types", "report_types", "interview_types"):
        source = (API_DIR / f"{name}.ts").read_text()
        assert "export interface" not in source and "export type " in source


def test_closed_event_vocabulary_matches_the_store() -> None:
    assert set(get_args(RunEventActivity)) == ACTIVITY_VALUES


def test_json_value_stays_recursive_and_rejects_non_json_values() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(JsonValue)
    value = {"nested": [None, True, {"deep": [1, "text"]}]}
    assert adapter.validate_python(value) == value
    with pytest.raises(ValidationError):
        adapter.validate_python({"bad": object()})
    assert type_expression(adapter.json_schema()) == "JsonValue"


def test_supported_read_routes_publish_concrete_response_schemas() -> None:
    paths = app.openapi()["paths"]
    routes = [
        ("/api/runs", "get"),
        ("/api/runs", "post"),
        ("/api/runs/{run_id}", "get"),
        ("/api/interviews", "get"),
        ("/api/interviews/{interview_id}", "get"),
        ("/api/shared/{token}", "get"),
    ]
    collections = [
        "hypotheses",
        "evidence",
        "matches",
        "proximity",
        "reviews",
        "safety",
        "outcomes",
        "claim-evidence",
        "messages",
        "report",
        "shares",
    ]
    routes.extend(
        (f"/api/runs/{{run_id}}/{name}", "get") for name in collections
    )
    for path, method in routes:
        schema = paths[path][method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert "$ref" in schema or schema.get("type") == "array", (path, schema)


@pytest.mark.parametrize("value", ["invalid", {}, None])
def test_response_models_reject_malformed_required_fields(value: Any) -> None:
    models = contracts()
    with pytest.raises(ValidationError):
        TypeAdapter(models["runs"]["RunSummary"]).validate_python(
            {
                "events": value,
                "hypotheses": 0,
                "evidence": 0,
                "matches": 0,
                "reviews": 0,
            }
        )
