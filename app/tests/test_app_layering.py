"""Shared policies and interview services must sit below HTTP routers."""

import ast
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1] / "app"
_INTERVIEW_MODULES = {
    path.stem for path in (_APP_DIR / "interviews").glob("*.py")
} - {"__init__"}


def _imports(path: Path) -> list[str]:
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
        "interviews/support.py",
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
    assert forbidden.isdisjoint(_imports(_APP_DIR / source)), source


@pytest.mark.parametrize(
    "source",
    ["support.py", "turns.py", "stream.py", "revision.py"],
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
