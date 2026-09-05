"""Silence LiteLLM's own logging noise, independent of the root logger.

Split out of ``app.logging_setup`` so that module stays under its line
cap; re-exported there so it stays the stable import surface.
"""

from __future__ import annotations

import logging

# LiteLLM attaches its own handler directly to these loggers at import
# (litellm/_logging.py): a colored StreamHandler defaulting to stderr,
# independent of the root handler ``logging_setup`` configures. Root's own
# level does nothing to it -- an ordinary INFO line comes back as two
# records, a colored one on stderr (Railway reads stderr as
# `severity: error`, and this doubled a stdout call-count taken earlier)
# and a plain one on stdout via propagation to root. ``LITELLM_LOG``
# (litellm's own env var) does not stop either: read once at import, it
# sets only that handler's level, never the logger's own, so propagation
# is unaffected. Setting the level directly on the logger does stop both
# -- a logger's effective level gates whether a record is created at all,
# before any handler runs and before propagation. Verified live: with
# root at INFO, an unpatched ``getLogger("LiteLLM").info(...)`` produced
# both copies regardless of ``LITELLM_LOG``; after ``setLevel(WARNING)``
# it produced neither, and ``.warning()`` still came through on both.
_LITELLM_LOGGER_NAMES: tuple[str, ...] = (
    "LiteLLM",
    "LiteLLM Router",
    "LiteLLM Proxy",
)


def silence_litellm_logging() -> None:
    """Raise LiteLLM's own loggers to WARNING; drop its debug print banner.

    Two unrelated mechanisms. The logger levels (module comment above)
    stop the duplicated per-call INFO lines. ``litellm.suppress_debug_info``
    is unrelated to logging entirely -- the repeated "Provider List"
    banner is a plain ``print()`` in litellm's provider-resolution code,
    guarded only by that flag.

    Called at import of this module, so a durable worker process (which
    never calls ``configure_logging``) inherits this merely by importing
    ``app.logging_setup`` for ``run_log_context``, and again from
    ``configure_logging`` itself so reconfiguring cannot leave it unset.
    """
    for name in _LITELLM_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        import litellm
    except ImportError:
        return
    litellm.suppress_debug_info = True


silence_litellm_logging()
