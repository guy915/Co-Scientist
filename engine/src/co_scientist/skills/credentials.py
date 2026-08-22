"""Giving a skill its API keys, and giving them to nothing else.

A confined command inherits none of the host's environment
(``WorkspaceSession.run_command`` rebuilds it from ``TMPDIR`` alone),
which is the right default and is also why every credentialed skill
silently returned nothing the first time one ran: a live simulation
review searched PubMed twice, got zero results both times, and reported
the missing key itself.

Handing the credentials to every command would fix that and open a worse
hole. The same workspace runs programs the *model* wrote, against a
network that is now reachable, so a key placed in the shared environment
is a key any generated program can read and send anywhere. Credentials
are therefore injected only for an argv that is recognisably a vendored
skill script run under the baked interpreter -- code we shipped, not
code the model wrote.

Names are translated on the way in. The skills read `NCBI_API_KEY` and
`USER_EMAIL`; this repository has held the same two values as
`ENTREZ_API_KEY` and `ENTREZ_EMAIL` since long before it had skills, and
maintaining one value under two names is how the two come to disagree.
"""

from __future__ import annotations

import os
import pathlib

from co_scientist.skills.catalog import (
    available_skills,
    skills_directory,
    skills_python,
)

# What a skill reads, and every host variable that may already hold it,
# in order of preference. The skill's own name comes first so an
# explicitly-set variable always wins over a translated one.
_CREDENTIAL_ALIASES: dict[str, tuple[str, ...]] = {
    "NCBI_API_KEY": ("NCBI_API_KEY", "ENTREZ_API_KEY"),
    "USER_EMAIL": ("USER_EMAIL", "ENTREZ_EMAIL"),
    "NCBI_TOOL": ("NCBI_TOOL",),
    "ALPHAGENOME_API_KEY": ("ALPHAGENOME_API_KEY",),
    "OPENALEX_API_KEY": ("OPENALEX_API_KEY",),
    "FDA_API_KEY": ("FDA_API_KEY",),
}


def skill_environment() -> dict[str, str]:
    """Collects the credentials the vendored skills know how to read.

    Returns:
        Skill-facing variable names mapped to whatever this host holds
        for them. Absent credentials are omitted rather than set empty:
        several skills branch on presence to pick a rate limit, and an
        empty string reads as present.
    """
    resolved: dict[str, str] = {}
    for wanted, aliases in _CREDENTIAL_ALIASES.items():
        for alias in aliases:
            value = os.environ.get(alias, "").strip()
            if value:
                resolved[wanted] = value
                break
    return resolved


def is_skill_invocation(argv: list[str]) -> bool:
    """Reports whether an argv runs a vendored skill script.

    Both halves are required, and neither is sufficient. The interpreter
    alone would match a model-written program handed to the same
    interpreter; a path under the skills directory alone would match a
    command that merely reads one.

    Args:
        argv: The command as the model asked for it.

    Returns:
        True when the first element is the skills interpreter and some
        later element resolves inside the skills directory.
    """
    return invoked_skill(argv) is not None


def invoked_skill(argv: list[str]) -> str | None:
    """Names the skill an argv runs a script of, or None.

    Attribution needs the name, not the fact: the third-party terms a
    run has to disclose are per source, and a run that queried STRING
    owes STRING's notice and nobody else's.

    Args:
        argv: The command as the model asked for it.

    Returns:
        The skill's declared name, or None when this is not a skill
        invocation -- which includes a model-written program handed to
        the same interpreter, and a command that merely reads a skill.
    """
    directory = skills_directory()
    if directory is None or not argv:
        return None
    if pathlib.Path(argv[0]).name != pathlib.Path(skills_python()).name:
        return None
    for skill in available_skills():
        root = skill.directory.resolve()
        if any(_is_within(argument, root) for argument in argv[1:]):
            return skill.name
    return None


def _is_within(argument: str, root: pathlib.Path) -> bool:
    """Reports whether an argument is a path inside `root`.

    Resolved before comparing, so neither `..` nor a symlink planted in
    the workspace can present itself as a skill script.
    """
    try:
        candidate = pathlib.Path(argument).resolve()
    except (OSError, ValueError):
        return False
    return candidate.is_relative_to(root)
