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

# How much of a description reaches the catalogue. See
# `catalogue_section` for the measurement behind it.
MAX_SUMMARY_CHARS = 160

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


def _routing_summary(description: str) -> str:
    """Reduces a description to the part that decides whether to read it.

    Upstream descriptions run two to five sentences: what the skill is
    for, then when not to use it and which sibling to use instead. All
    of it is useful once, and the first sentence is what a routing
    decision actually turns on -- so the rest is bought back by the
    document, which the model reads before using the skill anyway.

    Args:
        description: The skill's full description.

    Returns:
        Its first sentence, hard-capped.
    """
    head = description.split(". ", 1)[0].rstrip(".")
    return (
        f"{head[: MAX_SUMMARY_CHARS - 1]}\u2026"
        if (len(head) > MAX_SUMMARY_CHARS)
        else f"{head}."
    )


def catalogue_section() -> str:
    """Renders the catalogue for a prompt.

    Every line is re-sent on every turn of a tool loop, so this is a
    per-turn tax paid by a decision made once. Measured on a live
    simulation review: full descriptions cost ~2.4k tokens a turn, which
    over ten turns is a quarter of the loop's whole prompt budget --
    more than every tool result in it put together. Hence the summary.

    Returns:
        One line per skill, or an empty string when there are none -- so
        a caller can concatenate this unconditionally and a deployment
        without skills renders no section at all.
    """
    skills = available_skills()
    if not skills:
        return ""
    lines = [
        f"- {skill.name}: {_routing_summary(skill.description)}"
        for skill in skills
    ]
    return "\n".join(lines)


def _skill_file(skill: Skill, path: str) -> pathlib.Path | None:
    """Resolves one file inside a skill directory, or None.

    The model chooses this path, so it is resolved and checked to be
    inside the skill rather than trusted: ``../`` in a tool argument is
    a file read anywhere on the image.
    """
    candidate = (skill.directory / path).resolve()
    root = skill.directory.resolve()
    if candidate == root or root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _read_text(target: pathlib.Path | None) -> str | None:
    """Reads a file, or returns None where there is nothing to read."""
    if target is None:
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None


def read_skill_document(name: str, path: str | None = None) -> str | None:
    """Returns one skill's instructions, or one file it points at.

    The bundle's own disclosure is two levels deep, not one: 20 of the
    38 skills give the overview in ``SKILL.md`` and put the actual
    command syntax in ``references/*.md``, told to the model as "read
    the following reference files based on the request". Serving only
    the first level leaves it holding a document that names a file it
    cannot open, and what it does then is guess the arguments -- which
    is what a live drafting pass did, reaching STRING's CLI with no
    subcommand and getting exit 2 back.

    The preamble is the part the document does not say correctly here.
    Upstream tells the model to use ``uv run``, which this harness
    cannot; and several skills instruct it to stop and ask the user
    something, which in an autonomous run stops it in front of nobody.
    Stating both beside the document -- rather than editing the vendored
    file -- keeps the tree byte-identical to the revision it is pinned
    to.

    Args:
        name: The skill's name, as advertised in the catalogue.
        path: A file inside the skill, relative to its directory, as
            named by its own document. Defaults to ``SKILL.md``.

    Returns:
        The text, or None when no such skill or file exists, or it could
        not be read.
    """
    skill = find_skill(name)
    if skill is None:
        return None
    target = (
        skill.directory / _DOCUMENT_NAME
        if path is None
        else _skill_file(skill, path)
    )
    text = _read_text(target)
    if text is None:
        return None
    if path is not None:
        return text[:MAX_SKILL_DOCUMENT_CHARS]
    preamble = (
        f"Skill directory: {skill.directory}\n"
        f"Run this skill's scripts with `{skills_python()} "
        f"{skill.directory}/scripts/<script>.py`, from the workspace, via "
        "run_command. Ignore any instruction below to use `uv run` or to "
        "install packages: dependencies are already installed and the "
        "network is available for the skill's own API calls only.\n"
        "Where this document points at a file under `references/`, read "
        "it by calling read_skill again with that path -- the exact "
        "command syntax usually lives there, not here.\n"
        "There is no user to ask. Where this document says to stop and "
        "ask a question, choose the most reasonable answer, say which "
        "you chose, and carry on.\n"
        "Write results to a file with the script's own output option "
        "wherever it has one, then read the fields you need. Give that "
        "option a bare relative filename such as `results.json`: the "
        "workspace is the only writable directory, so an absolute path "
        "like /tmp/results.json is refused and the script dies having "
        "already spent its API call.\n\n"
    )
    return (preamble + text)[:MAX_SKILL_DOCUMENT_CHARS]
