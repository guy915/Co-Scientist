"""Reading the skills directory into a catalogue and one document.

The two halves are deliberately different sizes, and that is the whole
design. Every skill contributes a name and one description to the
catalogue the model sees on every turn; only a skill the model asks for
contributes its document, which runs to hundreds of lines. Sending all
of them would cost more per turn than the tools they describe.

Only the frontmatter is trusted for the catalogue. A ``SKILL.md`` carries
exactly two frontmatter keys upstream (``name`` and ``description``), and
a directory whose frontmatter is missing or malformed is skipped rather
than defaulted -- a skill the model cannot be told the purpose of is one
it would invoke by guessing.
"""

from __future__ import annotations

import functools
import logging
import os
import pathlib
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR_ENV = "COSCIENTIST_SKILLS_DIR"
SKILLS_PYTHON_ENV = "COSCIENTIST_SKILLS_PYTHON"

# Upstream instructions say to invoke a skill's scripts with `uv run`,
# which resolves their PEP 723 dependencies at execution time. That
# cannot happen inside the sandbox -- uv's cache contains a directory
# named `.git`, which is protected metadata, so uv cannot even
# initialise. The image resolves the closure once at build time instead
# and this interpreter is where it landed; the scripts themselves are
# unmodified, because a PEP 723 header is inert to a plain `python`.
_FALLBACK_SKILLS_PYTHON = "python3"

# A whole document, not an excerpt: these run to a few hundred lines and
# the model asked for exactly one. The bound exists so a malformed or
# hostile file cannot flood the transcript, not to trim a real skill.
MAX_SKILL_DOCUMENT_CHARS = 60_000

_DOCUMENT_NAME = "SKILL.md"


@dataclass(frozen=True)
class Skill:
    """One skill the model may ask to read.

    Attributes:
        name: The skill's own name, from its frontmatter. This is what
            the model passes back to read it.
        description: One paragraph saying what the skill is for and,
            usually, what it is not for.
        directory: Where the skill lives, so its scripts can be run.
    """

    name: str
    description: str
    directory: pathlib.Path


def skills_directory() -> pathlib.Path | None:
    """Returns the configured skills directory, or None when unset.

    Returns:
        The directory named by ``COSCIENTIST_SKILLS_DIR`` when it exists,
        otherwise None. Unset and missing are the same answer on purpose:
        both mean this deployment has no skills, and neither is an error.
    """
    raw = os.environ.get(SKILLS_DIR_ENV, "").strip()
    if not raw:
        return None
    directory = pathlib.Path(raw)
    if not directory.is_dir():
        logger.warning(
            "%s is set to %r, which is not a directory; no skills available",
            SKILLS_DIR_ENV,
            raw,
        )
        return None
    return directory


def skills_python() -> str:
    """Returns the interpreter a skill's scripts should be run with."""
    return os.environ.get(SKILLS_PYTHON_ENV, "").strip() or (
        _FALLBACK_SKILLS_PYTHON
    )


def _parse_frontmatter(text: str) -> dict[str, object] | None:
    """Extracts the YAML frontmatter block from a document.

    Args:
        text: The document's full text.

    Returns:
        The parsed mapping, or None when the document has no frontmatter
        block or its block is not a mapping.
    """
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        parsed = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _load_skill(directory: pathlib.Path) -> Skill | None:
    """Reads one skill directory into a catalogue entry.

    Args:
        directory: A candidate skill directory.

    Returns:
        The skill, or None when it carries no readable ``SKILL.md`` with
        both a name and a description.
    """
    document = directory / _DOCUMENT_NAME
    try:
        text = document.read_text(encoding="utf-8")
    except OSError:
        return None
    front = _parse_frontmatter(text)
    if front is None:
        return None
    name = str(front.get("name") or "").strip()
    description = " ".join(str(front.get("description") or "").split())
    if not name or not description:
        return None
    return Skill(name=name, description=description, directory=directory)


@functools.cache
def available_skills() -> tuple[Skill, ...]:
    """Returns every readable skill, ordered by name.

    Cached: the directory is baked into the image and cannot change while
    the process runs, and this is read on every tool-loop turn.

    Returns:
        The catalogue, empty when no skills directory is configured.
    """
    directory = skills_directory()
    if directory is None:
        return ()
    found = [
        skill
        for child in sorted(directory.iterdir())
        if child.is_dir() and (skill := _load_skill(child)) is not None
    ]
    if found:
        logger.info("Loaded %d skills from %s", len(found), directory)
    else:
        logger.warning("No readable skills in %s", directory)
    return tuple(found)


def find_skill(name: str) -> Skill | None:
    """Looks a skill up by the name the catalogue advertised.

    Args:
        name: The skill's name.

    Returns:
        The skill, or None when no skill carries that name.
    """
    wanted = name.strip().lower()
    for skill in available_skills():
        if skill.name.lower() == wanted:
            return skill
    return None


def catalogue_section() -> str:
    """Renders the catalogue for a prompt.

    Returns:
        One line per skill, or an empty string when there are none -- so
        a caller can concatenate this unconditionally and a deployment
        without skills renders no section at all.
    """
    skills = available_skills()
    if not skills:
        return ""
    lines = [f"- {skill.name}: {skill.description}" for skill in skills]
    return "\n".join(lines)


def read_skill_document(name: str) -> str | None:
    """Returns one skill's full instructions, with how to run it.

    The preamble is the one thing the document does not say correctly
    here: upstream tells the model to use ``uv run``, which this harness
    cannot. Stating the substitution beside the document -- rather than
    editing the vendored file -- keeps the tree byte-identical to the
    revision it is pinned to.

    Args:
        name: The skill's name, as advertised in the catalogue.

    Returns:
        The document, or None when no such skill exists or it could not
        be read.
    """
    skill = find_skill(name)
    if skill is None:
        return None
    try:
        text = (skill.directory / _DOCUMENT_NAME).read_text(encoding="utf-8")
    except OSError:
        return None
    preamble = (
        f"Skill directory: {skill.directory}\n"
        f"Run this skill's scripts with `{skills_python()} "
        f"{skill.directory}/scripts/<script>.py`, from the workspace, via "
        "run_command. Ignore any instruction below to use `uv run` or to "
        "install packages: dependencies are already installed and the "
        "network is available for the skill's own API calls only.\n"
        "Write results to a file with the script's own output option "
        "wherever it has one, then read the fields you need.\n\n"
    )
    return (preamble + text)[:MAX_SKILL_DOCUMENT_CHARS]
