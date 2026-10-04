"""Network denial uses a kernel namespace; allowed network is unfiltered host
egress.
"""

from co_scientist.sandbox.policy import (
    METADATA_NAMES,
    SandboxPolicy,
)

BWRAP_EXECUTABLE = "bwrap"

# User namespaces avoid privileges; drop capabilities and kill the sandbox with
# its parent.
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

# Writable rebinds must follow the read-only root; later mounts win.
_READ_ONLY_ROOT = ("--ro-bind", "/", "/")

_RUNTIME_MOUNTS = ("--proc", "/proc", "--dev", "/dev")

# A private /tmp would both grant undeclared writes and hide real files. Scratch
# must live inside a declared writable root.


def _metadata_protection(policy: SandboxPolicy) -> list[str]:
    """Bubblewrap has no deny rule; later read-only binds cover earlier
    writable ones.
    """
    args: list[str] = []
    for root in policy.writable_roots:
        for name in METADATA_NAMES:
            target = str(root / name)
            args.extend(["--ro-bind-try", target, target])
    return args


def _writable_binds(policy: SandboxPolicy) -> list[str]:
    binds: list[str] = []
    for root in policy.writable_roots:
        binds.extend(["--bind", str(root), str(root)])
    return binds


def build_args(policy: SandboxPolicy) -> list[str]:
    args = [*_BASE_FLAGS, *_READ_ONLY_ROOT, *_RUNTIME_MOUNTS]
    args.extend(_writable_binds(policy))
    # Metadata rebinds follow writable mounts because the last mount wins.
    args.extend(_metadata_protection(policy))
    if not policy.allows_network:
        args.append("--unshare-net")
    return args


def wrap_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    return [BWRAP_EXECUTABLE, *build_args(policy), "--", *argv]


def is_available() -> bool:
    from shutil import which

    return which(BWRAP_EXECUTABLE) is not None
