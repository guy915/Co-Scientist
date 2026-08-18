"""Backend selection, and the fail-closed rule that governs it.

``wrap_argv`` is the only entry point callers should use. It picks the
platform's confinement primitive and, when there isn't one, **raises**.

That last part is the whole design. Codex has this exact seam and its
agent path fails *open* -- an unsupported platform silently becomes
`SandboxType::None` -- while its CLI hard-fails on the same condition.
For a host whose sandboxed commands are written by a language model
rather than by the operator, the CLI's behaviour is the correct one: a
platform we cannot confine on must refuse to run the command, not run it
unconfined and look identical in the logs. A caller that genuinely wants
no confinement says so with DANGER_FULL_ACCESS, which is visible in the
policy, the log line, and the stored task row.
"""

import functools
import logging
import subprocess
import sys
from collections.abc import Callable

from co_scientist.sandbox import bwrap, landlock, seatbelt
from co_scientist.sandbox.policy import SandboxPolicy

logger = logging.getLogger(__name__)

# How long the one-off bwrap usability probe may take. It runs /bin/true
# under a minimal namespace set; anything slower than this is a sick host.
_PROBE_TIMEOUT_SECONDS = 10.0


class UnsupportedSandboxError(RuntimeError):
    """Raised when no confinement primitive is available for a policy.

    Deliberately not a subclass of anything a generic handler is likely
    to swallow, and deliberately raised rather than logged: the failure
    mode this prevents is running model-authored code unconfined because
    a deployment landed on a platform nobody checked.
    """


@functools.lru_cache(maxsize=1)
def bwrap_is_usable() -> bool:
    """Reports whether bubblewrap can actually create a namespace here.

    Installed is not the same as usable, and the difference is the whole
    reason this function exists. bwrap builds its confinement out of
    namespaces, and a container runtime's default seccomp profile
    refuses ``unshare(CLONE_NEWUSER)`` -- so in a stock container bwrap
    is present, on PATH, and fails on every invocation. Selecting it on
    presence alone gives a backend that refuses every command, which
    reads as a broken harness rather than as a platform limit.

    Cached because it forks a process, and the answer cannot change
    while this one is running.
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
    """Names the confinement backend available here, or None.

    Returns:
        ``"seatbelt"`` on macOS. On Linux, ``"bwrap"`` when bubblewrap
        can actually create a namespace, else ``"landlock"`` when the
        kernel supports it, else None.

    Bubblewrap is preferred where it works because it isolates more than
    the filesystem -- pid, ipc, uts and the network are separate
    namespaces, not policy. Landlock covers the filesystem only, with
    the network denied by a seccomp filter instead, and it cannot
    express a read-only carve-out inside a writable root at all. It wins
    on the one axis that decides deployment: it needs no privileges, so
    it works in the container this is actually shipped in.

    Callers wanting to fail early on a misconfigured host can check this
    at startup rather than at the first command -- but note that startup
    work here must not be awaited before the port binds.
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
    """Builds the argv that confines itself and then becomes the command.

    Landlock and seccomp restrict the calling process, so the wrapper is
    a helper that applies both to itself and execs -- see
    ``confine_exec``. The interpreter is this one, because the helper is
    part of this package.
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


_BACKEND_WRAPPERS: dict[
    str, Callable[[list[str], SandboxPolicy], list[str]]
] = {
    "seatbelt": seatbelt.wrap_argv,
    "bwrap": bwrap.wrap_argv,
    "landlock": _landlock_argv,
}


def wrap_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    """Wraps a command so the OS enforces the policy against it.

    Args:
        argv: The command to run, already split into arguments.
        policy: The confinement decision. DANGER_FULL_ACCESS and EXTERNAL
            return ``argv`` unchanged -- the first because the caller
            named the risk, the second because something outside this
            process is doing the confining.

    Returns:
        The wrapped argv, or ``argv`` unchanged for the two policies that
        do not confine in process.

    Raises:
        ValueError: If ``argv`` is empty.
        UnsupportedSandboxError: If the policy asks for in-process
            confinement and this platform offers none.
    """
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
