"""Scientific skill catalogues, documents, licence notices and scoped usage.

Absent COSCIENTIST_SKILLS_DIR, the catalogue is empty. Scripts execute through
the ordinary confined workspace, and only invoked scripts receive credentials.
"""

from __future__ import annotations

import contextlib
import datetime
import functools
import logging
import os
import pathlib
import re
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass

import yaml

from co_scientist.llm import campaign_free_mode

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


# One skill's PEP 723 inline metadata block, and one dependency line
# inside it. The bundle declares dependencies per script this way rather
# than in a manifest, so this is the only place they are written down.
_METADATA_BLOCK = re.compile(r"# /// script(.*?)# ///", re.S)
_DEPENDENCY = re.compile(r'^#\s*"([A-Za-z0-9._-]+)')


def _normalised(name: str) -> str:
    """Returns a distribution name in PEP 503 comparison form."""
    return re.sub(r"[-_.]+", "-", name).lower()


@functools.cache
def _installed_distributions() -> frozenset[str] | None:
    """Returns what the skills interpreter can import, or None if unknown.

    Read from the interpreter's own ``site-packages`` rather than by
    running it, since this is consulted while building a catalogue that
    a tool loop reads on every turn. None means the layout was not
    recognisable, which is deliberately distinct from "nothing is
    installed": an unknown environment must not silently empty the
    catalogue.
    """
    interpreter = pathlib.Path(skills_python())
    if not interpreter.is_absolute():
        return None
    roots = list((interpreter.parent.parent / "lib").glob("*/site-packages"))
    if not roots:
        return None
    return frozenset(
        _normalised(entry.name.split("-")[0])
        for root in roots
        for entry in root.glob("*.dist-info")
    )


def _runnable_scripts(directory: pathlib.Path) -> list[pathlib.Path]:
    """Returns the skill's executable scripts, newest-sorted for stability."""
    scripts = directory / "scripts"
    return sorted(scripts.glob("*.py")) if scripts.is_dir() else []


def _unmet_dependencies(directory: pathlib.Path) -> set[str]:
    """Returns the skill's declared dependencies that are not installed.

    Empty whenever the installed set is unknown, so an unrecognised
    environment offers every skill exactly as before this check existed.
    """
    installed = _installed_distributions()
    if installed is None:
        return set()
    scripts = directory / "scripts"
    sources = sorted(scripts.glob("*.py")) if scripts.is_dir() else []
    declared = (
        set().union(*(_declared_in(s) for s in sources)) if sources else set()
    )
    return declared - installed


def _declared_in(script: pathlib.Path) -> set[str]:
    """Returns the dependencies one script's metadata block declares."""
    try:
        text = script.read_text(encoding="utf-8")
    except OSError:
        return set()
    block = _METADATA_BLOCK.search(text)
    if block is None:
        return set()
    found = (
        _DEPENDENCY.match(line.strip()) for line in block.group(1).splitlines()
    )
    return {_normalised(m.group(1)) for m in found if m is not None}


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
    withheld = _withholding_reason(directory)
    if withheld is not None:
        logger.info("Skill %r withheld: %s", name, withheld)
        return None
    return Skill(name=name, description=description, directory=directory)


def _withholding_reason(directory: pathlib.Path) -> str | None:
    """Says why this skill cannot be used here, or None if it can.

    Withheld rather than offered and failed at call time, for the same
    reason ``run_command`` is withheld when no sandbox backend exists:
    reading a skill costs a turn and then several thousand tokens
    re-sent on every turn after it, and neither failure below is one the
    model can act on.

    Two cases, six of the vendored 38 skills between them. A skill with
    no script has nothing to run at all -- every step of a skill's
    instructions is a command, so prose alone is a dead end. None of
    those four is a data source: PyMOL needs a binary this image has no
    reason to carry, ``uv`` and ``credentials`` describe setup the
    harness has already done and whose instructions the ``read_skill``
    preamble explicitly overrides, and ``workflow_skill_creator`` authors
    new skills rather than using one. The other two declare a 695 MB
    dependency closure this image deliberately omits, so their scripts
    could only ever raise ImportError.
    """
    if not _runnable_scripts(directory):
        return "no runnable script"
    unmet = _unmet_dependencies(directory)
    if unmet:
        return f"{', '.join(sorted(unmet))} not installed for {skills_python()}"
    return None


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
        "wherever it has one, then read the fields you need. Every "
        "`--output /tmp/...` below is wrong here: the workspace is the "
        "only writable directory, so replace the whole path with a bare "
        "relative filename such as `results.json`. An absolute path is "
        "refused and the script dies having already spent its API "
        "call.\n\n"
    )
    return (preamble + text)[:MAX_SKILL_DOCUMENT_CHARS]


