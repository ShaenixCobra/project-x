"""Field types for declaring schemas.

A field has two jobs:

``load(value)``
    Turn a raw value (usually something decoded from JSON) into a validated
    Python value, raising :class:`~projectx.errors.ValidationError` when the
    value is unusable.

``dump(value)``
    Turn a validated value back into JSON-compatible primitives.

Loading is strict on purpose. Numbers are never parsed out of strings, decimal
values are never built from binary floats, and ``bool`` is not accepted where an
integer is expected. Silent coercion is how money bugs get into production.
"""

from __future__ import annotations

import datetime as dt
import enum as _enum
import re
import sys
import uuid as _uuid
from decimal import Decimal as _Decimal
from decimal import InvalidOperation
from typing import Callable

from .errors import ValidationError

__all__ = [
    "MISSING",
    "Field",
    "Str",
    "Int",
    "Float",
    "Decimal",
    "Bool",
    "Date",
    "DateTime",
    "UUID",
    "Enum",
    "List",
    "Dict",
    "Nested",
    "Any",
]

MISSING = object()
"""Sentinel meaning "no default was given"."""


class _Invalid(TypeError):
    """Internal signal: wrong type, or the value cannot be converted."""


class _FieldError(Exception):
    """Internal container for one or more messages about a single field."""

    __slots__ = ("messages",)

    def __init__(self, messages: object) -> None:
        self.messages = messages
        super().__init__(messages)


def _typename(value: object) -> str:
    return type(value).__name__


def _as_checkers(validate: object) -> tuple[Callable[[object], object], ...]:
    if validate is None:
        return ()
    if callable(validate):
        return (validate,)
    checkers = tuple(validate)  # type: ignore[arg-type]
    for checker in checkers:
        if not callable(checker):
            raise TypeError("validate must be a callable or an iterable of callables")
    return checkers


def _range_messages(value: object, ge: object, le: object, gt: object, lt: object) -> list[str]:
    messages = []
    if ge is not None and not value >= ge:  # type: ignore[operator]
        messages.append(f"must be greater than or equal to {ge}")
    if le is not None and not value <= le:  # type: ignore[operator]
        messages.append(f"must be less than or equal to {le}")
    if gt is not None and not value > gt:  # type: ignore[operator]
        messages.append(f"must be greater than {gt}")
    if lt is not None and not value < lt:  # type: ignore[operator]
        messages.append(f"must be less than {lt}")
    return messages


def _places(number: _Decimal) -> int:
    """Number of decimal places in ``number`` (``Decimal("1.20")`` -> 2)."""
    exponent = number.as_tuple().exponent
    return -exponent if isinstance(exponent, int) else 0


