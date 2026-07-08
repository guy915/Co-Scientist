"""Shared NCBI Entrez credential and SSL initialization."""
# pylint: disable=inconsistent-quotes

import logging
import os
import ssl

from Bio import Entrez

logger = logging.getLogger(__name__)

# Module-level guard: Biopython's Entrez client stores credentials as
# process-global attributes (Entrez.email, Entrez.api_key) rather than on an
# instance, so initialization only needs to happen once per process even
# though multiple tool modules call initialize_entrez() at import time.
_entrez_initialized = False


def initialize_entrez() -> None:
    """Initializes Entrez with email, API key, and SSL policy from the env.

    Idempotent: configuration is applied and warnings logged only on the first
    call. NCBI rejects a request carrying an empty ``api_key=`` query parameter
    with HTTP 400 while accepting one that omits it, so an unset key is left
    unassigned rather than blanked.
    """
    global _entrez_initialized  # pylint: disable=global-statement

    if _entrez_initialized:
        return

    # Set the flag before doing the work (rather than after) so a failure
    # partway through does not cause every subsequent call to retry and
    # re-log the same warnings.
    _entrez_initialized = True
    # Opt-in only: NCBI's cert chain is normally fine, this env var exists
    # for environments with broken/incomplete local CA bundles.
    ssl_verify = os.environ.get("DISABLE_SSL_VERIFY",
                                "").lower() in ("true", "1", "yes")
    logger.debug("SSL verification: %s", ssl_verify)

    if not Entrez.email:
        entrez_email = os.environ.get("ENTREZ_EMAIL")
        if entrez_email:
            Entrez.email = entrez_email
            logger.info("Initialized Entrez with email: %s", entrez_email)
        else:
            # NCBI asks for a contact email to identify traffic; requests
            # still work without one but may be throttled more readily.
            logger.warning(
                "ENTREZ_EMAIL not set - PubMed may have stricter rate limits")

    if not Entrez.api_key:
        entrez_key = os.environ.get("ENTREZ_API_KEY")
        if entrez_key:
            Entrez.api_key = entrez_key
            logger.info("Initialized Entrez with API key")
        else:
            # Without a key NCBI enforces the default ~3 requests/second
            # rate limit rather than the higher registered-key limit.
            logger.info("ENTREZ_API_KEY not set - using default rate limits")

    if not ssl_verify:
        # Deliberate runtime monkeypatch to disable cert verification; the two
        # SSL context factory signatures are interchangeable at call sites here.
        # pylint: disable=protected-access
        ssl._create_default_https_context = (
            ssl._create_unverified_context  # type: ignore[assignment]
        )
        # pylint: enable=protected-access
