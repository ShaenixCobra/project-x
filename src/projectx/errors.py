"""Exceptions raised by :mod:`projectx`.

Error messages are collected into a nested mapping that mirrors the shape of
the input, which lets callers hand the whole structure back to an API client::

    {"principal": ["must be greater than 0"],
     "borrower": {"date_of_birth": ["expected a date, got str"]},
     "properties": {0: {"postal_code": ["must match pattern ..."]}}}
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ["ProjectXError", "ValidationError", "iter_errors"]


class ProjectXError(Exception):
    """Base class for every exception raised by projectx."""


def _join(prefix: str, key: object) -> str:
    if isinstance(key, int):
        return f"{prefix}[{key}]"
    return f"{prefix}.{key}" if prefix else str(key)


def iter_errors(messages: Mapping[Any, Any], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(path, message)`` pairs from a nested error mapping.

    ``path`` uses dotted notation for object keys and brackets for list
    indexes, so ``{"borrower": {"name": [...]}}`` becomes ``borrower.name``.
    """
    for key, value in messages.items():
        path = _join(prefix, key)
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, Mapping):
            yield from iter_errors(value, path)
        else:
            for message in value:
                yield path, message


class ValidationError(ProjectXError):
    """Raised when data does not satisfy a schema.

    Attributes:
        messages: nested mapping of error messages, keyed like the input.
        value: the offending input, when available.
    """

    def __init__(self, messages: Mapping[Any, Any], *, value: object = None) -> None:
        self.messages = messages
        self.value = value
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [f"{path}: {message}" for path, message in iter_errors(self.messages)]
        return "; ".join(parts) if parts else "invalid data"

    def __str__(self) -> str:
        return self._render()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.messages!r})"

    def to_dict(self) -> Mapping[Any, Any]:
        """Return the nested messages, ready to be serialized as JSON."""
        return self.messages
