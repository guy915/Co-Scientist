"""Shared evidence gathering cannot depend on an agent's implementation."""

import ast
from pathlib import Path

import co_scientist.evidence as evidence


def test_shared_evidence_modules_do_not_import_agents() -> None:
    """Keep search and article construction usable by every specialist."""
    for path in Path(evidence.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        modules = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        modules += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(
            module.startswith("co_scientist.agents") for module in modules
        ), path
