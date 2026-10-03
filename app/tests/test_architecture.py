from __future__ import annotations

import ast
import json
import re
from importlib import import_module
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app import store
from app.api_contracts.common import JsonValue, RunEventActivity
from app.api_contracts.generate import (
    API_DIR,
    contracts,
    generated_files,
    type_expression,
)
from app.main import app
from app.store.events import ACTIVITY_VALUES

_APP_DIR = Path(__file__).resolve().parents[1] / "app"
_INTERVIEW_MODULES = {
    path.stem for path in (_APP_DIR / "interviews").glob("*.py")
} - {"__init__"}


def _layering_imports(path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app":
                modules.extend(f"app.{alias.name}" for alias in node.names)
            else:
                modules.append(module)
    return modules


@pytest.mark.parametrize(
    "source",
    [
        "operator_access.py",
        "staged_documents.py",
        "interviews/turns.py",
    ],
)
def test_shared_services_do_not_import_endpoint_owners(source: str) -> None:
    forbidden = {
        "app.main",
        "app.documents",
        "app.logs_api",
        "app.diagnostics_api",
    }
    assert forbidden.isdisjoint(_layering_imports(_APP_DIR / source)), source


@pytest.mark.parametrize(
    "source",
    ["turns.py", "stream.py"],
)
def test_interview_modules_do_not_reach_into_router_facade(source: str) -> None:
    path = _APP_DIR / "interviews" / source
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module == "app.interviews":
            assert {alias.name for alias in node.names} <= _INTERVIEW_MODULES, (
                path
            )
        if isinstance(node, ast.Import):
            assert all(
                alias.name != "app.interviews" for alias in node.names
            ), path


_ROOT = Path(__file__).resolve().parents[2]


def _boundaries_imports(path: Path) -> list[tuple[int, str, list[str]]]:
    imports: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            imports.append(
                (node.lineno, node.module or "", [a.name for a in node.names])
            )
        elif isinstance(node, ast.Import):
            imports.extend((node.lineno, a.name, []) for a in node.names)
    return imports


def _is_private_engine_import(module: str, names: list[str]) -> bool:
    engine = module == "co_scientist" or module.startswith("co_scientist.")
    private = any(name.startswith("_") for name in [*module.split("."), *names])
    return engine and private


def _engine_private_imports(source_dir: Path) -> list[str]:
    return [
        f"{path}:{line}: {module}: {', '.join(names)}"
        for path in sorted(source_dir.rglob("*.py"))
        for line, module, names in _boundaries_imports(path)
        if _is_private_engine_import(module, names)
    ]


def test_app_consumes_public_engine_operations() -> None:
    violations = _engine_private_imports(_ROOT / "app" / "app")
    assert not violations, "Private engine imports:\n" + "\n".join(violations)


def test_engine_does_not_depend_on_app() -> None:
    engine_dir = _ROOT / "engine" / "src" / "co_scientist"
    violations = [
        f"{path}:{line}: {module}"
        for path in sorted(engine_dir.rglob("*.py"))
        for line, module, _ in _boundaries_imports(path)
        if module == "app" or module.startswith("app.")
    ]
    assert not violations, "Engine imports app:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("owner", "coordinators"),
    [
        ("generation/operations.py", {"generation.generate"}),
        ("ranking/operations.py", {"ranking.ranking"}),
        (
            "reflection/deep_verification.py",
            {
                "reflection.deep_verification",
                "reflection.comprehensive_reflection",
                "reflection.reflection",
                "reflection.review",
            },
        ),
        (
            "evolution/operations.py",
            {"evolution.evolve", "evolution.evolve_prompt"},
        ),
    ],
)
def test_shared_operations_do_not_import_graph_coordinators(
    owner: str, coordinators: set[str]
) -> None:
    agent_dir = _ROOT / "engine" / "src" / "co_scientist" / "agents"
    forbidden = {f"co_scientist.agents.{name}" for name in coordinators}
    modules = {
        module for _, module, _ in _boundaries_imports(agent_dir / owner)
    }
    assert forbidden.isdisjoint(modules), (owner, forbidden & modules)


# requirements.txt deliberately adds uvicorn[standard] and omits the editable
# engine dependency.


tomllib = import_module("tomllib")

APP_DIR = Path(__file__).resolve().parents[1]


def _normalize(requirement: str) -> str:
    return requirement.replace(" ", "").lower()


def _pyproject_dependencies() -> list[str]:
    data = tomllib.loads((APP_DIR / "pyproject.toml").read_text())
    deps: list[str] = data["project"]["dependencies"]
    return [_normalize(dep) for dep in deps]


