from pathlib import Path

import pytest

from evaluations.tests._coverage import Report, guard, metric, suite


def report(covered: int, total: int = 1000) -> Report:
    return {
        "suites": {"app": suite({"module.py": metric(covered, total)})},
        "protected_modules": [],
    }


@pytest.mark.parametrize("covered,passed", [(895, True), (894, False)])
def test_suite_coverage_allows_at_most_half_a_point_loss(
    tmp_path: Path, covered: int, passed: bool
) -> None:
    assert (not guard(report(covered), report(900), tmp_path)) is passed


def test_protected_module_rejects_loss_even_within_suite_allowance(
    tmp_path: Path,
) -> None:
    (tmp_path / "module.py").write_text("pass\n")
    baseline = report(900)
    baseline["protected_modules"] = ["module.py"]
    errors = guard(report(899), baseline, tmp_path)
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