LICENCES_DIRNAME = ".licenses"

# The prerequisite names its own target file, so the filename is read
# from each SKILL.md rather than derived from the directory name -- a
# re-pin that renames one would otherwise leave the model paying the
# toll again for a file we seeded under the old name.
_TARGET = re.compile(r"\.licenses/([A-Za-z0-9_.-]+\.txt)")

# The terms live at URLs the document quotes; capturing them keeps the
# seeded notice specific rather than a generic placeholder.
_URL = re.compile(r"https?://[^\s)>\]]+")

_NOTICE = (
    "Notice recorded by the Co-Scientist harness on {stamp}.\n"
    "This run used the {name} skill. Review that source's terms of use "
    "before relying on or redistributing results:\n{urls}\n"
)


def _skill_notice(name: str, document: str) -> tuple[str, str] | None:
    """Builds one skill's notice file, if it asks for one.

    Args:
        name: The skill's name.
        document: Its ``SKILL.md`` text.

    Returns:
        A (filename, contents) pair, or None when the skill states no
        licence prerequisite.
    """
    match = _TARGET.search(document)
    if match is None:
        return None
    prerequisite = document[: match.end() + 600]
    urls = sorted(set(_URL.findall(prerequisite)))
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    return match.group(1), _NOTICE.format(
        stamp=stamp,
        name=name,
        urls="\n".join(f"  {url}" for url in urls) or "  (see SKILL.md)",
    )


def _write_notice(directory: pathlib.Path, skill: Skill) -> bool:
    """Writes one skill's notice, reporting whether it needed one.

    Returns:
        True when a notice was written, False when the skill states no
        licence prerequisite or its files could not be read or written.
    """
    try:
        document = (skill.directory / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return False
    notice = _skill_notice(skill.name, document)
    if notice is None:
        return False
    filename, contents = notice
    try:
        (directory / filename).write_text(contents, encoding="utf-8")
    except OSError as exc:
        logger.warning("could not write %s: %s", filename, exc)
        return False
    return True


def seed_licence_notices(root: pathlib.Path) -> int:
    """Writes every skill's licence notice into a workspace.

    Best-effort by design: a workspace that cannot hold these is a
    workspace whose simulation is about to fail for a better reason, and
    refusing to open it here would turn a cosmetic problem into a lost
    review.

    Args:
        root: The workspace root the skills will run from.

    Returns:
        How many notices were written.
    """
    skills = available_skills()
    if not skills:
        return 0
    directory = root / LICENCES_DIRNAME
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("could not create %s: %s", directory, exc)
        return 0
    written = sum(_write_notice(directory, skill) for skill in skills)
    logger.info("Seeded %d skill licence notices in %s", written, directory)
    return written


class SkillUsage:
    """Mutable skill-name-to-invocation-count tally for one node."""

    def __init__(self) -> None:
        """Start with an empty tally."""
        self._counts: dict[str, int] = {}

    def record(self, name: str) -> None:
        """Count one invocation of the named skill."""
        self._counts[name] = self._counts.get(name, 0) + 1

    def snapshot(self) -> dict[str, int]:
        """Return the tally as a plain dict, safe to hand to metrics."""
        return dict(self._counts)


_current_usage: ContextVar[SkillUsage | None] = ContextVar(
    "current_skill_usage", default=None
)


@contextlib.contextmanager
def scoped_skill_usage() -> Iterator[SkillUsage]:
    """Scope a skill tally to one node's execution.

    Yields:
        The tally every skill invocation in this scope is recorded into.
    """
    usage = SkillUsage()
    token = _current_usage.set(usage)
    try:
        yield usage
    finally:
        _current_usage.reset(token)


def record_skill_use(name: str) -> None:
    """Record one skill invocation into the active scope, if any.

    Args:
        name: The skill's declared name, from ``invoked_skill``.
    """
    usage = _current_usage.get()
    if usage is not None:
        usage.record(name)


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
    if campaign_free_mode():
        return {}
    resolved: dict[str, str] = {}
    for wanted, aliases in _CREDENTIAL_ALIASES.items():
        for alias in aliases:
            value = os.environ.get(alias, "").strip()
            if value:
                resolved[wanted] = value
                break
    return resolved


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


__all__ = [
    "Skill",
    "SkillUsage",
    "available_skills",
    "catalogue_section",
    "invoked_skill",
    "read_skill_document",
    "record_skill_use",
    "scoped_skill_usage",
    "seed_licence_notices",
    "skill_environment",
    "skills_directory",
]
