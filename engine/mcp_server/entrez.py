"""Shared NCBI Entrez credential initialization."""

import logging
import os

from Bio import Entrez

logger = logging.getLogger(__name__)

# Module-level guard: Biopython's Entrez client stores credentials as
# process-global attributes (Entrez.email, Entrez.api_key) rather than on an
# instance, so initialization only needs to happen once per process even
# though multiple tool modules call initialize_entrez() at import time.
_entrez_initialized = False


def initialize_entrez() -> None:
    """Initializes Entrez with email and API key from the environment.

    Idempotent: configuration is applied and warnings logged only on the first
    call. NCBI rejects a request carrying an empty ``api_key=`` query parameter
    with HTTP 400 while accepting one that omits it, so an unset key is left
    unassigned rather than blanked.
    """
    global _entrez_initialized

    if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        raise RuntimeError("Disabling TLS verification is unsupported")

    if _entrez_initialized:
        return

    # Set the flag before doing the work (rather than after) so a failure
    # partway through does not cause every subsequent call to retry and
    # re-log the same warnings.
    _entrez_initialized = True
    _init_entrez_email()
    _init_entrez_api_key()


def _init_entrez_email() -> None:
    """Sets Entrez.email from ENTREZ_EMAIL if not already configured."""
    if Entrez.email:
        return

    entrez_email = os.environ.get("ENTREZ_EMAIL")
    if entrez_email:
        Entrez.email = entrez_email
        logger.info("Initialized Entrez with email: %s", entrez_email)
    else:
        # NCBI asks for a contact email to identify traffic; requests
        # still work without one but may be throttled more readily.
        logger.warning(
            "ENTREZ_EMAIL not set - PubMed may have stricter rate limits"
        )


def _init_entrez_api_key() -> None:
    """Sets Entrez.api_key from ENTREZ_API_KEY if not already configured."""
    if Entrez.api_key:
        return

    entrez_key = os.environ.get("ENTREZ_API_KEY")
    if entrez_key:
        Entrez.api_key = entrez_key
        logger.info("Initialized Entrez with API key")
    else:
        # Without a key NCBI enforces the default ~3 requests/second
        # rate limit rather than the higher registered-key limit.
        logger.info("ENTREZ_API_KEY not set - using default rate limits")
