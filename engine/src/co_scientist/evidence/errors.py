"""Describe transport failures without hiding their underlying cause."""


def describe_exception(exc: BaseException) -> str:
    """Describe an exception by type and message for diagnostic logging.

    Unwraps ``ExceptionGroup`` (raised by the anyio task groups inside the MCP
    transport) down to its first leaf so the root cause - e.g. a connection
    error versus a validation error - is visible instead of the opaque group
    wrapper.

    Args:
        exc: The caught exception.

    Returns:
        A "TypeName: message" string describing the underlying cause.
    """
    current: BaseException = exc
    # ExceptionGroup (Python 3.11+) exposes an ``exceptions`` tuple; descend to
    # the first leaf so the real cause surfaces instead of the group wrapper.
    while getattr(current, "exceptions", None):
        current = current.exceptions[0]  # type: ignore[attr-defined]
    message = str(current).strip()
    return (
        f"{type(current).__name__}: {message}"
        if message
        else type(current).__name__
    )
