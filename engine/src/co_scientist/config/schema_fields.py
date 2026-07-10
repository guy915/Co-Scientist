"""Shared dataclass-field helper for config schema parsing.

Every schema dataclass's ``from_dict()`` builds its constructor kwargs
through ``_declared_field_kwargs`` so YAML keys that don't map to a
declared field (typos, deprecated keys) are silently dropped instead of
raising, and fields the caller fills in specially are not double-set.
"""

from dataclasses import fields
from typing import Any


def _declared_field_kwargs(
    cls: type[Any],
    data: dict[str, Any],
    *,
    exclude: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build constructor kwargs from keys in data that are declared fields.

    Keys absent from ``data`` are omitted so the dataclass declaration
    remains the single source of truth for defaults. Keys not matching a
    declared field are ignored (unknown YAML keys are tolerated). A key
    present with an explicit ``null`` value is forwarded as ``None``,
    matching the legacy ``data.get(key, default)`` semantics where presence
    wins over the default.

    Args:
        cls: Dataclass whose declared fields define the accepted keys.
        data: Raw configuration dictionary (typically parsed YAML).
        exclude: Field names the caller handles explicitly (nested
            parsing, renamed keys, or defaults that differ from the
            dataclass declaration).

    Returns:
        Mapping of field name to raw value, suitable for ``cls(**kwargs)``.
    """
    # Field names declared on the dataclass, minus the ones the caller
    # handles itself; only keys matching this set are forwarded.
    names = {f.name for f in fields(cls)} - set(exclude)
    return {key: value for key, value in data.items() if key in names}
