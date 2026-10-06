from pathlib import Path

import pytest

from evaluations.tests._coverage import Report, guard, metric, suite


def report(covered: int, other: int = 0) -> Report:
    modules = {"module.py": metric(covered, 1000), "other.py": metric(other, other)}
    return {"suites": {"app": suite(modules)}, "protected_modules": []}


@pytest.mark.parametrize("covered,passed", [(800, True), (799, False)])
def test_suite_coverage_must_stay_at_or_above_the_floor(
    tmp_path: Path, covered: int, passed: bool
) -> None:
    assert (not guard(report(covered), report(960), tmp_path)) is passed


def test_protected_module_below_the_floor_fails_even_if_the_suite_passes(
    tmp_path: Path,
) -> None:
    (tmp_path / "module.py").write_text("pass\n")
    baseline = report(960)
    baseline["protected_modules"] = ["module.py"]
    errors = guard(report(799, other=1000), baseline, tmp_path)
    assert len(errors) == 1
    assert "protected coverage" in errors[0]


def test_protected_module_can_disappear_only_with_deleted_source(
    tmp_path: Path,
) -> None:
    baseline = report(0)
    baseline["protected_modules"] = ["module.py"]
    after: Report = {"suites": {"app": suite({})}, "protected_modules": []}
    assert not guard(after, baseline, tmp_path)
    (tmp_path / "module.py").write_text("pass\n")
    assert "missing from coverage" in guard(after, baseline, tmp_path)[0]
