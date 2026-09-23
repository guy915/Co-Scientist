"""What a confined command is allowed to do, as a value object.

The policy is data, deliberately. It carries no platform knowledge and no
enforcement: ``argv.wrap_argv`` turns it into the arguments of whichever
OS primitive is available, and a policy therefore serializes, logs, and
compares cleanly, and can be attached to a durable task row and replayed.

Modelled on the shape OpenAI Codex CLI uses (`SandboxPolicy` in
codex-rs/protocol/src/protocol.rs). The insight worth stealing is that
confinement expressed as an argv transform over a data policy is
language-independent -- the confinement lives in the arguments handed to
the kernel, not in the process that assembled them, so a Python host gets
exactly the isolation a Rust one does.
"""

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


class SandboxKind(Enum):
    """How much of the machine a command may touch."""

    # Read the filesystem, write nowhere, no network. The default for
    # anything whose job is to inspect rather than produce.
    READ_ONLY = "read_only"

    # Read the filesystem, write only inside declared roots, no network
    # unless network_allowed. The working mode for analysis code.
    WORKSPACE_WRITE = "workspace_write"

    # No confinement at all. Exists so that "unsandboxed" is a policy a
    # caller must name and a log can show, rather than the silent result
    # of a missing one.
    DANGER_FULL_ACCESS = "danger_full_access"

    # Confinement is provided by something outside this process -- a
    # container, a VM, a dedicated exec host. wrap_argv is a no-op, not
    # because nothing confines the command but because this process is
    # not what confines it.
    EXTERNAL = "external"


# Names a command must not rewrite even inside a directory it may write
# to: the history of the repository it was handed, and the agent
# configuration that decides what it is allowed to do next. These belong
# to whoever handed us the directory, so failing to protect them is a
# real loss of a stated guarantee -- the landlock backend REFUSES a
# policy whose writable root already contains one rather than enforcing
# less than the policy says (see landlock.can_enforce).
PROTECTED_METADATA_NAMES = (".git", ".agents", ".claude")

# The harness's own scratch inside a workspace: spilled command output,
# snapshot bookkeeping. Deliberately NOT in the tuple above, and the
# distinction is the point. Protecting it is nice -- one command cannot
# then rewrite the record of an earlier one -- but nothing's safety
# depends on it. The host writes these files from outside the sandbox and
# guards that write by resolving the target and refusing anything outside
# the workspace (workspace/output.py), which is what actually stops a
# symlink redirecting it. Conflating the two cost a working landlock
# backend: because this name is always present, every workspace policy
# looked inexpressible and every command was refused.
HARNESS_METADATA_NAME = ".cosci"

# What the backends that CAN express a read-only carve-out apply it to.
METADATA_NAMES = (*PROTECTED_METADATA_NAMES, HARNESS_METADATA_NAME)


@dataclass(frozen=True)
class SandboxPolicy:
    """A confinement decision, independent of how it is enforced.

    Attributes:
        kind: How much of the machine the command may touch.
        writable_roots: Absolute directories the command may write to.
            Meaningful only for WORKSPACE_WRITE; ignored otherwise.
        network_allowed: Whether outbound network is permitted. Ignored
            for READ_ONLY, which never permits it.
    """

    kind: SandboxKind
    writable_roots: tuple[Path, ...] = field(default_factory=tuple)
    network_allowed: bool = False

    def __post_init__(self) -> None:
        """Validates and canonicalizes the writable roots.

        Roots are resolved -- symlinks followed -- because the OS
        primitives match on the real path. On macOS ``/var`` is a symlink
        to ``/private/var``, so a root under ``/var`` that is not
        resolved grants nothing at all: the command is denied writes to
        the very directory it was handed. That fails closed, which is
        safe, but presents as "the sandbox is broken" rather than as a
        path bug, so it is fixed here at construction where the policy
        can still be inspected.

        Raises:
            ValueError: If any writable root is a relative path. A
                relative root would be resolved against the *sandboxed*
                process's cwd, which is not necessarily the cwd the
                policy was written against -- so the grant would not mean
                what its author intended.
        """
        relative = [str(p) for p in self.writable_roots if not p.is_absolute()]
        if relative:
            raise ValueError(
                f"writable_roots must be absolute paths; got {relative}"
            )
        object.__setattr__(
            self,
            "writable_roots",
            tuple(p.resolve() for p in self.writable_roots),
        )

    @property
    def confines_in_process(self) -> bool:
        """Whether wrap_argv should apply an OS primitive to this policy."""
        return self.kind in (
            SandboxKind.READ_ONLY,
            SandboxKind.WORKSPACE_WRITE,
        )

    @property
    def allows_network(self) -> bool:
        """Whether outbound network is permitted under this policy."""
        if self.kind is SandboxKind.READ_ONLY:
            return False
        if self.kind is SandboxKind.WORKSPACE_WRITE:
            return self.network_allowed
        return True


def read_only() -> SandboxPolicy:
    """Builds the read-nothing-write-nothing-reach-nothing default."""
    return SandboxPolicy(kind=SandboxKind.READ_ONLY)


def campaign_workspace_policy(policy: SandboxPolicy) -> SandboxPolicy:
    """Keep campaign workspace commands offline under OS confinement."""
    from co_scientist.llm_free_policy import campaign_free_mode

    if not campaign_free_mode():
        return policy
    if not policy.confines_in_process:
        raise RuntimeError("campaign workspace requires OS confinement")
    return replace(policy, network_allowed=False)


def workspace_write(
    *roots: Path, network_allowed: bool = False
) -> SandboxPolicy:
    """Builds a policy permitting writes inside the given roots.

    Args:
        *roots: Absolute directories the command may write to.
        network_allowed: Whether to permit outbound network.

    Returns:
        The corresponding WORKSPACE_WRITE policy.
    """
    return SandboxPolicy(
        kind=SandboxKind.WORKSPACE_WRITE,
        writable_roots=tuple(roots),
        network_allowed=network_allowed,
    )
