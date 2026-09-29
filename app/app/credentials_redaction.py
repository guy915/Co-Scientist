"""Log redaction for bring-your-own-key credentials.

Split from ``app.credentials`` to keep that module under the line
ceiling. The filter reads the credential scoped to the current context
(``credentials.current_byok``) and scrubs its exact key from a record.
"""

from __future__ import annotations

import logging

from app.credentials import current_byok, redact_byok_text


def _redact_log_details(record: logging.LogRecord) -> None:
    """Redact formatted traceback and stack text on a log record."""
    if record.exc_info:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    for field in ("exc_text", "stack_info"):
        value = getattr(record, field)
        if value:
            setattr(record, field, redact_byok_text(value))


class ByokRedactionFilter(logging.Filter):
    """Scrubs a scoped BYOK key out of any record that carries it.

    Defense in depth: no code path logs the key deliberately, but a
    provider error message could embed it, and records from libraries
    are not ours to control. Attached to both the stdout handler and the
    persistent capture pipeline (see ``logging_setup``); when no
    credential is scoped the filter is a cheap no-op.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the scoped key from the record, keeping the record."""
        if current_byok() is None:
            return True
        try:
            message = record.getMessage()
            redacted = redact_byok_text(message)
            if redacted != message:
                record.msg = redacted
                record.args = None
            _redact_log_details(record)
        except Exception:
            # Redaction must never break logging itself.
            return True
        return True
