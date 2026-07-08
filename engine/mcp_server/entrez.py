"""Shared NCBI Entrez credential and SSL initialization."""
# pylint: disable=inconsistent-quotes

import logging
import os
import ssl

from Bio import Entrez

logger = logging.getLogger(__name__)

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

    _entrez_initialized = True
    ssl_verify = os.environ.get("DISABLE_SSL_VERIFY",
                                "").lower() in ("true", "1", "yes")
    logger.debug("SSL verification: %s", ssl_verify)

    if not Entrez.email:
        entrez_email = os.environ.get("ENTREZ_EMAIL")
        if entrez_email:
            Entrez.email = entrez_email
            logger.info("Initialized Entrez with email: %s", entrez_email)
        else:
            logger.warning(
                "ENTREZ_EMAIL not set - PubMed may have stricter rate limits")

    if not Entrez.api_key:
        entrez_key = os.environ.get("ENTREZ_API_KEY")
        if entrez_key:
            Entrez.api_key = entrez_key
            logger.info("Initialized Entrez with API key")
        else:
            logger.info("ENTREZ_API_KEY not set - using default rate limits")

    if not ssl_verify:
        # Deliberate runtime monkeypatch to disable cert verification; the two
        # SSL context factory signatures are interchangeable at call sites here.
        ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[assignment]  # pylint: disable=protected-access
