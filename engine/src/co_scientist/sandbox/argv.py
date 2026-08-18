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

import sys

from co_scientist.sandbox import bwrap, seatbelt
from co_scientist.sandbox.policy import SandboxPolicy


class UnsupportedSandboxError(RuntimeError):
    """Raised when no confinement primitive is available for a policy.

    Deliberately not a subclass of anything a generic handler is likely
    to swallow, and deliberately raised rather than logged: the failure
    mode this prevents is running model-authored code unconfined because
    a deployment landed on a platform nobody checked.
    """


def sandbox_backend() -> str | None:
    """Names the confinement backend available here, or None.

    Returns:
        ``"seatbelt"`` on macOS, ``"bwrap"`` on Linux when bubblewrap is
        installed, else None. Callers wanting to fail early on a
        misconfigured host can check this at startup rather than at the
        first command -- but note that startup work here must not be
        awaited before the port binds.
    """
    if sys.platform == "darwin":
        return "seatbelt"
    if sys.platform.startswith("linux") and bwrap.is_available():
        return "bwrap"
    return None


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

    backend = sandbox_backend()
    if backend == "seatbelt":
        return seatbelt.wrap_argv(argv, policy)
    if backend == "bwrap":
        return bwrap.wrap_argv(argv, policy)

    raise UnsupportedSandboxError(
        f"no sandbox backend available on platform {sys.platform!r}: "
        f"refusing to run {argv[0]!r} unconfined. Install bubblewrap on "
        f"Linux, or run the command under an external sandbox and pass "
        f"SandboxKind.EXTERNAL."
    )
