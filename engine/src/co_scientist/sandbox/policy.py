from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


class SandboxKind(Enum):
    READ_ONLY = "read_only"

    WORKSPACE_WRITE = "workspace_write"

    # Unsandboxed execution must be explicitly named and visible, never a
    # missing-backend fallback.
    DANGER_FULL_ACCESS = "danger_full_access"

    # EXTERNAL delegates confinement to the caller's boundary outside this
    # process.
    EXTERNAL = "external"


# Protected repository metadata controls future behavior; Landlock refuses
# inexpressible carve-outs.
PROTECTED_METADATA_NAMES = (".git", ".agents", ".claude")

# Harness scratch protection is optional, unlike repository metadata. Host-side
# resolved-path guards enforce spill containment on every backend.
HARNESS_METADATA_NAME = ".cosci"

METADATA_NAMES = (*PROTECTED_METADATA_NAMES, HARNESS_METADATA_NAME)


@dataclass(frozen=True)
class SandboxPolicy:
    kind: SandboxKind
    writable_roots: tuple[Path, ...] = field(default_factory=tuple)
    network_allowed: bool = False

    def __post_init__(self) -> None:
        """macOS /var points to /private/var; OS grants need real paths.
        Relative roots would resolve against the confined process's cwd.
        """
        relative = [str(p) for p in self.writable_roots if not p.is_absolute()]
        if relative:
            raise ValueError(f"writable_roots must be absolute paths; got {relative}")
        object.__setattr__(
            self,
            "writable_roots",
            tuple(p.resolve() for p in self.writable_roots),
        )

    @property
    def confines_in_process(self) -> bool:
        return self.kind in (
            SandboxKind.READ_ONLY,
            SandboxKind.WORKSPACE_WRITE,
        )

    @property
    def allows_network(self) -> bool:
        if self.kind is SandboxKind.READ_ONLY:
            return False
        if self.kind is SandboxKind.WORKSPACE_WRITE:
            return self.network_allowed
        return True


def read_only() -> SandboxPolicy:
    return SandboxPolicy(kind=SandboxKind.READ_ONLY)


def campaign_workspace_policy(policy: SandboxPolicy) -> SandboxPolicy:
    from co_scientist.llm import campaign_free_mode

    if not campaign_free_mode():
        return policy
    if not policy.confines_in_process:
        raise RuntimeError("campaign workspace requires OS confinement")
    return replace(policy, network_allowed=False)


def workspace_write(*roots: Path, network_allowed: bool = False) -> SandboxPolicy:
    return SandboxPolicy(
        kind=SandboxKind.WORKSPACE_WRITE,
        writable_roots=tuple(roots),
        network_allowed=network_allowed,
    )
