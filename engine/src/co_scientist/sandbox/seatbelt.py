"""Pass paths as SBPL parameters to prevent policy injection. Last-match-wins
metadata denials must follow writable-root allows.
"""

from pathlib import Path

from co_scientist.sandbox.policy import (
    METADATA_NAMES,
    SandboxPolicy,
)

# An absolute backend path prevents PATH entries substituting an unconfined
# wrapper.
SEATBELT_EXECUTABLE = "/usr/bin/sandbox-exec"

_BASE_POLICY_PATH = Path(__file__).with_name("seatbelt_base_policy.sbpl")

_WRITABLE_ROOT_PARAM = "WRITABLE_ROOT_{index}"

# Reads follow the invoking user's permissions; restricting them needs a
# separate policy surface.
_ALLOW_READ_SECTION = "(allow file-read*)"

# Outbound analysis access does not require listening sockets.
_ALLOW_NETWORK_SECTION = "(allow network-outbound)\n(allow system-socket)"


def _load_base_policy() -> str:
    return _BASE_POLICY_PATH.read_text(encoding="utf-8")


def _writable_root_params(policy: SandboxPolicy) -> dict[str, Path]:
    return {
        _WRITABLE_ROOT_PARAM.format(index=i): root
        for i, root in enumerate(policy.writable_roots)
    }


def _write_section(param_names: list[str]) -> str:
    if not param_names:
        return ""
    subpaths = "\n  ".join(
        f'(subpath (param "{name}"))' for name in param_names
    )
    return f"(allow file-write*\n  {subpaths}\n)"


def _escape_regex(literal: str) -> str:
    return literal.replace(".", r"\.")


def build_policy_text(policy: SandboxPolicy) -> str:
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
    if not param_names:
        return ""
    clauses = []
    for name in param_names:
        for metadata in METADATA_NAMES:
            escaped = _escape_regex(metadata)
            clauses.append(
                f'(regex (string-append (param "{name}")'
                f' #"(/|/.*/){escaped}(/|$)"))'
            )
    joined = "\n  ".join(clauses)
    return f"(deny file-write*\n  {joined}\n)"


def wrap_argv(argv: list[str], policy: SandboxPolicy) -> list[str]:
    wrapped = [SEATBELT_EXECUTABLE, "-p", build_policy_text(policy)]
    for param, root in _writable_root_params(policy).items():
        wrapped.append(f"-D{param}={root}")
    wrapped.append("--")
    wrapped.extend(argv)
    return wrapped
