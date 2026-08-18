"""Tests for the unprivileged Linux backend.

The enforcement tests live in ``test_sandbox.py`` and run under whichever
backend the platform selected, so this file covers the parts that are
checkable anywhere: the policy's trip across a process boundary, the
refusal of a policy landlock cannot express, and the shape of the seccomp
program.

That last one earns its place. A wrong jump offset in a BPF filter does
not produce a policy error -- it denies every syscall the process makes,
and the process dies in a way that reads as the interpreter crashing.
It cost a debugging detour to find, and it is invisible to every test
that only asks "was the network denied", because a process that cannot
run anything cannot reach the network either.
"""

import struct
from pathlib import Path

import pytest

from co_scientist.sandbox import (
    HARNESS_METADATA_NAME,
    PROTECTED_METADATA_NAMES,
    SandboxKind,
    SandboxPolicy,
    landlock,
    read_only,
    seccomp,
    workspace_write,
)
from co_scientist.sandbox.confine_exec import policy_from_json, policy_to_json

# --- the policy's trip across the process boundary ------------------------


def test_a_policy_survives_the_round_trip(tmp_path: Path) -> None:
    """The helper is a separate process; the policy travels in argv."""
    policy = workspace_write(tmp_path, network_allowed=True)
    assert policy_from_json(policy_to_json(policy)) == policy


def test_a_read_only_policy_survives_the_round_trip() -> None:
    assert policy_from_json(policy_to_json(read_only())) == read_only()


def test_awkward_directory_names_travel_as_data(tmp_path: Path) -> None:
    """JSON, not interpolation: a quote in a path must stay inert."""
    awkward = tmp_path / 'we"ird \n dir'
    awkward.mkdir()
    restored = policy_from_json(policy_to_json(workspace_write(awkward)))
    assert restored.writable_roots == (awkward.resolve(),)


# --- what landlock will not pretend to enforce ----------------------------


@pytest.mark.parametrize("name", PROTECTED_METADATA_NAMES)
def test_a_protected_name_makes_a_policy_inexpressible(
    tmp_path: Path, name: str
) -> None:
    """Rules only add access, so the carve-out cannot be spelled.

    Refusing is the fail-closed direction: applying the part it can
    express would grant write access to the very directory the policy
    names as protected, while every log line still said "confined".
    """
    (tmp_path / name).mkdir()
    assert not landlock.can_enforce(workspace_write(tmp_path))


def test_harness_scratch_does_not_make_a_policy_inexpressible(
    tmp_path: Path,
) -> None:
    """The distinction that cost a working backend.

    This directory exists in every workspace. While it sat in
    PROTECTED_METADATA_NAMES, every policy was inexpressible and the
    helper refused every command with exit 122.
    """
    (tmp_path / HARNESS_METADATA_NAME).mkdir()
    assert landlock.can_enforce(workspace_write(tmp_path))


def test_an_empty_workspace_is_expressible(tmp_path: Path) -> None:
    assert landlock.can_enforce(workspace_write(tmp_path))
    assert landlock.unenforceable_roots(workspace_write(tmp_path)) == ()


def test_full_access_is_not_landlock_s_problem() -> None:
    """DANGER_FULL_ACCESS names the risk; it is not an enforcement gap."""
    landlock.restrict_self(SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS))


# --- the seccomp program --------------------------------------------------

_ALLOW_INDEX = 8
_DENY_INDEX = 9
_RET_OPCODE = 0x06


def _decode(program: bytes) -> list[tuple[int, int, int, int]]:
    """Unpacks a BPF program into (code, jt, jf, k) tuples."""
    return [
        struct.unpack("=HBBI", program[offset : offset + 8])
        for offset in range(0, len(program), 8)
    ]


def _program() -> list[tuple[int, int, int, int]]:
    """Builds the filter for a known architecture."""
    return _decode(seccomp._deny_inet_program(0xC000003E, 41))


def test_every_conditional_jump_lands_on_a_return() -> None:
    """A jump into the middle re-reads instructions as a new program."""
    instructions = _program()
    for index, (code, jt, jf, _) in enumerate(instructions):
        if code == _RET_OPCODE:
            continue
        for offset in (jt, jf):
            assert index + 1 + offset in (index + 1, _ALLOW_INDEX, _DENY_INDEX)


def test_a_mismatch_falls_through_to_allow() -> None:
    """The bug that denies every syscall and reads as a crash.

    An unknown architecture or a syscall that is not socket() must reach
    the allow return. With the two returns transposed they reach deny
    instead, and the process dies on its next syscall -- which looks
    like the interpreter falling over, not like a policy.
    """
    instructions = _program()
    _, _, arch_mismatch, _ = instructions[1]
    _, _, not_socket, _ = instructions[3]
    assert 1 + 1 + arch_mismatch == _ALLOW_INDEX
    assert 3 + 1 + not_socket == _ALLOW_INDEX


def test_the_returns_are_the_right_way_round() -> None:
    instructions = _program()
    assert instructions[_ALLOW_INDEX] == (_RET_OPCODE, 0, 0, 0x7FFF0000)
    assert instructions[_DENY_INDEX][3] & 0xFFFF0000 == 0x00050000


def test_every_internet_family_reaches_deny() -> None:
    """AF_UNIX is untouched: local IPC is not network access."""
    instructions = _program()
    families = {}
    for index, (_code, jt, _, k) in enumerate(instructions):
        if index in (5, 6, 7):
            families[k] = index + 1 + jt
    assert set(families) == {2, 10, 17}  # AF_INET, AF_INET6, AF_PACKET
    assert set(families.values()) == {_DENY_INDEX}
