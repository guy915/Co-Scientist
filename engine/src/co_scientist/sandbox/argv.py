"""Unavailable or inexpressible confinement must refuse execution."""

import functools
import logging
import subprocess
import sys
from collections.abc import Callable

from co_scientist.sandbox import bwrap, landlock, seatbelt
from co_scientist.sandbox.policy import SandboxPolicy

logger = logging.getLogger(__name__)

# Bound the forked namespace probe so a sick host cannot delay availability
# indefinitely.
_PROBE_TIMEOUT_SECONDS = 10.0


class UnsupportedSandboxError(RuntimeError):
    """Confinement failure must propagate rather than degrade to unconfined
    execution.
    """


@functools.lru_cache(maxsize=1)
def bwrap_is_usable() -> bool:
    """Container seccomp can refuse user namespaces even with bwrap installed.
    Cache the forked usability probe for this process.
    """
    if not bwrap.is_available():
        return False
    try:
        probe = subprocess.run(
            [
                bwrap.BWRAP_EXECUTABLE,
                "--unshare-user",
                "--unshare-pid",
                "--ro-bind",
                "/",
                "/",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--",
                "/bin/true",
            ],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("bubblewrap is installed but unusable here: %s", exc)
        return False
    if probe.returncode != 0:
        logger.info(
            "bubblewrap is installed but cannot create a namespace here "
            "(%s); falling back to landlock",
            probe.stderr.decode("utf-8", "replace").strip()[:200],
        )
    return probe.returncode == 0


def sandbox_backend() -> str | None:
    """Bubblewrap isolates namespaces; Landlock needs no privileges but cannot
    carve out metadata.
    """
    if sys.platform == "darwin":
        return "seatbelt"
    if not sys.platform.startswith("linux"):
        return None
    if bwrap_is_usable():
        return "bwrap"
    if landlock.is_available():
        return "landlock"
    return None


def _landlock_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    """Apply process-local Landlock/seccomp in a helper that execs, never a
    threaded preexec_fn.
    """
    from co_scientist.sandbox.confine_exec import policy_to_json

    return [
        sys.executable,
        "-m",
        "co_scientist.sandbox.confine_exec",
        policy_to_json(policy),
        "--",
        *argv,
    ]


_BACKEND_WRAPPERS: dict[str, Callable[[list[str], SandboxPolicy], list[str]]] = {
    "seatbelt": seatbelt.wrap_argv,
    "bwrap": bwrap.wrap_argv,
    "landlock": _landlock_argv,
}


def wrap_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    if not argv:
        raise ValueError("cannot wrap an empty command")
    if not policy.confines_in_process:
        return list(argv)

    wrapper = _BACKEND_WRAPPERS.get(sandbox_backend() or "")
    if wrapper is not None:
        return wrapper(argv, policy)

    raise UnsupportedSandboxError(
        f"no sandbox backend available on platform {sys.platform!r}: "
        f"refusing to run {argv[0]!r} unconfined. Landlock needs Linux "
        f"5.13 or newer; failing that, install bubblewrap, or run the "
        f"command under an external sandbox and pass SandboxKind.EXTERNAL."
    )