def _to_decimal(value: object) -> _Decimal:
    if isinstance(value, _Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        return _Decimal(str(value))
    if isinstance(value, (int, str)):
        return _Decimal(value)
    raise TypeError(f"expected a decimal bound, got {_typename(value)}")


class Field:
    """Base class for all fields.

    Args:
        required: the key must be present and non-null when loading.
        default: value used when the key is absent. Implies ``required=False``.
        default_factory: callable returning the value used when the key is
            absent; use this for mutable defaults.
        allow_none: explicit ``null`` is accepted and kept as ``None``.
        load_only: never included in :meth:`projectx.Schema.dump` output
            (passwords, internal identifiers).
        dump_only: never read by :meth:`projectx.Schema.load` (computed fields).
        validate: callable or sequence of callables run on the loaded value.
            A checker signals failure by raising ``ValueError``, returning
            ``False``, or returning a message string.
        description: free-form documentation, also copied into ``__doc__`` of
            nothing but kept for schema introspection.
    """

    __slots__ = (
        "allow_none",
        "default",
        "default_factory",
        "description",
        "dump_only",
        "load_only",
        "name",
        "required",
        "validators",
    )

    def __init__(
        self,
        *,
        required: bool = False,
        default: object = MISSING,
        default_factory: Callable[[], object] | None = None,
        allow_none: bool = False,
        load_only: bool = False,
        dump_only: bool = False,
        validate: object = None,
        description: str | None = None,
    ) -> None:
        if required and (default is not MISSING or default_factory is not None):
            raise ValueError("a required field cannot also define a default")
        if default is not MISSING and default_factory is not None:
            raise ValueError("pass either default or default_factory, not both")
        if default_factory is not None and not callable(default_factory):
            raise TypeError("default_factory must be callable")
        if default is None and not allow_none:
            raise ValueError("default=None requires allow_none=True")
        if load_only and dump_only:
            raise ValueError("a field cannot be both load_only and dump_only")
        self.required = bool(required)
        self.default = default
        self.default_factory = default_factory
        self.allow_none = bool(allow_none)
        self.load_only = bool(load_only)
        self.dump_only = bool(dump_only)
        self.validators = _as_checkers(validate)
        self.description = description
        self.name: str | None = None

    # -- public API ----------------------------------------------------
    def load(self, value: object) -> object:
        """Validate and convert ``value``, or raise an internal field error."""
        try:
            converted = self._load(value)
        except _FieldError:
            raise
        except _Invalid as exc:
            raise _FieldError([str(exc)]) from None
        validators = self.validators
        if validators:
            messages = []
            for validator in validators:
                try:
                    outcome = validator(converted)
                except ValueError as exc:
                    messages.append(str(exc) or "invalid value")
                    continue
                if outcome is False:
                    messages.append("invalid value")
                elif isinstance(outcome, str):
                    messages.append(outcome)
            if messages:
                raise _FieldError(messages)
        return converted

    def dump(self, value: object) -> object:
        """Convert ``value`` to JSON-compatible primitives."""
        try:
            return self._dump(value)
        except _Invalid as exc:
            raise _FieldError([str(exc)]) from None

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    # -- subclass hooks -----------------------------------------------
    def _load(self, value: object) -> object:
        raise NotImplementedError

    def _dump(self, value: object) -> object:
        raise NotImplementedError

    def _bind(self, owner: type) -> None:
        """Internal: record the schema class that owns this field."""
        return None


class Any(Field):
    """Pass-through field: the value is neither checked nor converted."""

    __slots__ = ()

    def _load(self, value: object) -> object:
        return value

    def _dump(self, value: object) -> object:
        return value


class Str(Field):
    """A Unicode string."""

    __slots__ = ("max_length", "min_length", "pattern", "strip")

    def __init__(
        self,
        *,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | re.Pattern[str] | None = None,
        strip: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if min_length is not None and min_length < 0:
            raise ValueError("min_length must not be negative")
        if min_length is not None and max_length is not None and min_length > max_length:
            raise ValueError("min_length cannot exceed max_length")
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.strip = bool(strip)

    def _load(self, value: object) -> str:
        if not isinstance(value, str):
            raise _Invalid(f"expected a string, got {_typename(value)}")
        if self.strip:
            value = value.strip()
        min_length = self.min_length
        max_length = self.max_length
        pattern = self.pattern
        if (
            (min_length is not None and len(value) < min_length)
            or (max_length is not None and len(value) > max_length)
            or (pattern is not None and pattern.search(value) is None)
        ):
            raise _FieldError(self._violations(value))
        return value

    def _dump(self, value: object) -> str:
        if not isinstance(value, str):
            raise _Invalid(f"expected a string, got {_typename(value)}")
        return value

    def _violations(self, value: str) -> list[str]:
        messages = []
        if self.min_length is not None and len(value) < self.min_length:
            messages.append(f"length must be at least {self.min_length}")
        if self.max_length is not None and len(value) > self.max_length:
            messages.append(f"length must be at most {self.max_length}")
        if self.pattern is not None and self.pattern.search(value) is None:
            messages.append(f"must match pattern '{self.pattern.pattern}'")
        return messages


class Int(Field):
    """An integer. ``bool`` is rejected even though it subclasses ``int``."""

    __slots__ = ("ge", "gt", "le", "lt", "multiple_of")

    def __init__(
        self,
        *,
        ge: int | None = None,
        le: int | None = None,
        gt: int | None = None,
        lt: int | None = None,
        multiple_of: int | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if multiple_of is not None and multiple_of <= 0:
            raise ValueError("multiple_of must be positive")
        self.ge = ge
        self.le = le
        self.gt = gt
        self.lt = lt
        self.multiple_of = multiple_of

    def _load(self, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _Invalid(f"expected an integer, got {_typename(value)}")
        if (
            (self.ge is not None and value < self.ge)
            or (self.le is not None and value > self.le)
            or (self.gt is not None and value <= self.gt)
            or (self.lt is not None and value >= self.lt)
            or (self.multiple_of is not None and value % self.multiple_of)
        ):
            raise _FieldError(self._violations(value))
        return value

    def _dump(self, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _Invalid(f"expected an integer, got {_typename(value)}")
        return value

    def _violations(self, value: int) -> list[str]:
        messages = _range_messages(value, self.ge, self.le, self.gt, self.lt)
        if self.multiple_of is not None and value % self.multiple_of:
            messages.append(f"must be a multiple of {self.multiple_of}")
        return messages


class Float(Field):
    """A finite float.

    Non-finite values (``nan``, ``inf``) are rejected by default because they
    are not representable in JSON and poison downstream arithmetic.
    """

    __slots__ = ("allow_non_finite", "ge", "gt", "le", "lt")

    def __init__(
        self,
        *,
        ge: float | None = None,
        le: float | None = None,
        gt: float | None = None,
        lt: float | None = None,
        allow_non_finite: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.ge = ge
        self.le = le
        self.gt = gt
        self.lt = lt
        self.allow_non_finite = bool(allow_non_finite)

    def _load(self, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _Invalid(f"expected a number, got {_typename(value)}")
        number = float(value)
        if not self.allow_non_finite and number - number != 0.0:
            raise _Invalid(f"expected a finite number, got {number!r}")
        if (
            (self.ge is not None and number < self.ge)
            or (self.le is not None and number > self.le)
            or (self.gt is not None and number <= self.gt)
            or (self.lt is not None and number >= self.lt)
        ):
            raise _FieldError(self._violations(number))
        return number

    def _dump(self, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _Invalid(f"expected a number, got {_typename(value)}")
        number = float(value)
        if not self.allow_non_finite and number - number != 0.0:
            raise _Invalid(f"expected a finite number, got {number!r}")
        return number

    def _violations(self, value: float) -> list[str]:
        return _range_messages(value, self.ge, self.le, self.gt, self.lt)


class Decimal(Field):
    """An exact base-10 number, loaded from ``str``, ``int`` or ``Decimal``.

    Binary floats are rejected: ``0.1`` is not ``Decimal("0.1")`` and quietly
    pretending otherwise is unacceptable for balances, rates and payments.
    """

    __slots__ = ("decimal_places", "ge", "gt", "le", "lt", "max_digits")

    def __init__(
        self,
        *,
        ge: object = None,
        le: object = None,
        gt: object = None,
        lt: object = None,
        max_digits: int | None = None,
        decimal_places: int | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if max_digits is not None and max_digits <= 0:
            raise ValueError("max_digits must be positive")
        if decimal_places is not None and decimal_places < 0:
            raise ValueError("decimal_places must not be negative")
        self.ge = None if ge is None else _to_decimal(ge)
        self.le = None if le is None else _to_decimal(le)
        self.gt = None if gt is None else _to_decimal(gt)
        self.lt = None if lt is None else _to_decimal(lt)
        self.max_digits = max_digits
        self.decimal_places = decimal_places

    def _coerce(self, value: object) -> _Decimal:
        if isinstance(value, _Decimal):
            number = value
        elif isinstance(value, bool):
            raise _Invalid(f"expected a decimal, got {_typename(value)}")
        elif isinstance(value, int):
            number = _Decimal(value)
        elif isinstance(value, str):
            try:
                number = _Decimal(value)
            except InvalidOperation:
                raise _Invalid(f"expected a decimal, got {value!r}") from None
        else:
            raise _Invalid(f"expected a decimal string, integer or Decimal, got {_typename(value)}")
        if not number.is_finite():
            raise _Invalid(f"expected a finite decimal, got {number!r}")
        return number

    def _load(self, value: object) -> _Decimal:
        number = self._coerce(value)
        if self._violates(number):
            raise _FieldError(self._violations(number))
        return number

    def _dump(self, value: object) -> str:
        return format(self._coerce(value), "f")

    def _violates(self, value: _Decimal) -> bool:
        ge, le, gt, lt = self.ge, self.le, self.gt, self.lt
        if (
            (ge is not None and value < ge)
            or (le is not None and value > le)
            or (gt is not None and value <= gt)
            or (lt is not None and value >= lt)
        ):
            return True
        if self.max_digits is not None or self.decimal_places is not None:
            digits = value.as_tuple().digits
            if self.max_digits is not None and len(digits) > self.max_digits:
                return True
            if self.decimal_places is not None and _places(value) > self.decimal_places:
                return True
        return False

    def _violations(self, value: _Decimal) -> list[str]:
        messages = _range_messages(value, self.ge, self.le, self.gt, self.lt)
        if self.max_digits is not None or self.decimal_places is not None:
            if self.decimal_places is not None and _places(value) > self.decimal_places:
                messages.append(f"must have at most {self.decimal_places} decimal places")
            if self.max_digits is not None and len(value.as_tuple().digits) > self.max_digits:
                messages.append(f"must have at most {self.max_digits} digits")
        return messages


class Bool(Field):
    """A boolean."""

    __slots__ = ()

    def _load(self, value: object) -> bool:
        if not isinstance(value, bool):
            raise _Invalid(f"expected a boolean, got {_typename(value)}")
        return value

    _dump = _load


class Date(Field):
    """A calendar date. ISO-8601 strings are accepted on load."""

    __slots__ = ()

    def _load(self, value: object) -> dt.date:
        if isinstance(value, dt.datetime):
            raise _Invalid("expected a date, got datetime")
        if isinstance(value, dt.date):
            return value
        if isinstance(value, str):
            try:
                return dt.date.fromisoformat(value)
            except ValueError:
                raise _Invalid(f"expected an ISO-8601 date, got {value!r}") from None
        raise _Invalid(f"expected a date, got {_typename(value)}")

    def _dump(self, value: object) -> str:
        return self._load(value).isoformat()


class DateTime(Field):
    """A timestamp. ISO-8601 strings are accepted on load.

    With ``require_tz=True`` naive timestamps are rejected, which prevents the
    "midnight in which timezone?" class of settlement bugs.
    """

    __slots__ = ("require_tz",)

    def __init__(self, *, require_tz: bool = False, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.require_tz = bool(require_tz)

    def _load(self, value: object) -> dt.datetime:
        if isinstance(value, str):
            try:
                value = dt.datetime.fromisoformat(value)
            except ValueError:
                raise _Invalid(f"expected an ISO-8601 timestamp, got {value!r}") from None
        if not isinstance(value, dt.datetime):
            raise _Invalid(f"expected a timestamp, got {_typename(value)}")
        if self.require_tz and value.tzinfo is None:
            raise _Invalid("expected a timezone-aware timestamp")
        return value

    def _dump(self, value: object) -> str:
        return self._load(value).isoformat()


class UUID(Field):
    """A UUID. Canonical UUID strings are accepted on load."""

    __slots__ = ()

    def _load(self, value: object) -> _uuid.UUID:
        if isinstance(value, _uuid.UUID):
            return value
        if isinstance(value, str):
            try:
                return _uuid.UUID(value)
            except ValueError:
                raise _Invalid(f"expected a UUID, got {value!r}") from None
        raise _Invalid(f"expected a UUID, got {_typename(value)}")

    def _dump(self, value: object) -> str:
        return str(self._load(value))


class Enum(Field):
    """A member of ``enum``. Members and raw values are accepted on load.

    Args:
        enum: the ``enum.Enum`` subclass.
        by_name: accept/lookup members by name instead of by value.
    """

    __slots__ = ("by_name", "enum")

    def __init__(self, enum: type[_enum.Enum], *, by_name: bool = False, **kwargs: object) -> None:
        if not (isinstance(enum, type) and issubclass(enum, _enum.Enum)):
            raise TypeError("enum must be an enum.Enum subclass")
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.enum = enum
        self.by_name = bool(by_name)

    def _load(self, value: object) -> _enum.Enum:
        if isinstance(value, self.enum):
            return value
        try:
            if self.by_name:
                return self.enum[value]  # type: ignore[index]
            return self.enum(value)
        except (KeyError, ValueError, TypeError):
            allowed = [member.name for member in self.enum] if self.by_name else [
                member.value for member in self.enum
            ]
            raise _Invalid(f"expected one of {allowed!r}, got {value!r}") from None

    def _dump(self, value: object) -> object:
        return self._load(value).value


class List(Field):
    """A homogeneous list. ``inner`` defaults to :class:`Any`."""

    __slots__ = ("inner", "max_items", "min_items")

    def __init__(
        self,
        inner: Field | None = None,
        *,
        min_items: int | None = None,
        max_items: int | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if inner is not None and not isinstance(inner, Field):
            raise TypeError("inner must be a Field instance")
        if min_items is not None and max_items is not None and min_items > max_items:
            raise ValueError("min_items cannot exceed max_items")
        self.inner = inner if inner is not None else Any()
        self.min_items = min_items
        self.max_items = max_items

    def _load(self, value: object) -> list[object]:
        if not isinstance(value, (list, tuple)):
            raise _Invalid(f"expected a list, got {_typename(value)}")
        items = []
        errors: dict[int, object] = {}
        inner = self.inner
        inner_load = inner.load if inner.validators else inner._load
        for index, item in enumerate(value):
            try:
                items.append(inner_load(item))
            except _FieldError as exc:
                errors[index] = exc.messages
            except _Invalid as exc:
                errors[index] = [str(exc)]
        if errors:
            raise _FieldError(errors)
        if (self.min_items is not None and len(items) < self.min_items) or (
            self.max_items is not None and len(items) > self.max_items
        ):
            raise _FieldError(self._violations(len(items)))
        return items

    def _dump(self, value: object) -> list[object]:
        if not isinstance(value, (list, tuple)):
            raise _Invalid(f"expected a list, got {_typename(value)}")
        items = []
        errors: dict[int, object] = {}
        inner_dump = self.inner._dump
        for index, item in enumerate(value):
            try:
                items.append(inner_dump(item))
            except _FieldError as exc:
                errors[index] = exc.messages
            except _Invalid as exc:
                errors[index] = [str(exc)]
        if errors:
            raise _FieldError(errors)
        return items

    def _violations(self, length: int) -> list[str]:
        messages = []
        if self.min_items is not None and length < self.min_items:
            messages.append(f"length must be at least {self.min_items}")
        if self.max_items is not None and length > self.max_items:
            messages.append(f"length must be at most {self.max_items}")
        return messages

    def _bind(self, owner: type) -> None:
        self.inner._bind(owner)


class Dict(Field):
    """An object with optional key and value fields (both default to :class:`Any`)."""

    __slots__ = ("keys", "max_items", "min_items", "values")

    def __init__(
        self,
        keys: Field | None = None,
        values: Field | None = None,
        *,
        min_items: int | None = None,
        max_items: int | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        for label, field in (("keys", keys), ("values", values)):
            if field is not None and not isinstance(field, Field):
                raise TypeError(f"{label} must be a Field instance")
        self.keys = keys if keys is not None else Any()
        self.values = values if values is not None else Any()
        self.min_items = min_items
        self.max_items = max_items

    def _load(self, value: object) -> dict[object, object]:
        if not isinstance(value, dict):
            raise _Invalid(f"expected an object, got {_typename(value)}")
        result = {}
        errors: dict[object, object] = {}
        key_field = self.keys
        value_field = self.values
        key_load = key_field.load if key_field.validators else key_field._load
        value_load = value_field.load if value_field.validators else value_field._load
        for raw_key, raw_value in value.items():
            try:
                key = key_load(raw_key)
                result[key] = value_load(raw_value)
            except _FieldError as exc:
                errors[raw_key] = exc.messages
            except _Invalid as exc:
                errors[raw_key] = [str(exc)]
        if errors:
            raise _FieldError(errors)
        if (self.min_items is not None and len(result) < self.min_items) or (
            self.max_items is not None and len(result) > self.max_items
        ):
            raise _FieldError(self._violations(len(result)))
        return result

    def _dump(self, value: object) -> dict[object, object]:
        if not isinstance(value, dict):
            raise _Invalid(f"expected an object, got {_typename(value)}")
        result = {}
        errors: dict[object, object] = {}
        key_dump = self.keys._dump
        value_dump = self.values._dump
        for raw_key, raw_value in value.items():
            try:
                key = key_dump(raw_key)
                result[key] = value_dump(raw_value)
            except _FieldError as exc:
                errors[raw_key] = exc.messages
            except _Invalid as exc:
                errors[raw_key] = [str(exc)]
        if errors:
            raise _FieldError(errors)
        return result

    def _violations(self, length: int) -> list[str]:
        messages = []
        if self.min_items is not None and length < self.min_items:
            messages.append(f"must have at least {self.min_items} keys")
        if self.max_items is not None and length > self.max_items:
            messages.append(f"must have at most {self.max_items} keys")
        return messages

    def _bind(self, owner: type) -> None:
        self.keys._bind(owner)
        self.values._bind(owner)


class Nested(Field):
    """A nested :class:`~projectx.Schema`.

    ``schema`` may be a ``Schema`` subclass or the name of one defined later in
    the same module, which makes self-referencing structures possible.
    """

    __slots__ = ("_instance", "_owner", "many", "schema")

    def __init__(
        self,
        schema: type | str,
        *,
        many: bool = False,
        **kwargs: object,
    ) -> None:
        if not (isinstance(schema, str) or isinstance(schema, type)):
            raise TypeError("schema must be a Schema subclass or its class name")
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.schema = schema
        self.many = bool(many)
        self._owner: type | None = None
        self._instance: object | None = None

    def _bind(self, owner: type) -> None:
        self._owner = owner
        self._instance = None

    def _resolve_schema(self) -> type:
        schema = self.schema
        if isinstance(schema, str):
            from .schema import Schema

            owner = self._owner
            if owner is None:
                raise RuntimeError("Nested fields declared with a string need a Schema owner")
            resolved = getattr(sys.modules[owner.__module__], schema, None)
            if resolved is None:
                resolved = getattr(owner, schema, None)
            if not (isinstance(resolved, type) and issubclass(resolved, Schema)):
                raise TypeError(f"cannot resolve nested schema {schema!r} on {owner.__name__}")
            self.schema = resolved
            schema = resolved
        return schema  # type: ignore[return-value]

    def _get_instance(self) -> object:
        instance = self._instance
        if instance is None:
            instance = self._instance = self._resolve_schema()()
        return instance

    def _load(self, value: object) -> object:
        instance = self._get_instance()
        try:
            return instance.load(value, many=self.many)  # type: ignore[attr-defined]
        except ValidationError as exc:
            raise _FieldError(exc.messages) from None

    def _dump(self, value: object) -> object:
        instance = self._get_instance()
        try:
            return instance.dump(value, many=self.many)  # type: ignore[attr-defined]
        except ValidationError as exc:
            raise _FieldError(exc.messages) from None

    def __repr__(self) -> str:
        schema = self.schema
        label = schema if isinstance(schema, str) else schema.__name__
        return f"Nested({label}{', many=True' if self.many else ''})"

