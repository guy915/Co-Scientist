"""The layering of ``co_scientist.llm``: imports only point downward.

The package is regrouped by concern, and each layer may import only from the
layers before it in ``_LAYERS`` (its own included). The check reads the
source rather than importing it, so it sees the module-level imports that
decide initialisation order and ignores the function-level and
``TYPE_CHECKING`` ones that do not.
"""

import ast
import pathlib
from collections.abc import Iterator

import co_scientist.llm as llm

_PACKAGE = "co_scientist.llm"
_ROOT = pathlib.Path(llm.__file__).parent

# Lowest first. ``telemetry`` sits between two ``request`` modules: it reads
# token counts off ``request.response`` while ``request.completion`` records
# into it, so that one edge is allowed upward.
_LAYERS = (
    "values",
    "admission",
    "structured",
    "telemetry",
    "request",
    "precall",
    "attempts",
    "tools",
    "call",
)
_ALLOWED_UPWARD = {("telemetry", "request.response")}


def _modules() -> dict[str, pathlib.Path]:
    """Maps each module's dotted name below the package to its file."""
    return {
        ".".join(path.relative_to(_ROOT).with_suffix("").parts): path
        for path in _ROOT.rglob("*.py")
        if path.name != "__init__.py"
    }


def _runtime_nodes(body: list[ast.stmt]) -> Iterator[ast.ImportFrom]:
    """The ``from`` imports that run at import time, skipping type-only ones."""
    for node in body:
        if isinstance(node, ast.If) and "TYPE_CHECKING" not in ast.dump(
            node.test
        ):
            yield from _runtime_nodes(node.body + node.orelse)
        elif isinstance(node, ast.ImportFrom):
            yield node


def _targets(node: ast.ImportFrom, modules: set[str]) -> set[str]:
    """The package modules one import names (``""`` is the package)."""
    module = node.module or ""
    if not module.startswith(_PACKAGE):
        return set()
    base = module.removeprefix(_PACKAGE).removeprefix(".")
    joined = {f"{base}.{a.name}" if base else a.name for a in node.names}
    return {j if j in modules else base for j in joined}


def _runtime_imports(path: pathlib.Path, modules: set[str]) -> set[str]:
    """The package modules this file imports when it is first loaded."""
    found: set[str] = set()
    for node in _runtime_nodes(ast.parse(path.read_text()).body):
        found |= _targets(node, modules)
    return found


def _layer(module: str) -> int:
    return _LAYERS.index(module.split(".")[0])


def test_no_module_imports_the_interface_it_implements() -> None:
    """Siblings import each other where the name is defined."""
    modules = _modules()
    for name, path in modules.items():
        assert "" not in _runtime_imports(path, set(modules)), name


def test_imports_only_point_downward() -> None:
    """A lower layer never reaches into a higher one."""
    modules = _modules()
    for name, path in modules.items():
        for imported in _runtime_imports(path, set(modules)) - {""}:
            if (name.split(".")[0], imported) in _ALLOWED_UPWARD:
                continue
            assert _layer(imported) <= _layer(name), f"{name} -> {imported}"


def test_module_level_imports_form_no_cycle() -> None:
    """No module is reachable from itself through runtime imports."""
    modules = _modules()
    graph = {
        name: _runtime_imports(path, set(modules)) - {""}
        for name, path in modules.items()
    }
    for name in graph:
        assert name not in _reachable(graph, name), name


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    """Every module reachable from ``start`` by one or more imports."""
    seen: set[str] = set()
    todo = list(graph.get(start, ()))
    while todo:
        module = todo.pop()
        if module not in seen:
            seen.add(module)
            todo.extend(graph.get(module, ()))
    return seen
