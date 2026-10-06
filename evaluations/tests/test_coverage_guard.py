from pathlib import Path

import pytest

from evaluations.tests._coverage import Report, guard, metric, suite


def report(covered: int) -> Report:
    modules = {"m.py": metric(covered, 1000), "b.py": metric(1000, 1000)}
    return {"suites": {"app": suite(modules)}, "protected_modules": ["m.py"]}


@pytest.mark.parametrize("covered,passed", [(600, True), (599, False)])
def test_suite_coverage_must_stay_at_or_above_the_floor(
    tmp_path: Path, covered: int, passed: bool
) -> None:
    assert (not guard(report(covered), report(960), tmp_path)) is passed


@pytest.mark.parametrize(
    "base,covered,passed",
    [(960, 800, True), (960, 799, False), (700, 700, True), (700, 699, False)],
)
def test_protected_module_keeps_the_floor_or_its_lower_baseline(
    tmp_path: Path, base: int, covered: int, passed: bool
) -> None:
    (tmp_path / "m.py").write_text("pass\n")
    assert (not guard(report(covered), report(base), tmp_path)) is passed


def test_protected_module_can_disappear_only_with_deleted_source(
    tmp_path: Path,
) -> None:
    after: Report = {"suites": {"app": suite({})}, "protected_modules": []}
    assert not guard(after, report(0), tmp_path)
    (tmp_path / "m.py").write_text("pass\n")
    assert "missing from coverage" in guard(after, report(0), tmp_path)[0]
