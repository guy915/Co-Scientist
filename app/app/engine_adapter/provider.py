"""Provider selection and engine-availability probes.

Owns the offline/real LLM-backend split (`offline_mode`,
`resolve_offline_backend`, `sync_engine_llm_backend`), reports provider
diagnostics for the /status route (`system_status`), and performs the lazy
engine import used by the engine path (`select_provider` always resolves to
the engine; the mock workflow is retired).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from app import store
from app.config import any_provider_credential, byok_enabled, settings

# Editable-install .pth files aren't always processed in Python 3.12 venvs.
# Inject the sibling engine src into sys.path at import time so that
# `from co_scientist import HypothesisGenerator` in main.py succeeds.
_engine_src = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "engine", "src")
)
if os.path.isdir(_engine_src) and _engine_src not in sys.path:
    sys.path.insert(0, _engine_src)

logger = logging.getLogger(__name__)


# True if any provider key that LiteLLM/the engine reads from the
# environment is present. Any single key is sufficient to attempt the
# real-engine path; which model actually gets used is a separate concern
# controlled by settings.model_name / settings.supervisor_model_name.
#
# Which env vars count is config.PROVIDER_CREDENTIAL_ENV's to say, not this
# module's: the same question is asked by the semantic safety screen, and the
# two answered it from separately maintained lists until they disagreed.
def _has_provider_key() -> bool:
    return any_provider_credential()


# Checks importability via find_spec rather than a real import, so this can
# be probed cheaply and repeatedly without triggering the engine's own
# import-time side effects (e.g. LangGraph module setup).
def _engine_importable() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("co_scientist") is not None
    except Exception:
        return False


def offline_mode() -> bool:
    """Return whether this process runs against the offline LLM backend.

    True when offline execution is forced (``COSCIENTIST_FORCE_OFFLINE=1``, or
    its deprecated alias ``COSCIENTIST_FORCE_MOCK=1``) or when no provider
    credential is configured. This is a process-level, request-time predicate:
    use it to decide a *new* run's backend, never to infer a *past* run's
    backend (use ``store.run_used_offline`` for that -- see the note in
    ``select_provider``).
    """
    if os.getenv("COSCIENTIST_FORCE_OFFLINE") == "1":
        return True
    if os.getenv("COSCIENTIST_FORCE_MOCK") == "1":
        return True  # deprecated alias, retained for backward compatibility
    return not _has_provider_key()


def select_provider() -> str:
    """Return the workflow provider, always ``"engine"``.

    The mock provider has been retired: every run -- keyless or configured --
    executes on the real engine graph, with keyless/forced runs pinned to the
    deterministic offline LLM backend (see ``offline_mode``). The engine is
    therefore a hard runtime dependency; this raises ``RuntimeError`` when the
    ``co_scientist`` package is not importable rather than silently falling
    back to a mock that no longer exists.

    Raises:
        RuntimeError: When the ``co_scientist`` engine package cannot be
            imported. Called at startup (the lifespan hook), so an unusable
            deployment fails loudly there instead of at the first run.
    """
    if not _engine_importable():
        raise RuntimeError(
            "co_scientist engine is not importable; it is a hard dependency "
            "of the app now that the mock provider has been retired"
        )
    return "engine"


def resolve_offline_backend(cfg: dict[str, Any]) -> bool:
    """Return whether this run's engine execution should be offline-backed.

    The resolved config's ``llm_backend`` key wins when a caller pinned it
    explicitly ("offline" or "real"); a bring-your-own-key run is always
    real-backed (its own validated key must not be shadowed by the
    deterministic router just because the deployment itself is keyless);
    otherwise falls back to the process-level ``offline_mode()`` predicate,
    matching prior behavior for any run that does not set the override.
    """
    backend = cfg.get("llm_backend")
    if backend == "offline":
        return True
    if backend == "real":
        return False
    if cfg.get("byok_provider"):
        return False
    return offline_mode()


def sync_engine_llm_backend(
    run_id: str, cfg: dict[str, Any], db_path: str | None
) -> None:
    """Persist the resolved offline/real backend for an engine run.

    Written at the durable bootstrap, before the engine is dispatched, so
    every later reader (``run_used_offline``, used by generator
    construction, report finalization, and hypothesis badging) reflects the
    resolved config's override rather than whatever was derived when the run
    row was created.
    """
    backend = "offline" if resolve_offline_backend(cfg) else "real"
    store.set_run_llm_backend(run_id, backend, db_path=db_path)


def system_status() -> dict[str, Any]:
    """Return provider/engine diagnostic info for the /status route."""
    has_key = _has_provider_key()
    engine = _engine_importable()
    provider = select_provider()
    # Imported lazily to avoid a package-level import cycle (engine_adapter's
    # __init__ re-exports both this module and tools).
    from app.engine_adapter.tools import tools_config_report

    return {
        "provider": provider,
        "llm_backend": "offline" if offline_mode() else "real",
        "has_provider_key": has_key,
        # Whether this deployment accepts bring-your-own-key runs (the
        # encryption secret is configured). A boolean only: no credential
        # material is ever reported.
        "byok_enabled": byok_enabled(),
        "engine_importable": engine,
        "model_name": settings.model_name,
        # The generator falls back to model_name when supervisor_model_name is
        # unset; effective_supervisor_model mirrors that so /status reports the
        # model actually used for planning/meta-review.
        "supervisor_model_name": settings.effective_supervisor_model,
        "mcp_server_url": settings.mcp_server_url,
        # Effective tools config so the UI/ops can see whether a real run will
        # use the configured domain tools (e.g. INDRA) or the engine defaults.
        **tools_config_report(settings.tools_config),
    }


def _import_hypothesis_generator() -> Any | None:
    """Import the engine's `HypothesisGenerator`, or None if unavailable."""
    try:
        # The engine is a hard runtime dependency; this import only fails
        # if the co_scientist package is missing or broken.
        from co_scientist import (
            HypothesisGenerator,
        )

        return HypothesisGenerator
    except Exception as e:  # pragma: no cover (defensive)
        logger.error("engine import failed: %s", e)
        return None
