"""App adapters consume public engine operations without reverse edges."""

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> list[tuple[int, str, list[str]]]:
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
        for line, module, names in _imports(path)
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
        for line, module, _ in _imports(path)
        if module == "app" or module.startswith("app.")
    ]
    assert not violations, "Engine imports app:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("owner", "coordinators"),
    [
        ("generation/operations.py", {"generation.coordinator"}),
        ("ranking/operations.py", {"ranking.ranking"}),
        (
            "reflection/verification.py",
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
    modules = {module for _, module, _ in _imports(agent_dir / owner)}
    assert forbidden.isdisjoint(modules), (owner, forbidden & modules)
