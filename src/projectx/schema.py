"""Declarative schemas.

A schema is a class whose attributes are :class:`~projectx.fields.Field`
instances::

    class Property(Schema):
        address = Str(min_length=1, max_length=200)
        city = Str(min_length=1)
        state = Str(pattern=r"^[A-Z]{2}$")
        postal_code = Str(pattern=r"^\\d{5}(-\\d{4})?$")

Instances are stateless apart from their options, so ``Property()`` can be
created anywhere, shared between threads, and reused for every request. Field
plans are compiled once per schema class, not once per call.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Mapping
from typing import Any

from .errors import ValidationError
from .fields import MISSING, Field, _FieldError, _Invalid, _typename

__all__ = ["Schema"]

_UNKNOWN_OPTIONS = frozenset({"ignore", "raise"})

#: Names a field may not take: they would shadow schema options or methods.
_RESERVED_FIELD_NAMES = frozenset({"many", "partial", "unknown", "fields"})


def _default_factory(field: Field) -> Any:
    """Return a zero-argument callable producing the default, or ``None``."""
    factory = field.default_factory
    if factory is not None:
        return factory
    default = field.default
    if default is MISSING:
        return None
    if isinstance(default, (list, dict, set)):
        return lambda: copy.deepcopy(default)
    return lambda: default


def _partial_options(partial: object) -> tuple[bool, frozenset[str]]:
    """Normalize ``partial`` into ``(skip_all_required, explicitly_skipped)``."""
    if partial is True:
        return True, frozenset()
    if partial is False or partial is None:
        return False, frozenset()
    if isinstance(partial, str):
        raise TypeError("partial must be a bool or a collection of field names")
    return False, frozenset(partial)  # type: ignore[arg-type]


class Schema:
    """Base class for declarative schemas.

    Args:
        many: treat input/output as a list of objects instead of one object.
        partial: skip required-field checks — ``True`` for all fields, or a
            collection of field names (useful for PATCH endpoints).
        unknown: what to do with keys that are not fields; ``"ignore"``
            (default) drops them, ``"raise"`` reports them as errors.
    """

    _fields: dict[str, Field] = {}
    _load_plan: tuple[tuple[str, Any, bool, Any, bool], ...] = ()
    _dump_plan: tuple[tuple[str, Any, bool], ...] = ()
    _field_names: frozenset[str] = frozenset()
    _compiled: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        fields: dict[str, Field] = {}
        for base in reversed(cls.__mro__):
            for name, value in vars(base).items():
                if isinstance(value, Field):
                    fields[name] = value
        for name, field in fields.items():
            if name.startswith("_"):
                raise TypeError(f"{cls.__name__}: field names may not start with an underscore")
            if name in _RESERVED_FIELD_NAMES or hasattr(Schema, name):
                raise TypeError(f"{cls.__name__}: {name!r} is reserved by Schema")
            field.name = name
            field._bind(cls)
        cls._fields = fields
        cls._load_plan = ()
        cls._dump_plan = ()
        cls._field_names = frozenset(fields)
        cls._compiled = False

    def __init__(
        self,
        *,
        many: bool = False,
        partial: bool | Any = False,
        unknown: str = "ignore",
    ) -> None:
        if unknown not in _UNKNOWN_OPTIONS:
            raise ValueError(f"unknown must be one of {sorted(_UNKNOWN_OPTIONS)}")
        self.many = bool(many)
        self.partial = partial
        self.unknown = unknown
        type(self)._compile()

    # -- compilation ---------------------------------------------------
    @classmethod
    def _compile(cls) -> None:
        if cls.__dict__.get("_compiled", False):
            return
        load_plan = []
        dump_plan = []
        for name, field in cls._fields.items():
            if not field.dump_only:
                # Skip the public wrapper when there are no custom validators:
                # it only exists to convert internal errors into message lists.
                loader = field.load if field.validators else field._load
                load_plan.append(
                    (name, loader, field.required, _default_factory(field), field.allow_none)
                )
            if not field.load_only:
                dump_plan.append((name, field._dump, field.allow_none))
        cls._load_plan = tuple(load_plan)
        cls._dump_plan = tuple(dump_plan)
        cls._field_names = frozenset(cls._fields)
        cls._compiled = True

    # -- introspection -------------------------------------------------
    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        """Return the field names in declaration order."""
        return tuple(cls._fields)

    @property
    def fields(self) -> dict[str, Field]:
        """A copy of the ``{name: field}`` mapping."""
        return dict(type(self)._fields)

    def __repr__(self) -> str:
        options = []
        if self.many:
            options.append("many=True")
        if self.partial:
            options.append(f"partial={self.partial!r}")
        if self.unknown != "ignore":
            options.append(f"unknown={self.unknown!r}")
        suffix = f"({', '.join(options)})" if options else "()"
        return f"<{type(self).__name__}{suffix} fields={list(self._fields)}>"

    # -- loading -------------------------------------------------------
    def load(
        self,
        data: object,
        *,
        many: bool | None = None,
        partial: bool | Any = None,
        unknown: str | None = None,
    ) -> Any:
        """Validate ``data`` and return plain Python values.

        Raises:
            ValidationError: with a nested mapping of every problem found, so a
                single call reports as many issues as possible instead of just
                the first one.
        """
        many = self.many if many is None else many
        partial = self.partial if partial is None else partial
        unknown = self.unknown if unknown is None else unknown
        skip_all, skipped = _partial_options(partial)
        if many:
            if not isinstance(data, (list, tuple)):
                raise ValidationError(
                    {"_schema": [f"expected a list of objects, got {_typename(data)}"]}, value=data
                )
            results = []
            errors: dict[object, object] = {}
            for index, item in enumerate(data):
                try:
                    results.append(self._load_one(item, skip_all, skipped, unknown))
                except ValidationError as exc:
                    errors[index] = exc.messages
            if errors:
                raise ValidationError(errors, value=data)
            return results
        return self._load_one(data, skip_all, skipped, unknown)

    def _load_one(
        self, data: object, skip_all: bool, skipped: frozenset[str], unknown: str
    ) -> dict[str, object]:
        cls = type(self)
        if not isinstance(data, Mapping):
            raise ValidationError(
                {"_schema": [f"expected an object, got {_typename(data)}"]}, value=data
            )
        plan = cls._load_plan
        errors: dict[object, object] = {}
        output: dict[str, object] = {}
        for name, load, required, default_factory, allow_none in plan:
            try:
                raw = data[name]
            except KeyError:
                if default_factory is not None:
                    output[name] = default_factory()
                elif required and not (skip_all or name in skipped):
                    errors[name] = ["missing required field"]
                continue
            if raw is None:
                if allow_none:
                    output[name] = None
                else:
                    errors[name] = ["field may not be null"]
                continue
            try:
                output[name] = load(raw)
            except _FieldError as exc:
                errors[name] = exc.messages
            except _Invalid as exc:
                errors[name] = [str(exc)]
        if unknown == "raise":
            known = cls._field_names
            for key in data:
                if key not in known:
                    errors.setdefault(key, []).append("unknown field")  # type: ignore[union-attr]
        if errors:
            raise ValidationError(errors, value=data)
        return output

    # -- dumping -------------------------------------------------------
    def dump(self, data: object, *, many: bool | None = None) -> Any:
        """Serialize ``data`` (a mapping or an object with attributes) to JSON-ready values."""
        many = self.many if many is None else many
        if many:
            if isinstance(data, (str, bytes, bytearray, Mapping)):
                raise ValidationError(
                    {"_schema": [f"expected a list of objects, got {_typename(data)}"]}
                )
            results = []
            errors: dict[object, object] = {}
            for index, item in enumerate(data):  # type: ignore[union-attr]
                try:
                    results.append(self._dump_one(item))
                except ValidationError as exc:
                    errors[index] = exc.messages
            if errors:
                raise ValidationError(errors)
            return results
        return self._dump_one(data)

    def _dump_one(self, data: object) -> dict[str, object]:
        cls = type(self)
        plan = cls._dump_plan
        errors: dict[object, object] = {}
        output: dict[str, object] = {}
        if isinstance(data, Mapping):
            for name, dump, allow_none in plan:
                try:
                    value = data[name]
                except KeyError:
                    continue
                if value is None:
                    if allow_none:
                        output[name] = None
                    else:
                        errors[name] = ["field may not be null"]
                    continue
                try:
                    output[name] = dump(value)
                except _FieldError as exc:
                    errors[name] = exc.messages
                except _Invalid as exc:
                    errors[name] = [str(exc)]
        elif isinstance(
            data, (str, bytes, bytearray, list, tuple, set, frozenset, int, float, bool)
        ):
            raise ValidationError(
                {"_schema": [f"cannot dump {_typename(data)}: expected an object or a mapping"]}
            )
        else:
            for name, dump, allow_none in plan:
                value = getattr(data, name, MISSING)
                if value is MISSING:
                    continue
                if value is None:
                    if allow_none:
                        output[name] = None
                    else:
                        errors[name] = ["field may not be null"]
                    continue
                try:
                    output[name] = dump(value)
                except _FieldError as exc:
                    errors[name] = exc.messages
                except _Invalid as exc:
                    errors[name] = [str(exc)]
        if errors:
            raise ValidationError(errors, value=data)
        return output

    # -- convenience ---------------------------------------------------
    def loads(
        self,
        payload: str | bytes | bytearray,
        *,
        many: bool | None = None,
        partial: bool | Any = None,
        unknown: str | None = None,
    ) -> Any:
        """Parse a JSON document and validate it."""
        return self.load(json.loads(payload), many=many, partial=partial, unknown=unknown)

    def dumps(self, data: object, *, many: bool | None = None, **kwargs: Any) -> str:
        """Serialize ``data`` to a JSON string."""
        return json.dumps(self.dump(data, many=many), **kwargs)

    def validate(
        self,
        data: object,
        *,
        many: bool | None = None,
        partial: bool | Any = None,
        unknown: str | None = None,
    ) -> dict[object, object]:
        """Return the error mapping for ``data``, or ``{}`` when it is valid."""
        try:
            self.load(data, many=many, partial=partial, unknown=unknown)
        except ValidationError as exc:
            return dict(exc.messages)
        return {}

    def iter_fields(self) -> Iterator[tuple[str, Field]]:
        """Iterate over ``(name, field)`` pairs."""
        return iter(type(self)._fields.items())
