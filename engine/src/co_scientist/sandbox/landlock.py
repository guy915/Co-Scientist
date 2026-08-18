"""Linux confinement that needs no privileges at all.

The reason this exists: bubblewrap builds its confinement out of
namespaces, and creating a user namespace is exactly what a container
runtime's default seccomp profile refuses. Measured in a stock
`python:3.12-slim` container -- `unshare(CLONE_NEWUSER)` returns EPERM,
so bwrap cannot start, so the platform we actually deploy to had no
enforceable sandbox. Landlock is the opposite shape: a process restricts
*itself*, asks the kernel for nothing it does not already have, and the
restriction survives `execve` because `no_new_privs` is set alongside it.
Same container, Landlock ABI 6, and the escape tests pass.

**One thing Landlock cannot do, and it is the one this host relied on.**
Landlock rules are strictly additive: a rule on a subdirectory can only
*grant* access, never withdraw it. There is no deny, and no
last-match-wins. So the pattern both other backends use for protected
metadata -- allow the workspace, then carve `.git` back out -- has no
Landlock spelling. That is why `can_enforce` exists and why the backend
refuses such a policy rather than applying the part it can express: a
sandbox that quietly enforces less than its policy says is worse than one
that refuses, because the policy is what everything downstream reasons
about.

Network denial is TCP-only here (`LANDLOCK_ACCESS_NET_*`, ABI 4+), which
would leave UDP open -- so it is not used. `seccomp.py` denies the whole
address family instead, and this module handles the filesystem only.
"""

import ctypes
import logging
import os
import struct
from pathlib import Path

from co_scientist.sandbox.policy import (
    PROTECTED_METADATA_NAMES,
    SandboxKind,
    SandboxPolicy,
)

logger = logging.getLogger(__name__)

# Identical on x86_64 and aarch64.
_NR_CREATE_RULESET = 444
_NR_ADD_RULE = 445
_NR_RESTRICT_SELF = 446

_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# This module is Linux-only at run time but must still import elsewhere:
# the argv-shape tests, mypy and ruff all run on macOS, where os.O_PATH
# does not exist. The value is the same on every Linux architecture.
_O_PATH = getattr(os, "O_PATH", 0o010000000)

# Filesystem access bits, in ABI order.
_EXECUTE = 1 << 0
_WRITE_FILE = 1 << 1
_READ_FILE = 1 << 2
_READ_DIR = 1 << 3
_REFER = 1 << 13
_TRUNCATE = 1 << 14

# Bits 0..12: every operation defined by ABI 1.
_ABI1_ALL = (1 << 13) - 1

# What a command may do anywhere: run programs and read. Deliberately no
# REFER, so a rename out of a writable root is refused.
_READ_ACCESS = _EXECUTE | _READ_FILE | _READ_DIR


def _libc() -> ctypes.CDLL:
    """Returns a libc handle configured to report errno."""
    return ctypes.CDLL(None, use_errno=True)


def abi_version() -> int | None:
    """Returns the kernel's Landlock ABI version, or None if absent.

    Returns:
        The ABI version, or None when the syscall is missing (pre-5.13),
        compiled out, or blocked.
    """
    try:
        libc = _libc()
    except OSError:  # pragma: no cover - libc is always present on Linux
        return None
    result = libc.syscall(
        _NR_CREATE_RULESET,
        None,
        ctypes.c_size_t(0),
        ctypes.c_uint32(_CREATE_RULESET_VERSION),
    )
    return result if result > 0 else None


def is_available() -> bool:
    """Reports whether this kernel can enforce a Landlock ruleset."""
    return abi_version() is not None


def _handled_access(abi: int) -> int:
    """Returns the access bits the ruleset takes responsibility for.

    REFER is handled from ABI 2 because *not* handling it makes the
    kernel refuse every cross-directory rename outright -- including one
    entirely inside the workspace, which is ordinary work. Handling it
    and granting it on the writable roots restores that while still
    refusing a rename out of them. IOCTL_DEV is left unhandled: this
    backend confines the filesystem, and handling it without granting it
    on /dev breaks terminal ioctls for no gain here.
    """
    handled = _ABI1_ALL
    if abi >= 2:
        handled |= _REFER
    if abi >= 3:
        handled |= _TRUNCATE
    return handled


