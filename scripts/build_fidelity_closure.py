"""Build the live fidelity closure ledger from audited finding IDs."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/audits/google-co-scientist-implementation"
AUDIT = PACKAGE / "GOOGLE_CO_SCIENTIST_FIDELITY_DIFF_2026-07-12.md"
OVERRIDES = PACKAGE / "fidelity_closure_overrides.json"
OUTPUT = PACKAGE / "IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md"

FINDING = re.compile(
    r"^\| ([A-M]\d{2}) \| `([^`]+)` \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$"
)


def _cell(value: object) -> str:
    """Escape a value for one compact Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def main() -> None:
    """Write a deterministic closure matrix with explicit unproven defaults."""
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    findings: dict[str, tuple[str, str, str, str, str]] = {}
    for line in AUDIT.read_text().splitlines():
        match = FINDING.match(line)
        if match and match.group(1) not in findings:
            findings[match.group(1)] = tuple(match.groups()[1:])  # type: ignore[assignment]

    lines = [
        "# Google Co-Scientist implementation closure matrix",
        "",
        "Generated from the audited difference register. `unproven` is the "
        "fail-closed default: code presence or a passing broad suite does not "
        "close a finding. Edit `fidelity_closure_overrides.json` only after "
        "recording direct implementation and verification evidence, then rerun "
        "`python scripts/build_fidelity_closure.py`.",
        "",
        "## Finding closure ledger",
        "",
        "| ID | Audit class | Current disposition | Google requirement | "
        "Implementation evidence | Verification evidence | Remaining work |",
        "|---|---|---|---|---|---|---|",
    ]
    finding_overrides = overrides.get("findings", {})
    for finding_id in sorted(findings):
        audit_class, google, _local, _evidence, consequence = findings[finding_id]
        current = finding_overrides.get(finding_id, {})
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    finding_id,
                    audit_class,
                    current.get("status", "unproven"),
                    google,
                    current.get("implementation", "—"),
                    current.get("verification", "—"),
                    current.get("remaining", consequence),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Acceptance conditions",
            "",
            "| # | Current disposition | Requirement | Evidence | Remaining work |",
            "|---|---|---|---|---|",
        ]
    )
    for item in overrides.get("acceptance", []):
        lines.append(
            "| "
            + " | ".join(
                _cell(item.get(key, "—"))
                for key in ("id", "status", "requirement", "evidence", "remaining")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Verification log",
            "",
            *[f"- {_cell(entry)}" for entry in overrides.get("verification_log", [])],
            "",
        ]
    )
    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(findings)} findings")


if __name__ == "__main__":
    main()
