"""Linux confinement: a SandboxPolicy rendered as bubblewrap arguments.

Bubblewrap rather than Landlock: Codex treats its Landlock backend as
legacy and enforces with `bwrap` plus seccomp, and bwrap expresses the
filesystem shape this host wants -- everything read-only, specific roots
rebound writable -- as mount arguments rather than as a ruleset the
process must apply to itself.

Network denial is a namespace (`--unshare-net`), so it is enforced by the
kernel rather than by a proxy that a determined program could route
around. The cost is that "network allowed" means the host's network
unfiltered; a filtered middle ground needs a proxy and is not offered
here rather than being approximated.
"""

from co_scientist.sandbox.policy import (
    METADATA_NAMES,
    SandboxPolicy,
)

BWRAP_EXECUTABLE = "bwrap"

# Applied to every confined command regardless of policy. --unshare-user
# is what allows the rest without privileges; --cap-drop ALL ensures the
# command cannot regain any; --die-with-parent means a killed worker does
# not leave the sandboxed process orphaned and running.
_BASE_FLAGS = (
    "--unshare-user",
    "--unshare-pid",
    "--unshare-ipc",
    "--unshare-uts",
    "--unshare-cgroup-try",
    "--cap-drop",
    "ALL",
    "--new-session",
    "--die-with-parent",
)

# The whole filesystem readable, nothing writable. Writable roots are
# rebound over this afterwards, so ordering matters: a --bind emitted
# before this --ro-bind would be masked by it.
_READ_ONLY_ROOT = ("--ro-bind", "/", "/")

# /proc and /dev are needed by essentially every runtime.
_RUNTIME_MOUNTS = ("--proc", "/proc", "--dev", "/dev")

# No private /tmp is mounted, deliberately. A tmpfs over /tmp both
# widens and narrows the policy at once, and both directions were caught
# by running the escape tests on Linux:
#
#   * it makes the whole of /tmp WRITABLE, so a workspace under /tmp --
#     where pytest puts them, and where container scratch space often
#     lives -- meant a write anywhere in /tmp succeeded; and
#   * it MASKS the real /tmp, so a read-only sandbox could not read
#     files that were actually there.
#
# Neither is what the policy says. /tmp is therefore left read-only like
# the rest of the filesystem, and a command needing scratch space writes
# into a declared root -- WorkspaceSession points TMPDIR at one.
#
# macOS never showed either fault: seatbelt grants by path and has no
# equivalent blanket mount.


def _metadata_protection(policy: SandboxPolicy) -> list[str]:
    """Re-binds protected metadata read-only inside each writable root.

    bwrap has no deny rule, so protection is a later read-only bind that
    covers the earlier writable one. ``--ro-bind-try`` is used so a root
    without a .git directory is not an error.
    """
    args: list[str] = []
    for root in policy.writable_roots:
        for name in METADATA_NAMES:
            target = str(root / name)
            args.extend(["--ro-bind-try", target, target])
    return args


def _writable_binds(policy: SandboxPolicy) -> list[str]:
    """Builds the --bind pairs that make each writable root writable."""
    binds: list[str] = []
    for root in policy.writable_roots:
        binds.extend(["--bind", str(root), str(root)])
    return binds


def build_args(policy: SandboxPolicy) -> list[str]:
    """Builds the bwrap arguments enforcing a policy, without the command.

    Args:
        policy: The confinement decision to enforce.

    Returns:
        The bwrap flags, ordered so that writable rebinds land after the
        read-only root they override.
    """
    args = [*_BASE_FLAGS, *_READ_ONLY_ROOT, *_RUNTIME_MOUNTS]
    args.extend(_writable_binds(policy))
    # After the writable binds, so it covers them: last mount wins.
    args.extend(_metadata_protection(policy))
    if not policy.allows_network:
        args.append("--unshare-net")
    return args


def wrap_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    """Wraps a command so the kernel enforces the policy against it.

    Args:
        argv: The command to confine, already split into arguments.
        policy: The confinement decision to enforce.

    Returns:
        A new argv invoking bwrap with the policy's mounts and namespaces,
        and the original command after the ``--`` separator.
    """
    return [BWRAP_EXECUTABLE, *build_args(policy), "--", *argv]


def is_available() -> bool:
    """Reports whether a usable bwrap is on PATH."""
    from shutil import which

    return which(BWRAP_EXECUTABLE) is not None
