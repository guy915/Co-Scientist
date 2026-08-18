"""macOS confinement: a SandboxPolicy rendered as sandbox-exec arguments.

Composes the vendored base profile with per-policy read, write, and
network sections, and passes every path as a ``-D`` *parameter* rather
than interpolating it into the policy text. That distinction is a
security property, not a style: a path containing a quote or a newline
interpolated into SBPL source would let the path's author rewrite the
policy that is supposed to contain them.

Rule ordering is load-bearing. SBPL is last-match-wins, so the deny that
protects repository metadata is emitted *after* the writable-root allow
it needs to override. Reordering these sections silently widens the
sandbox while every test that only inspects argv keeps passing.
"""

from pathlib import Path

from co_scientist.sandbox.policy import (
    PROTECTED_METADATA_NAMES,
    SandboxPolicy,
)

# Only ever the absolute path. Resolving via PATH would let anything that
# can prepend to PATH substitute its own "sandbox-exec" and be handed the
# command to run unconfined.
SEATBELT_EXECUTABLE = "/usr/bin/sandbox-exec"

_BASE_POLICY_PATH = Path(__file__).with_name("seatbelt_base_policy.sbpl")

_WRITABLE_ROOT_PARAM = "WRITABLE_ROOT_{index}"

# Reading is permitted wherever the invoking user could already read.
# Confining reads is a separate feature (Codex has one) that would need
# its own policy surface; claiming it here without implementing it would
# be worse than not offering it.
_ALLOW_READ_SECTION = "(allow file-read*)"

# Chosen over `(allow network*)`: outbound is what analysis code needs
# when it needs anything, and binding a listening socket inside a
# sandbox is not something this host has a use for.
_ALLOW_NETWORK_SECTION = "(allow network-outbound)\n(allow system-socket)"


def _load_base_policy() -> str:
    """Reads the vendored base profile from disk."""
    return _BASE_POLICY_PATH.read_text(encoding="utf-8")


def _writable_root_params(policy: SandboxPolicy) -> dict[str, Path]:
    """Maps each writable root to the SBPL parameter naming it."""
    return {
        _WRITABLE_ROOT_PARAM.format(index=i): root
        for i, root in enumerate(policy.writable_roots)
    }


def _write_section(param_names: list[str]) -> str:
    """Builds the allow-write rules for the given root parameters."""
    if not param_names:
        return ""
    subpaths = "\n  ".join(
        f'(subpath (param "{name}"))' for name in param_names
    )
    return f"(allow file-write*\n  {subpaths}\n)"


def _escape_regex(literal: str) -> str:
    """Escapes a literal for use inside an SBPL regex."""
    return literal.replace(".", r"\.")


def build_policy_text(policy: SandboxPolicy) -> str:
    """Renders the full SBPL source for a policy.

    Args:
        policy: The confinement decision to render. Only its writable
            roots and network flag are read; the caller is responsible
            for having established that this policy is enforced in
            process.

    Returns:
        SBPL source, with every path referenced as a parameter rather
        than embedded.
    """
    param_names = list(_writable_root_params(policy))
    sections = [
        _load_base_policy(),
        _ALLOW_READ_SECTION,
        _write_section(param_names),
        _metadata_denials(param_names),
    ]
    if policy.allows_network:
        sections.append(_ALLOW_NETWORK_SECTION)
    return "\n".join(section for section in sections if section)


def _metadata_denials(param_names: list[str]) -> str:
    """Builds deny rules for protected metadata under every root."""
    if not param_names:
        return ""
    clauses = []
    for name in param_names:
        for metadata in PROTECTED_METADATA_NAMES:
            escaped = _escape_regex(metadata)
            clauses.append(
                f'(regex (string-append (param "{name}")'
                f' #"(/|/.*/){escaped}(/|$)"))'
            )
    joined = "\n  ".join(clauses)
    return f"(deny file-write*\n  {joined}\n)"


def wrap_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    """Wraps a command so the kernel enforces the policy against it.

    Args:
        argv: The command to confine, already split into arguments.
        policy: The confinement decision to enforce.

    Returns:
        A new argv invoking sandbox-exec with the rendered policy, the
        writable roots supplied as ``-D`` parameters, and the original
        command after the ``--`` separator.
    """
    wrapped = [SEATBELT_EXECUTABLE, "-p", build_policy_text(policy)]
    for param, root in _writable_root_params(policy).items():
        wrapped.append(f"-D{param}={root}")
    wrapped.append("--")
    wrapped.extend(argv)
    return wrapped
