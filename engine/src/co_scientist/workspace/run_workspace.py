"""Where a run's workspace lives, and why it lives there.

One function decides the directory, so that two callers asking for the
same run get the same files. That is not tidiness -- this host kills and
restarts workers by design (lease expiry, `--reload`, a failed
healthcheck), and a restarted task that resolved its workspace to a fresh
temporary directory would silently redo work whose output was sitting on
disk a few inches away. Reopening is therefore the normal case, not an
edge one, and `open_run_workspace` is idempotent by construction.

**Off the volume, always.** Workspaces are scratch: a simulation's
intermediate arrays, a checked-out repository, spilled command output.
The production volume holds one SQLite file written by one process, and
`COSCIENTIST_CACHE_DIR` was moved off it for exactly this reason -- a full
volume takes the database down, and the database is the run. So the
default root is the system temp directory, and an operator who overrides
`COSCIENTIST_WORKSPACE_DIR` onto a volume is making a choice this module
cannot make for them.

**The run id is treated as untrusted.** It reaches here from a request,
and it is being used to build a path. A run id of `../../etc` would
otherwise resolve a "workspace" wherever it liked -- and the sandbox
would then be handed that directory as a *writable root*, so the
containment argument would be arguing for the escape.
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from co_scientist.workspace.output import SecretRegistry
from co_scientist.workspace.session import WorkspaceSession
from co_scientist.workspace.tools import WorkspaceToolProvider

logger = logging.getLogger(__name__)

WORKSPACE_DIR_ENV = "COSCIENTIST_WORKSPACE_DIR"

# Name of the directory workspaces are created under, inside whichever
# root is resolved.
_WORKSPACES_DIRNAME = "coscientist-workspaces"

# Subdirectory of a run's workspace holding one directory per variant.
_VARIANTS_DIRNAME = "variants"
_REVIEWS_DIRNAME = "reviews"
_DRAFTS_DIRNAME = "drafts"

# Everything else in a run id is replaced. Deliberately narrow: real ids
# are uuids, so anything outside this set is either a bug or an attempt.
_UNSAFE_IN_RUN_ID = re.compile(r"[^A-Za-z0-9_-]")

# Longest directory name built from a run id. Long ids are truncated
# rather than rejected, but the truncation keeps the front, which is
# where a uuid's entropy is.
_MAX_RUN_ID_CHARS = 64


class WorkspaceIdError(ValueError):
    """A run id that cannot be turned into a directory name."""


def _safe_run_id(run_id: str) -> str:
    """Reduces a run id to something safe to use as a directory name.

    Args:
        run_id: The run identifier, as it arrived.

    Returns:
        The sanitized name.

    Raises:
        WorkspaceIdError: If nothing usable survives sanitization. Empty
            would resolve to the workspaces root itself, handing every
            run one shared directory.
    """
    cleaned = _UNSAFE_IN_RUN_ID.sub("_", run_id)[:_MAX_RUN_ID_CHARS]
    if not cleaned.strip("_"):
        raise WorkspaceIdError(
            f"run id {run_id!r} contains nothing usable as a directory name"
        )
    if cleaned != run_id:
        logger.warning(
            "run id %r was sanitized to %r for use as a path", run_id, cleaned
        )
    return cleaned


def workspaces_root() -> Path:
    """Returns the directory all run workspaces are created under."""
    override = os.getenv(WORKSPACE_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path(tempfile.gettempdir()).resolve() / _WORKSPACES_DIRNAME


def workspace_path(run_id: str) -> Path:
    """Returns one run's workspace directory, without creating it.

    Args:
        run_id: The run identifier.

    Returns:
        The absolute path this run's workspace resolves to.
    """
    return workspaces_root() / _safe_run_id(run_id)


def open_run_workspace(
    run_id: str, *, network_allowed: bool = False
) -> WorkspaceSession:
    """Opens (creating if absent) the workspace belonging to a run.

    Args:
        run_id: The run identifier.
        network_allowed: Whether commands may reach the network. Off by
            default: a hypothesis test that needs the internet is a
            deliberate decision, not the resting state.

    Returns:
        A session confined to that run's directory.
    """
    root = workspace_path(run_id)
    existed = root.exists()
    session = WorkspaceSession(root, network_allowed=network_allowed)
    # 0o700: the workspace holds whatever a run was given to work on.
    # Best-effort, because a filesystem that cannot express it is not a
    # reason to refuse the run.
    try:
        root.chmod(0o700)
    except OSError as exc:  # pragma: no cover - filesystem-dependent
        logger.debug("could not restrict workspace permissions: %s", exc)
    logger.info(
        "%s workspace for run %s at %s",
        "reopened" if existed else "created",
        run_id,
        root,
    )
    return session


def variant_workspace_path(run_id: str, variant_id: str) -> Path:
    """Returns one variant's directory, without creating it."""
    return workspace_path(run_id) / _VARIANTS_DIRNAME / _safe_run_id(variant_id)


