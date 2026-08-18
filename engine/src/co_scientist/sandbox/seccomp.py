"""Denying a process the network without privileges.

Landlock can refuse TCP connect and bind from ABI 4, and that is not
enough: measured in a container, a Landlock-confined process still sent
UDP freely, so "no network" would have meant "no network except DNS and
anything willing to use it". A namespace (`--unshare-net`) is complete
but needs privileges the deployment target does not grant.

A seccomp filter is the third option and the one that fits: it needs only
`no_new_privs`, it is inherited across `execve`, and refusing `socket()`
for the internet address families denies every protocol at once rather
than enumerating them. `AF_UNIX` is deliberately left alone -- local IPC
is not network access, and runtimes use it for things as ordinary as
logging.

The filter is written as raw BPF because that is the kernel's interface
and the program is nine instructions. The jump offsets are the part to
read carefully: an arch or syscall *mismatch* must fall through to
allow, and getting that backwards denies every syscall in the process,
which does not look like a policy error from outside -- it looks like the
interpreter crashing.
"""

import ctypes
import logging
import platform
import struct

logger = logging.getLogger(__name__)

_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2

_RET_ALLOW = 0x7FFF0000
_RET_ERRNO_EACCES = 0x00050000 | 13

# Offsets into struct seccomp_data.
_OFFSET_NR = 0
_OFFSET_ARCH = 4
_OFFSET_ARG0 = 16

# BPF opcodes: load word absolute, jump-if-equal, return constant.
_LD_W_ABS = 0x20
_JEQ_K = 0x15
_RET_K = 0x06

_AF_INET = 2
_AF_INET6 = 10
_AF_PACKET = 17

# (audit arch, socket syscall number) per machine.
_ARCHITECTURES = {
    "aarch64": (0xC00000B7, 198),
    "arm64": (0xC00000B7, 198),
    "x86_64": (0xC000003E, 41),
}


class SeccompUnavailableError(OSError):
    """This platform cannot install the filter."""


def _instruction(code: int, jt: int, jf: int, k: int) -> bytes:
    """Packs one struct sock_filter."""
    return struct.pack("=HBBI", code, jt, jf, k)


def _deny_inet_program(audit_arch: int, socket_nr: int) -> bytes:
    """Builds the filter refusing internet sockets.

    Jump targets are relative to the *next* instruction, and the two
    returns sit at 8 (allow) and 9 (deny). Every mismatch above -- a
    different architecture, a syscall that is not socket(), an address
    family we do not refuse -- must land on 8. Getting that backwards
    denies every syscall the process makes, which from outside looks
    like the interpreter crashing rather than like a policy error.
    """
    return b"".join(
        [
            _instruction(_LD_W_ABS, 0, 0, _OFFSET_ARCH),  # 0
            _instruction(_JEQ_K, 0, 6, audit_arch),  # 1 -> 8 on mismatch
            _instruction(_LD_W_ABS, 0, 0, _OFFSET_NR),  # 2
            _instruction(_JEQ_K, 0, 4, socket_nr),  # 3 -> 8 if not socket
            _instruction(_LD_W_ABS, 0, 0, _OFFSET_ARG0),  # 4 (domain)
            _instruction(_JEQ_K, 3, 0, _AF_INET),  # 5 -> 9
            _instruction(_JEQ_K, 2, 0, _AF_INET6),  # 6 -> 9
            _instruction(_JEQ_K, 1, 0, _AF_PACKET),  # 7 -> 9
            _instruction(_RET_K, 0, 0, _RET_ALLOW),  # 8
            _instruction(_RET_K, 0, 0, _RET_ERRNO_EACCES),  # 9
        ]
    )


class _SockFprog(ctypes.Structure):
    """struct sock_fprog: a filter's length and its address."""

    _fields_ = (("len", ctypes.c_ushort), ("filter", ctypes.c_void_p))


def is_supported() -> bool:
    """Reports whether this machine has a known audit arch."""
    return platform.machine() in _ARCHITECTURES


def deny_network() -> None:
    """Refuses internet sockets for this process and its children.

    Raises:
        SeccompUnavailableError: If the architecture is unknown or the
            kernel refuses the filter. Callers must treat this as a
            failure to confine, never as "network denial not needed".
    """
    architecture = _ARCHITECTURES.get(platform.machine())
    if architecture is None:
        raise SeccompUnavailableError(
            f"no seccomp filter for machine {platform.machine()!r}"
        )

    program = _deny_inet_program(*architecture)
    blob = ctypes.create_string_buffer(program, len(program))
    fprog = _SockFprog(len(program) // 8, ctypes.cast(blob, ctypes.c_void_p))

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0):
        raise SeccompUnavailableError(
            ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed"
        )
    if libc.prctl(
        _PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0
    ):
        raise SeccompUnavailableError(
            ctypes.get_errno(), "PR_SET_SECCOMP failed"
        )
