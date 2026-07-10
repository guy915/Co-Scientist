"""Value transforms for the response-parser expression language.

Implements the pipe-transform vocabulary (``split``, ``index``, ``int``,
``float``, ``default``, ``wrap_list``) applied to field values by
``ResponseParser`` when evaluating YAML field-mapping expressions such as
``date_revised|split:/|index:0|int``.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_transform(transform: str, value: Any) -> Any:
    """Apply a transform to a value.

    Args:
        transform: Transform specification
            (e.g., "split:/", "index:0", "int")
        value: Value to transform

    Returns:
        Transformed value
    """
    # Default transform - applies only when value is None; non-None
    # values pass through unchanged. Checked before the None guard
    # below since it is the one transform meant to handle None input.
    if transform.startswith("default:"):
        return _transform_default(transform, value)

    if value is None:
        return None

    return _apply_value_transform(transform, value)


def _apply_value_transform(transform: str, value: Any) -> Any:
    """Dispatch a non-default transform against a non-None value.

    Args:
        transform: Transform specification (e.g., "split:/", "int").
        value: Non-None value to transform.

    Returns:
        Transformed value, or the original value if the transform is
        unknown.
    """
    if transform.startswith("split:"):
        return _transform_split(transform, value)
    if transform.startswith("index:"):
        return _transform_index(transform, value)

    handlers = {
        "int": _transform_int,
        "float": _transform_float,
        "wrap_list": _transform_wrap_list,
    }
    handler = handlers.get(transform)
    if handler:
        return handler(value)

    logger.warning("unknown transform: %s", transform)
    return value


def _transform_default(transform: str, value: Any) -> Any:
    """Apply the "default:VALUE" transform.

    Args:
        transform: Transform specification, e.g. "default:0".
        value: Value to transform.

    Returns:
        value unchanged if not None; otherwise VALUE, parsed as an int
        when possible and left as a string otherwise.
    """
    if value is not None:
        return value
    default_value = transform[8:]
    try:
        return int(default_value)
    except ValueError:
        return default_value


def _transform_split(transform: str, value: Any) -> Any:
    """Apply the "split:DELIM" transform."""
    delimiter = transform[6:]
    if isinstance(value, str):
        return value.split(delimiter)
    return value


def _transform_index(transform: str, value: Any) -> Any:
    """Apply the "index:N" transform."""
    index = int(transform[6:])
    if isinstance(value, (list, tuple)) and len(value) > index:
        return value[index]
    return None


def _transform_int(value: Any) -> Any:
    """Apply the "int" transform."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _transform_float(value: Any) -> Any:
    """Apply the "float" transform."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _transform_wrap_list(value: Any) -> Any:
    """Apply the "wrap_list" transform - wrap a single value in a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