def _requirements_lines() -> list[str]:
    lines = (APP_DIR / "requirements-app.txt").read_text().splitlines()
    stripped = (line.strip() for line in lines)
    return [_normalize(line) for line in stripped if line and line[0] != "#"]


def _expected_requirements() -> list[str]:
    expected = []
    for dep in _pyproject_dependencies():
        if dep.startswith("co-scientist-engine"):
            continue
        if dep.startswith("uvicorn") and not dep.startswith("uvicorn["):
            dep = dep.replace("uvicorn", "uvicorn[standard]", 1)
        expected.append(dep)
    return expected


def test_requirements_app_matches_pyproject() -> None:
    assert sorted(_requirements_lines()) == sorted(_expected_requirements())


def _legacy_run(isolated_db: str) -> str:
    run = store.create_run(
        "Study feedback",
        "standard",
        "mock",
        {"old_knob": [1, None]},
        store.RunCreateOptions(client_id="contract-owner", db_path=isolated_db),
    )
    store.save_report(
        run.id,
        {"leaderboard": [], "older_section": {"retained": True}},
        "# Saved report",
        db_path=isolated_db,
    )
    return run.id


def _read(client: TestClient, path: str) -> Any:
    response = client.get(path, headers={"X-Client-ID": "contract-owner"})
    assert response.status_code == 200, response.text
    return response.json()


def test_run_reads_keep_nullable_and_unmodeled_persisted_fields(
    isolated_db: str,
) -> None:
    run_id = _legacy_run(isolated_db)
    with TestClient(app) as client:
        run = _read(client, f"/api/runs/{run_id}")
        assert run["completed_at"] is None and run["error"] is None
        assert run["config"]["old_knob"] == [1, None]
        assert run["execution_policy"] == "standard"
        assert run["summary"]["hypotheses"] == 0
        listed = _read(client, "/api/runs")["runs"][0]
        assert "summary" not in listed
        assert listed["top_hypotheses"] == []


def test_old_report_and_public_projection_keep_their_exact_shapes(
    isolated_db: str,
) -> None:
    run_id = _legacy_run(isolated_db)
    with TestClient(app) as client:
        report = _read(client, f"/api/runs/{run_id}/report")
        assert report["payload"] == {
            "leaderboard": [],
            "older_section": {"retained": True},
        }
        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "contract-owner"},
        )
        assert created.status_code == 200
        shared = client.get(f"/api/shared/{created.json()['token']}").json()
        assert set(shared["run"]) == {"title", "research_goal", "run_mode"}
        assert shared["report"] == report


def test_curated_reports_validate_all_nonempty_collection_shapes(
    isolated_db: str,
) -> None:
    with TestClient(app) as client:
        demos = client.get("/api/runs/demo")
        assert demos.status_code == 200
        for run in demos.json()["runs"]:
            for name in (
                "hypotheses",
                "evidence",
                "matches",
                "proximity",
                "reviews",
                "safety",
                "claim-evidence",
                "messages",
                "report",
            ):
                response = client.get(f"/api/runs/{run['id']}/{name}")
                assert response.status_code == 200, (name, response.text)
                if name in ("hypotheses", "evidence", "matches", "reviews"):
                    assert response.json()[name]


def _tokens(source: str) -> list[str]:
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r",\s*}", "}", source)
    source = re.sub(r"([=:])\s*\|", r"\1", source)
    tokens = re.findall(r""""[^"\n]*"|'[^'\n]*'|[\w$]+|[^\s]""", source)
    return [
        json.dumps(t[1:-1]) if t.startswith(("'", '"')) else t for t in tokens
    ]


def test_frontend_wire_types_are_generated_from_backend_contracts() -> None:
    generated = generated_files()
    for name, expected in generated.items():
        assert _tokens((API_DIR / name).read_text()) == _tokens(expected), (
            f"Regenerate {name}: cd app && python -m app.api_contracts.generate"
        )
    exports = set(
        re.findall(
            r"export\s+type\s+\*\s+from\s+['\"](\./wire_[\w]+)['\"]",
            (API_DIR / "runs.ts").read_text(),
        )
    )
    assert exports == {f"./{name.removesuffix('.ts')}" for name in generated}
    contract_names = {name for group in contracts().values() for name in group}
    for path in API_DIR.glob("*.ts"):
        if path.name.startswith("wire_") or path.name.endswith(".test.ts"):
            continue
        source = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(), flags=re.S)
        declarations = set(
            re.findall(
                r"\b(?:interface|type|class|enum)\s+([A-Za-z_$][\w$]*)",
                source,
            )
        )
        assert contract_names.isdisjoint(declarations), (
            path.name,
            contract_names & declarations,
        )


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