def open_variant_workspace(
    run_id: str, variant_id: str, *, network_allowed: bool = False
) -> WorkspaceSession:
    """Opens the workspace belonging to one variant of one run.

    Variants of a run are proposed and evaluated concurrently, so they
    cannot share the run's directory: two evaluations writing their
    programs to the same paths would each run partly the other's code,
    and the resulting scores would be attributed to the wrong variants.
    Nothing about that failure is visible in a result -- both variants
    return a plausible number -- so the isolation has to be structural
    rather than a convention about who writes when.

    Args:
        run_id: The run identifier.
        variant_id: The variant identifier.
        network_allowed: Whether commands may reach the network.

    Returns:
        A session confined to that variant's directory.
    """
    root = variant_workspace_path(run_id, variant_id)
    # The run's own directory is created (and permission-restricted)
    # first, so the variant tree never exists under a world-readable
    # parent even for the moment between the two mkdirs.
    open_run_workspace(run_id, network_allowed=network_allowed)
    return WorkspaceSession(root, network_allowed=network_allowed)


def draft_workspace_path(run_id: str, draft_id: str) -> Path:
    """Returns one drafting pass's directory, without creating it."""
    return workspace_path(run_id) / _DRAFTS_DIRNAME / _safe_run_id(draft_id)


def open_draft_workspace(run_id: str, draft_id: str) -> WorkspaceSession:
    """Opens the workspace one hypothesis-drafting pass works in.

    This is the generation agent's literature-exploration step, and the
    one consumer the science skills are turned on for: retrieval is what
    the step is for, so a skill that queries a database serves the work
    rather than competing with it. The network comes with them and is
    the reason they are here -- a skill that cannot reach its API is a
    document about an API.

    Per pass rather than per run because a run drafts on every
    generation cycle, and a directory holding the previous cycle's
    result files invites the model to read a stale one as its own.

    Args:
        run_id: The run identifier.
        draft_id: Identifier unique to this drafting pass.

    Returns:
        A session confined to that pass's directory, with the network
        open and the skills offered.
    """
    root = draft_workspace_path(run_id, draft_id)
    # As with variants and reviews: the run directory is created (and
    # permission-restricted) first so this tree is never briefly
    # world-readable.
    open_run_workspace(run_id)
    return WorkspaceSession(root, network_allowed=True, skills_enabled=True)


def review_workspace_path(run_id: str, hypothesis_id: str) -> Path:
    """Returns one review's directory, without creating it."""
    return (
        workspace_path(run_id) / _REVIEWS_DIRNAME / _safe_run_id(hypothesis_id)
    )


def open_review_workspace(
    run_id: str, hypothesis_id: str, *, network_allowed: bool = False
) -> WorkspaceSession:
    """Opens the workspace one review of one hypothesis works in.

    Per hypothesis for the same reason variants get their own
    directory: reviews of a round's hypotheses are fanned out as
    separate leased tasks and run concurrently, so a shared directory
    would have two simulations each reading part of the other's model.
    Both would then report a coherent-looking observation about the
    wrong hypothesis, which no review makes visible.

    Args:
        run_id: The run identifier.
        hypothesis_id: The hypothesis being reviewed.
        network_allowed: Whether commands may reach the network.

    Returns:
        A session confined to that review's directory.
    """
    root = review_workspace_path(run_id, hypothesis_id)
    # As with variants: the run directory is created (and
    # permission-restricted) first so this tree is never briefly
    # world-readable.
    open_run_workspace(run_id, network_allowed=network_allowed)
    return WorkspaceSession(root, network_allowed=network_allowed)


def build_workspace_tools(
    run_id: str,
    *,
    delegate: Any | None = None,
    network_allowed: bool = False,
    secrets: SecretRegistry | None = None,
) -> WorkspaceToolProvider:
    """Builds the tool provider a run's agent should be handed.

    Args:
        run_id: The run identifier.
        delegate: The run's MCP tool provider, so the model sees one
            surface rather than two.
        network_allowed: Whether commands may reach the network.
        secrets: Values to mask; defaults to the host's credential-shaped
            environment variables.

    Returns:
        A provider serving the workspace tools and delegating the rest.
    """
    return WorkspaceToolProvider(
        open_run_workspace(run_id, network_allowed=network_allowed),
        delegate=delegate,
        secrets=secrets,
    )