def _ruleset_attr(abi: int, handled: int) -> ctypes.Array[ctypes.c_char]:
    """Packs landlock_ruleset_attr at the size this ABI expects.

    The struct grew twice (handled_access_net at ABI 4, scoped at ABI 6)
    and the kernel rejects a size it does not recognise, so the length is
    chosen from the ABI rather than fixed.
    """
    if abi >= 6:
        return ctypes.create_string_buffer(
            struct.pack("=QQQ", handled, 0, 0), 24
        )
    if abi >= 4:
        return ctypes.create_string_buffer(struct.pack("=QQ", handled, 0), 16)
    return ctypes.create_string_buffer(struct.pack("=Q", handled), 8)


def _add_path_rule(
    libc: ctypes.CDLL, ruleset_fd: int, path: Path, access: int
) -> None:
    """Grants ``access`` on everything beneath ``path``.

    Raises:
        OSError: If the path cannot be opened or the rule rejected.
    """
    parent_fd = os.open(path, _O_PATH | os.O_CLOEXEC)
    try:
        # landlock_path_beneath_attr is __packed__: 8 + 4, not 16.
        attr = ctypes.create_string_buffer(
            struct.pack("=Qi", access, parent_fd), 12
        )
        if libc.syscall(
            _NR_ADD_RULE,
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint32(_RULE_PATH_BENEATH),
            attr,
            ctypes.c_uint32(0),
        ):
            errno = ctypes.get_errno()
            raise OSError(errno, f"landlock_add_rule({path}) failed")
    finally:
        os.close(parent_fd)


def unenforceable_roots(policy: SandboxPolicy) -> tuple[Path, ...]:
    """Returns writable roots holding metadata Landlock cannot protect.

    A rule may only add access, so "writable, except this subdirectory"
    is not expressible. Any writable root that already contains a
    protected name would therefore be granted write access to it.

    Args:
        policy: The confinement being asked for.

    Returns:
        The offending roots, empty when the policy is expressible.
    """
    offending = []
    for root in policy.writable_roots:
        if any((root / name).exists() for name in PROTECTED_METADATA_NAMES):
            offending.append(root)
    return tuple(offending)


def can_enforce(policy: SandboxPolicy) -> bool:
    """Reports whether Landlock can express this policy exactly."""
    return not unenforceable_roots(policy)


def restrict_self(policy: SandboxPolicy) -> None:
    """Applies ``policy``'s filesystem rules to the calling process.

    The restriction is inherited across ``execve`` -- that is the whole
    mechanism -- so a caller applies this and then execs the command it
    wants confined.

    Args:
        policy: The confinement to enforce.

    Raises:
        OSError: If the kernel refuses any step. Never partially applied
            in a way that reports success: the ruleset only takes effect
            at the final ``landlock_restrict_self``.
    """
    if policy.kind is SandboxKind.DANGER_FULL_ACCESS:
        return
    abi = abi_version()
    if abi is None:
        raise OSError("landlock is not available on this kernel")

    libc = _libc()
    handled = _handled_access(abi)
    ruleset_fd = libc.syscall(
        _NR_CREATE_RULESET,
        _ruleset_attr(abi, handled),
        ctypes.c_size_t(len(_ruleset_attr(abi, handled))),
        ctypes.c_uint32(0),
    )
    if ruleset_fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset failed")

    try:
        _add_path_rule(libc, ruleset_fd, Path("/"), _READ_ACCESS)
        for root in policy.writable_roots:
            _add_path_rule(libc, ruleset_fd, root, handled)
        _commit(libc, ruleset_fd)
    finally:
        os.close(ruleset_fd)


def _commit(libc: ctypes.CDLL, ruleset_fd: int) -> None:
    """Sets no_new_privs and enforces the ruleset on this process."""
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    if libc.syscall(
        _NR_RESTRICT_SELF, ctypes.c_int(ruleset_fd), ctypes.c_uint32(0)
    ):
        raise OSError(ctypes.get_errno(), "landlock_restrict_self failed")
