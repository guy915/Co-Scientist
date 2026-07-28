"""Entrez response reading and error logging for PubMed searches.

Holds the rate-limited ``_entrez_read`` handle reader shared by the PubMed
search and parsing helpers, plus the diagnostic logging for HTTP, URL, and
unexpected errors raised while reading an Entrez response.
"""

import logging
import traceback
from typing import Any, cast
from urllib.error import HTTPError, URLError

from Bio import Entrez

logger = logging.getLogger(__name__)


def _entrez_read(handle: Any) -> dict[str, Any]:
    """Reads an open Entrez response handle.

    Rate limiting does not belong here: by the time a handle exists its
    request has already been sent, so the delay this used to sleep paced
    nothing. Requests are paced before they go out, in
    :func:`mcp_server.entrez_rate_limit.entrez_call`.

    Args:
        handle: Open Entrez response handle.

    Returns:
        Parsed result dict from Entrez.read().

    Raises:
        HTTPError: On HTTP-level errors from the Entrez API.
        URLError: On network-level errors.
    """
    try:
        results = Entrez.read(handle)
        handle.close()
        return cast(dict[str, Any], results)
    except HTTPError as e:
        _log_entrez_read_http_error(e)
        handle.close()
        raise
    except URLError as e:
        _log_entrez_read_url_error(e)
        handle.close()
        raise
    except Exception as e:
        _log_entrez_read_generic_error(e, handle)
        handle.close()
        raise


def _log_entrez_http_error_body(e: HTTPError) -> None:
    """Logs the raw response body off an HTTPError, if still readable.

    Args:
        e: The HTTPError whose response body should be logged.
    """
    try:
        if hasattr(e, "read"):
            error_body = e.read()
            error_text = (
                error_body.decode("utf-8", errors="ignore")
                if isinstance(error_body, bytes)
                else error_body
            )
            logger.debug("Error response body: %s", error_text[:1000])
    except Exception as read_err:
        logger.debug("Could not read error response body: %s", read_err)


def _log_entrez_read_http_error(e: HTTPError) -> None:
    """Logs full diagnostic detail for an HTTPError from an Entrez read.

    Args:
        e: The HTTPError raised while reading the Entrez response.
    """
    logger.error(
        "Entrez HTTP error (%s): %s %s", type(e).__name__, e.code, e.reason
    )
    if hasattr(e, "url"):
        logger.debug("Request URL: %s", e.url)
    if hasattr(e, "headers"):
        logger.debug("Response headers: %s", dict(e.headers))

    # Try to read error response body from the exception
    _log_entrez_http_error_body(e)


def _log_entrez_read_url_error(e: URLError) -> None:
    """Logs diagnostic detail for a URLError from an Entrez read.

    Args:
        e: The URLError raised while reading the Entrez response.
    """
    logger.error(
        "Entrez URL error (%s): %s",
        type(e).__name__,
        e.reason if hasattr(e, "reason") else e,
    )
    if hasattr(e, "url"):
        logger.debug("Request URL: %s", e.url)


def _log_entrez_read_generic_error(e: Exception, handle: Any) -> None:
    """Logs diagnostic detail for an unexpected error from an Entrez read.

    Args:
        e: The exception raised while reading the Entrez response.
        handle: The Entrez response handle being read, used to capture a
            raw-response snippet if it is still readable.
    """
    logger.error("Entrez read error (%s): %s", type(e).__name__, e)

    # Try to read raw response from handle if possible
    try:
        if hasattr(handle, "read"):
            raw_response = handle.read()
            if isinstance(raw_response, bytes):
                raw_response = raw_response.decode("utf-8", errors="ignore")
            logger.debug(
                "Raw response from handle (first 1000 chars): %s",
                raw_response[:1000],
            )
    except Exception:
        pass

    logger.debug("Full traceback:\n%s", traceback.format_exc())
