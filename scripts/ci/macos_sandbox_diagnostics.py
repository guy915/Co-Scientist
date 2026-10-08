"""Harmless runner probes for loader failures; never changes the shipped policy."""

import platform
import subprocess
import sys
from pathlib import Path

from co_scientist.platform.sandbox import read_only, seatbelt
from co_scientist.platform.sandbox.policy import runtime_read_roots


def probe(label: str, argv: list[str]) -> None:
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=15, check=False
    )
    print(
        f"{label}: exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


def main() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("macOS diagnostics require Darwin")
    print(f"macOS={platform.mac_ver()[0]}, architecture={platform.machine()}")
    print(f"Runtime read roots: {runtime_read_roots()}")
    command = ["/bin/echo", "sandbox-runtime-probe"]
    probe("unconfined positive control", command)
    probe("shipped baseline", seatbelt.wrap_argv(command, read_only()))
    library = Path("/System/Library")
    cryptex = Path("/System/Volumes/Preboot/Cryptexes/OS/System/Library")
    print(
        f"System library exists={library.exists()}, Cryptex library exists={cryptex.exists()}"
    )
    probe("system library read only", seatbelt.wrap_argv(command, read_only(library)))
    probe(
        "system and Cryptex libraries read only",
        seatbelt.wrap_argv(command, read_only(library, cryptex)),
    )
    root = '(allow file-read* (literal "/"))'
    sysctls = (
        '(allow sysctl-read (sysctl-name "security.mac.lockdown_mode_state") '
        '(sysctl-name "kern.bootargs"))'
    )
    for label, addition in (
        ("root directory only", root),
        ("startup sysctls only", sysctls),
        ("root directory and startup sysctls", root + "\n" + sysctls),
    ):
        wrapped = seatbelt.wrap_argv(command, read_only())
        wrapped[wrapped.index("-p") + 1] += "\n" + addition
        probe(label, wrapped)
    logs = subprocess.run(
        [
            "/usr/bin/log",
            "show",
            "--last",
            "2m",
            "--style",
            "compact",
            "--predicate",
            'eventMessage CONTAINS "deny" AND (process == "sandboxd" OR process == "kernel")',
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    print(f"Sandbox denial log exit={logs.returncode}")
    print(logs.stdout[-12000:])


if __name__ == "__main__":
    main()
