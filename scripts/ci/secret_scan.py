import os
import subprocess
import sys
from pathlib import Path

try:
    from .git_hygiene import revision
except ImportError:
    from git_hygiene import revision


def added_lines(diff: str) -> str:
    additions = []
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@ "):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            additions.append(line[1:] + "\n")
    return "".join(additions)


def scan(root: Path, base: str, head: str, binary: Path) -> int:
    base, head = revision(base), revision(head)
    common = subprocess.check_output(
        ["git", "-C", str(root), "merge-base", base, head], text=True
    ).strip()
    diff = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--text",
            "--unified=0",
            common,
            head,
            "--",
        ],
        text=True,
        errors="replace",
    )
    result = subprocess.run(
        [
            str(binary),
            "stdin",
            "--no-banner",
            "--redact=100",
            "--config",
            str(Path(__file__).with_name("gitleaks.toml")),
        ],
        input=added_lines(diff),
        text=True,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(
        scan(
            Path("."),
            os.environ["BASE_SHA"],
            os.environ["HEAD_SHA"],
            Path(os.environ["GITLEAKS_BIN"]),
        )
    )
