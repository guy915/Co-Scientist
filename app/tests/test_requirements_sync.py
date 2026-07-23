"""Guard the manual sync between pyproject.toml and requirements-app.txt.

requirements-app.txt mirrors ``[project] dependencies`` in app/pyproject.toml
for the installers that use ``pip install -e app --no-deps`` (make setup, the
CI setup-backend action, docker/Dockerfile.api). Two deltas are deliberate and
documented in the requirements file's header:

- uvicorn carries the ``[standard]`` extra there (watchfiles for --reload),
  while pyproject stays on plain uvicorn;
- the co-scientist-engine pin is omitted (installed editable from ../engine).

Anything else is drift.
"""

from importlib import import_module
from pathlib import Path

# Imported dynamically: mypy checks against python_version 3.10, where the
# 3.11+ tomllib module does not exist; the test itself runs on 3.11+.
tomllib = import_module("tomllib")

APP_DIR = Path(__file__).resolve().parents[1]


def _normalize(requirement: str) -> str:
    """Canonicalize a requirement string for comparison."""
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
    """Pyproject dependencies with the two documented deltas applied."""
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
