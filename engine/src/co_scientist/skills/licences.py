"""Paying the bundle's licence-notice precondition once, not per review.

35 of the 38 vendored skills open with the same prerequisite: if
``.licenses/<skill>_LICENSE.txt`` does not already exist in the workspace
root, prominently notify the user of that data source's terms and then
create the file recording the notice and a timestamp.

Left to the model that is a fixed toll on every first use of every skill,
and it is charged every time: each review runs in its own fresh workspace
(``open_review_workspace``), so the file never pre-exists. Measured on a
live simulation review, one skill's notice cost four turns of a
fourteen-turn budget -- an ``ls``, a ``mkdir``, a ``pwd`` and a
``write_file`` -- before a single query ran.

Seeding the directory when the workspace opens removes the toll and is
also the more faithful reading of the obligation. The skills' own
condition is existence of the file, and a notice written by the harness
is written every time, whereas a notice written by a model is written
when the model remembers to.

What this does **not** do is discharge the underlying duty, which is to
tell a human. A file inside a temporary workspace reaches nobody. The
real surface is the run's report, and that is why ``notified_sources``
records which sources a run touched.
"""

from __future__ import annotations

import datetime
import logging
import pathlib
import re

from co_scientist.skills.catalog import Skill, available_skills

logger = logging.getLogger(__name__)

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


def notified_sources() -> tuple[str, ...]:
    """Returns the skills whose terms a seeded workspace has notified.

    Exposed so the surface that actually reaches a human -- the run's
    report -- can attribute the sources a run could have used, rather
    than the obligation ending at a file in a directory that is deleted.
    """
    return tuple(
        skill.name
        for skill in available_skills()
        if _TARGET.search(
            (skill.directory / "SKILL.md").read_text(
                encoding="utf-8", errors="ignore"
            )
        )
    )
