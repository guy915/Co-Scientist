"""The helper that confines itself and then becomes the command.

Landlock and seccomp restrict *the calling process*, so something has to
apply them between fork and exec. The obvious hook is
``subprocess(preexec_fn=...)``, and it is the one thing this host must not
use: ``preexec_fn`` runs after a fork that inherited every lock the parent
held, and worker cohorts here run on several threads, so it is a deadlock
waiting for a busy moment (see the runner's module docstring).

So the restriction moves into the argv instead, where the other two
backends already live. ``wrap_argv`` produces

    python -m co_scientist.sandbox.confine_exec <policy-json> -- <command>

and this module applies the policy to itself and ``execv``s the command.
Both mechanisms survive ``execve`` -- that is what ``no_new_privs`` buys --
so the confinement the command runs under was installed by a process it
replaced.

**Every failure exits non-zero before the exec.** A helper that could not
apply its policy and ran the command anyway would be the fail-open
sandbox this codebase keeps refusing to build. There is no path from here
to an unconfined command.
"""

import json
import os
import sys
from pathlib import Path

from co_scientist.sandbox import landlock, seccomp
from co_scientist.sandbox.policy import SandboxKind, SandboxPolicy

# Exit codes distinguishable from a command's own, for diagnosis when a
# run reports a failure nobody can reproduce by hand.
EXIT_BAD_INVOCATION = 121
EXIT_POLICY_REFUSED = 122
EXIT_EXEC_FAILED = 123


def _fail(code: int, message: str) -> None:
    """Reports why the command will not run, and does not run it."""
    print(f"confine_exec: {message}", file=sys.stderr)
    raise SystemExit(code)


def policy_to_json(policy: SandboxPolicy) -> str:
    """Serializes a policy for the helper's argv.

    Args:
        policy: The confinement to carry across the process boundary.

    Returns:
        A single JSON argument. Paths travel as data rather than being
        interpolated into anything, so a directory name containing a
        quote or a newline is inert.
    """
    return json.dumps(
        {
            "kind": policy.kind.value,
            "writable_roots": [str(root) for root in policy.writable_roots],
            "allows_network": policy.allows_network,
        }
    )


def policy_from_json(raw: str) -> SandboxPolicy:
    """Rebuilds a policy from the helper's argv.

    Raises:
        ValueError: If the payload is not a policy this module wrote.
    """
    data = json.loads(raw)
    return SandboxPolicy(
        kind=SandboxKind(data["kind"]),
        writable_roots=tuple(Path(p) for p in data["writable_roots"]),
        network_allowed=bool(data["allows_network"]),
    )


def _refuse_inexpressible(policy: SandboxPolicy) -> None:
    """Exits rather than enforcing less than the policy states."""
    if landlock.can_enforce(policy):
        return
    offending = ", ".join(
        str(root) for root in landlock.unenforceable_roots(policy)
    )
    _fail(
        EXIT_POLICY_REFUSED,
        "landlock cannot express a writable root containing protected "
        f"metadata ({offending}); rules are additive, so the carve-out "
        "would silently be granted instead",
    )


def _apply(policy: SandboxPolicy) -> None:
    """Installs the policy on this process, or exits without running."""
    if policy.kind is SandboxKind.DANGER_FULL_ACCESS:
        return

    if not policy.allows_network:
        try:
            seccomp.deny_network()
        except OSError as exc:
            _fail(EXIT_POLICY_REFUSED, f"could not deny the network: {exc}")

    _refuse_inexpressible(policy)

    try:
        landlock.restrict_self(policy)
    except OSError as exc:
        _fail(EXIT_POLICY_REFUSED, f"could not apply landlock: {exc}")


def main(argv: list[str]) -> None:
    """Confines this process and execs the command after ``--``."""
    if "--" not in argv:
        _fail(EXIT_BAD_INVOCATION, "expected <policy-json> -- <command>")
    separator = argv.index("--")
    command = argv[separator + 1 :]
    if separator != 1 or not command:
        _fail(EXIT_BAD_INVOCATION, "expected <policy-json> -- <command>")

    try:
        policy = policy_from_json(argv[0])
    except (ValueError, KeyError, TypeError) as exc:
        _fail(EXIT_BAD_INVOCATION, f"unreadable policy: {exc}")

    _apply(policy)

    try:
        # execvp, not execv: the other two backends hand the command to a
        # wrapper binary that resolves it through PATH, so a bare
        # "python3" works under them. execv does no lookup at all, which
        # made every non-absolute command -- the normal case for anything
        # a model writes -- fail with ENOENT on this backend alone. PATH
        # here is the rebuilt, allowlisted one from build_env, and the
        # sandbox is already applied, so the lookup happens confined.
        os.execvp(command[0], command)
    except OSError as exc:
        _fail(EXIT_EXEC_FAILED, f"could not exec {command[0]}: {exc}")


if __name__ == "__main__":
    main(sys.argv[1:])
