import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from Bio import Entrez

from mcp_server.campaign import campaign_free_mode

logger = logging.getLogger(__name__)


def read_entrez(handle: Any) -> Any:
    """Pace before sending requests, not while parsing their responses."""
    try:
        return Entrez.read(handle)
    except Exception:
        logger.debug("Entrez response parsing failed", exc_info=True)
        raise
    finally:
        handle.close()


# Biopython stores credentials process-wide, so configure once across tool
# modules.
_entrez_initialized = False


def initialize_entrez() -> None:
    """NCBI rejects empty api_key parameters with HTTP 400; omit unset keys."""
    global _entrez_initialized

    if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        raise RuntimeError("Disabling TLS verification is unsupported")

    if _entrez_initialized:
        return

    # Set the guard first so failed initialization cannot repeat warnings on
    # every import.
    _entrez_initialized = True
    _init_entrez_email()
    _init_entrez_api_key()


def _init_entrez_email() -> None:
    if Entrez.email:
        return

    entrez_email = os.environ.get("ENTREZ_EMAIL")
    if entrez_email:
        Entrez.email = entrez_email
        logger.info("Initialized Entrez with email: %s", entrez_email)
    else:
        # NCBI asks for a contact email to identify traffic; requests
        # still work without one but may be throttled more readily.
        logger.warning("ENTREZ_EMAIL not set - PubMed may have stricter rate limits")


def _init_entrez_api_key() -> None:
    if Entrez.api_key:
        return

    entrez_key = os.environ.get("ENTREZ_API_KEY")
    if entrez_key:
        Entrez.api_key = entrez_key
        logger.info("Initialized Entrez with API key")
    else:
        # NCBI permits 3 requests/s without a key, 10 with one.
        logger.info("ENTREZ_API_KEY not set - using default rate limits")


# Pace the entire process just below NCBI's 10/s keyed and 3/s unkeyed ceilings.
_INTERVAL_WITH_API_KEY = 0.11
_INTERVAL_WITHOUT_API_KEY = 0.4

_lock = threading.Lock()
_next_slot = 0.0

# Indirect clock/sleep hooks let tests avoid real elapsed waits.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def _request_interval() -> float:
    initialize_entrez()
    return (
        _INTERVAL_WITH_API_KEY
        if Entrez.api_key and not campaign_free_mode()
        else _INTERVAL_WITHOUT_API_KEY
    )


def _await_slot() -> None:
    interval = _request_interval()
    with _lock:
        now = _clock()
        start = max(now, _next_slot)
        _claim_slot(start + interval)
    delay = start - now
    if delay > 0:
        _sleep(delay)


def _claim_slot(next_slot: float) -> None:
    """The caller must hold the process-wide pacer lock."""
    global _next_slot
    _next_slot = next_slot


def entrez_call(request: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Every Entrez request must use this seam to preserve process-wide NCBI
    pacing.
    """
    # Biopython's key is process-global. Passing None suppresses it for this
    # request even when a standard user's key was loaded earlier in the process.
    if campaign_free_mode():
        kwargs["api_key"] = None
    _await_slot()
    return request(**kwargs)
