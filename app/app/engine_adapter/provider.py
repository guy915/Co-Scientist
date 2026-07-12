"""Provider selection and engine-availability probes.

Decides between the real engine and the mock workflow (`select_provider`),
reports provider diagnostics for the /status route (`system_status`), and
performs the lazy engine import used by the real-engine path.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from app.config import settings

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
def _has_provider_key() -> bool:
    return any(
        bool(os.getenv(k))
        for k in (
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AZURE_API_KEY",
            "DEEPSEEK_API_KEY",
        )
    )


# Checks importability via find_spec rather than a real import, so this can
# be probed cheaply and repeatedly without triggering the engine's own
# import-time side effects (e.g. LangGraph module setup).
def _engine_importable() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("co_scientist") is not None
    except Exception:
        return False


def select_provider() -> str:
    """Return 'mock' or 'engine'. Persisted on the run row."""
    if os.getenv("COSCIENTIST_FORCE_MOCK") == "1":
        return "mock"  # explicit override, e.g. for tests or local dev
    if not _has_provider_key():
        return "mock"  # no LLM credentials configured
    if not _engine_importable():
        return "mock"  # co_scientist package not installed/importable
    return "engine"


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
        "mock_mode": provider == "mock",
        "has_provider_key": has_key,
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
        # The engine is an optional runtime dependency; when absent this
        # import fails and the app falls back to the mock provider.
        from co_scientist import (
            HypothesisGenerator,  # type: ignore[import-not-found, unused-ignore]
        )

        return HypothesisGenerator
    except Exception as e:  # pragma: no cover (defensive)
        logger.error("engine import failed: %s — falling back to mock", e)
        return None
