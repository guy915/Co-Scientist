from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, TypedDict


class Metric(TypedDict):
    covered: int
    total: int
    percent: float


class Suite(Metric):
    modules: dict[str, Metric]


class Report(TypedDict):
    suites: dict[str, Suite]
    protected_modules: list[str]


def metric(covered: int, total: int) -> Metric:
    return {
        "covered": covered,
        "total": total,
        "percent": 100 * covered / total if total else 100.0,
    }


def suite(modules: dict[str, Metric]) -> Suite:
    totals = metric(
        sum(row["covered"] for row in modules.values()),
        sum(row["total"] for row in modules.values()),
    )
    return {**totals, "modules": dict(sorted(modules.items()))}


def read_python(path: Path, cwd: Path, root: Path) -> Suite:
    raw: dict[str, Any] = json.loads(path.read_text())
    modules = {}
    for name, data in raw["files"].items():
        source = (cwd / name).resolve().relative_to(root).as_posix()
        summary = data["summary"]
        modules[source] = metric(
            summary["covered_lines"], summary["num_statements"]
        )
    return suite(modules)


def read_frontend(path: Path, root: Path) -> Suite:
    raw: dict[str, Any] = json.loads(path.read_text())
    return suite(
        {
            Path(name).resolve().relative_to(root).as_posix(): metric(
                data["lines"]["covered"], data["lines"]["total"]
            )
            for name, data in raw.items()
            if name != "total"
        }
    )


COVERAGE_FLOOR = 80.0


def guard(report: Report, baseline: Report, root: Path) -> list[str]:
    errors = []
    for name, before in baseline["suites"].items():
        after = report["suites"][name]
        if after["percent"] + 1e-9 < COVERAGE_FLOOR:
            errors.append(
                f"{name}: {after['percent']:.4f}% below the "
                f"{COVERAGE_FLOOR:.0f}% floor"
            )
        errors.extend(module_guard(after, before, baseline, root))
    return errors


def module_guard(
    after: Suite, before: Suite, baseline: Report, root: Path
) -> list[str]:
    errors = []
    for name in set(baseline["protected_modules"]) & before["modules"].keys():
        if not (root / name).exists():
            continue
        if name not in after["modules"]:
            errors.append(f"{name}: protected module missing from coverage")
            continue
        current = after["modules"][name]
        if current["percent"] + 1e-9 < COVERAGE_FLOOR:
            errors.append(
                f"{name}: protected coverage {current['percent']:.4f}% "
                f"below the {COVERAGE_FLOOR:.0f}% floor"
            )
    return errors


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print(f">> Coverage: {cwd}", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    print(f"coverage_suite_exit_status={completed.returncode}", flush=True)
    completed.check_returncode()


def python_suites(
    args: argparse.Namespace, root: Path, output: Path, env: dict[str, str]
) -> dict[str, Suite]:
    config = output / "pytest.coveragerc"
    config.write_text("[run]\nomit = */tests/*\n")
    suites = {}
    for name, cwd, source, tests, interpreter in (
        ("app", root / "app", "app", "tests", args.python),
        (
            "engine",
            root / "engine",
            "src/co_scientist",
            "tests",
            args.python,
        ),
        (
            "mcp",
            root / "engine",
            "mcp_server",
            "mcp_server/tests",
            args.mcp_python,
        ),
    ):
        raw_path = output / f"{name}.json"
        run(
            [
                interpreter,
                "-m",
                "pytest",
                tests,
                "-q",
                f"--cov={source}",
                f"--cov-config={config}",
                "--cov-report=term",
                f"--cov-report=json:{raw_path}",
            ],
            cwd,
            {**env, "COVERAGE_FILE": str(output / f".coverage.{name}")},
        )
        suites[name] = read_python(raw_path, cwd, root)
    return suites


def measure(args: argparse.Namespace, root: Path, output: Path) -> Report:
    output.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "COSCIENTIST_FORCE_OFFLINE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    }
    suites = python_suites(args, root, output, env)
    frontend = root / "app/frontend"
    run(
        [
            args.bun,
            "run",
            "test",
            "--config",
            "src/__tests__/coverage_config.ts",
            "--coverage",
            f"--coverage.reportsDirectory={output / 'frontend'}",
        ],
        frontend,
        env,
    )
    suites["frontend"] = read_frontend(
        output / "frontend/coverage-summary.json", root
    )
    return {"suites": suites, "protected_modules": []}


def print_report(report: Report) -> None:
    for name, row in report["suites"].items():
        print(
            f"{name}: {row['percent']:.4f}% "
            f"({row['covered']}/{row['total']} production lines)"
        )
        for module, data in row["modules"].items():
            print(
                f"  {module}: {data['percent']:.4f}% "
                f"({data['covered']}/{data['total']})"
            )


def finish(args: argparse.Namespace, report: Report, root: Path) -> int:
    baseline_path = root / "docs/test-campaign/coverage-baseline.json"
    if args.record_baseline:
        report["protected_modules"] = sorted(set(args.protect))
        measured = {
            name for row in report["suites"].values() for name in row["modules"]
        }
        if not args.protect or set(args.protect) - measured:
            raise ValueError("Baseline needs measured protected module paths")
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        with baseline_path.open("x") as baseline_file:
            json.dump(report, baseline_file, indent=2, sort_keys=True)
            baseline_file.write("\n")
        print(f"Recorded fixed baseline: {baseline_path}")
        return 0
    baseline: Report = json.loads(baseline_path.read_text())
    errors = guard(report, baseline, root)
    for error in errors:
        print(f"COVERAGE GUARD: {error}")
    print(f"Coverage guard: {'FAILED' if errors else 'passed'}")
    return int(bool(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--python", default=".venv/bin/python")
    parser.add_argument("--mcp-python", default=".venv-mcp/bin/python")
    parser.add_argument("--bun", default="bun")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--protect", action="append", default=[])
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    for option in ("python", "mcp_python"):
        interpreter = Path(getattr(args, option))
        if not interpreter.is_absolute():
            setattr(args, option, str(root / interpreter))
    output = root / ".cache/test-campaign/coverage"
    report_path = output / "report.json"
    if args.report_only:
        report: Report = json.loads(report_path.read_text())
    else:
        report = measure(args, root, output)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
    print_report(report)
    return finish(args, report, root)


if __name__ == "__main__":
    raise SystemExit(main())
