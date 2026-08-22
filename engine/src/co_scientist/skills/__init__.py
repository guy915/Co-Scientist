"""The vendored science skills, as something an agent can find and read.

A skill is a directory of instructions and scripts (see
``vendor/science-skills``). This package is the part that makes one
reachable: it reads the catalogue, hands the model a name and a
description per skill, and returns the full document only when the model
asks for it. Nothing here executes anything -- a skill's scripts run
through the workspace's ordinary ``run_command``, confined like any other
command, which is why adding skills needed no second execution path.

Absent by default. ``COSCIENTIST_SKILLS_DIR`` is set by the api image and
by nothing else, so a checkout, a test and a CI job all see an empty
catalogue and behave exactly as they did before skills existed.
"""

from co_scientist.skills.catalog import (
    Skill,
    available_skills,
    catalogue_section,
    read_skill_document,
    skills_directory,
)
from co_scientist.skills.credentials import (
    is_skill_invocation,
    skill_environment,
)
from co_scientist.skills.licences import (
    notified_sources,
    seed_licence_notices,
)

__all__ = [
    "Skill",
    "available_skills",
    "catalogue_section",
    "is_skill_invocation",
    "notified_sources",
    "read_skill_document",
    "seed_licence_notices",
    "skill_environment",
    "skills_directory",
]
