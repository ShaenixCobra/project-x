"""Field-level validation and serialization semantics."""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal as PyDecimal

import pytest

from projectx import (
    UUID,
    Any,
    Bool,
    Date,
    DateTime,
    Decimal,
    Dict,
    Enum,
    Float,
    Int,
    List,
    Str,
    ValidationError,
)


class Status(enum.Enum):
    ACTIVE = "active"
    PAID_OFF = "paid_off"


def failure(schema, value):
    with pytest.raises(ValidationError) as excinfo:
        schema.load({"value": value})
    return excinfo.value.messages["value"]


# -- Str ------------------------------------------------------------------


def test_str_accepts_only_strings(single):
    assert single(Str()).load({"value": "ok"}) == {"value": "ok"}
    assert failure(single(Str()), 42) == ["expected a string, got int"]


def test_str_strip_and_length_and_pattern(single):
    assert single(Str(strip=True)).load({"value": "  hi  "}) == {"value": "hi"}
    assert failure(single(Str(min_length=3)), "ab") == ["length must be at least 3"]
    assert failure(single(Str(max_length=2)), "abc") == ["length must be at most 2"]
    messages = failure(single(Str(pattern=r"^\d{5}$")), "abc")
    assert messages == ["must match pattern '^\\d{5}$'"]


def test_str_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        Str(min_length=5, max_length=2)
    with pytest.raises(ValueError):
        Str(min_length=-1)


# -- Int ------------------------------------------------------------------


def test_int_rejects_bool_and_strings(single):
    schema = single(Int())
    assert schema.load({"value": 7}) == {"value": 7}
    assert failure(schema, True) == ["expected an integer, got bool"]
    assert failure(schema, "7") == ["expected an integer, got str"]


def test_int_bounds_are_all_reported(single):
    schema = single(Int(ge=10, multiple_of=5))
    assert failure(schema, 3) == [
        "must be greater than or equal to 10",
        "must be a multiple of 5",
    ]
    assert failure(single(Int(le=1)), 2) == ["must be less than or equal to 1"]
    assert failure(single(Int(gt=1)), 1) == ["must be greater than 1"]
    assert failure(single(Int(lt=1)), 1) == ["must be less than 1"]


def test_int_rejects_bad_multiple_of():
    with pytest.raises(ValueError):
        Int(multiple_of=0)


# -- Float ----------------------------------------------------------------


def test_float_accepts_numbers(single):
    assert single(Float()).load({"value": 3}) == {"value": 3.0}
    assert single(Float()).load({"value": 2.5}) == {"value": 2.5}


def test_float_rejects_bool_string_and_non_finite(single):
    schema = single(Float())
    assert failure(schema, True) == ["expected a number, got bool"]
    assert failure(schema, "2.5") == ["expected a number, got str"]
    assert failure(schema, float("nan")) == ["expected a finite number, got nan"]
    assert failure(schema, float("inf")) == ["expected a finite number, got inf"]


def test_float_can_opt_into_non_finite(single):
    value = single(Float(allow_non_finite=True)).load({"value": float("inf")})["value"]
    assert value == float("inf")


# -- Decimal --------------------------------------------------------------


def test_decimal_accepts_exact_inputs_only(single):
    schema = single(Decimal())
    assert schema.load({"value": "1.20"}) == {"value": PyDecimal("1.20")}
    assert schema.load({"value": 3}) == {"value": PyDecimal(3)}
    assert schema.load({"value": PyDecimal("2.50")}) == {"value": PyDecimal("2.50")}


def test_decimal_rejects_binary_floats(single):
    messages = failure(single(Decimal()), 1.1)
    assert messages == ["expected a decimal string, integer or Decimal, got float"]


def test_decimal_rejects_garbage_and_non_finite(single):
    schema = single(Decimal())
    assert failure(schema, "abc") == ["expected a decimal, got 'abc'"]
    assert failure(schema, "NaN") == ["expected a finite decimal, got Decimal('NaN')"]
    assert failure(schema, True) == ["expected a decimal, got bool"]


def test_decimal_dump_preserves_scale(single):
    schema = single(Decimal())
    loaded = schema.load({"value": "1.20"})["value"]
    assert schema.dump({"value": loaded}) == {"value": "1.20"}
    assert schema.dump({"value": PyDecimal("1E+3")}) == {"value": "1000"}


def test_decimal_precision_checks(single):
    assert failure(single(Decimal(decimal_places=2)), "1.234") == [
        "must have at most 2 decimal places"
    ]
    assert failure(single(Decimal(max_digits=3)), "1234") == ["must have at most 3 digits"]
    assert single(Decimal(decimal_places=2)).load({"value": "1.23"}) == {
        "value": PyDecimal("1.23")
    }


def test_decimal_bounds_from_strings(single):
    schema = single(Decimal(gt="0", le="10000000.00"))
    assert failure(schema, "0") == ["must be greater than 0"]
    assert failure(schema, "10000000.01") == ["must be less than or equal to 10000000.00"]


# -- Bool, Date, DateTime, UUID -------------------------------------------


def test_bool_is_strict(single):
    assert single(Bool()).load({"value": False}) == {"value": False}
    assert failure(single(Bool()), 1) == ["expected a boolean, got int"]


def test_date_parses_iso_strings_and_rejects_datetimes(single):
    schema = single(Date())
    assert schema.load({"value": "2026-03-01"}) == {"value": dt.date(2026, 3, 1)}
    assert failure(schema, dt.datetime(2026, 3, 1, 9, 30)) == ["expected a date, got datetime"]
    assert failure(schema, "03/01/2026") == ["expected an ISO-8601 date, got '03/01/2026'"]
    assert schema.dump({"value": dt.date(2026, 3, 1)}) == {"value": "2026-03-01"}


def test_datetime_timezone_handling(single):
    aware = single(DateTime(require_tz=True))
    assert aware.load({"value": "2026-03-01T09:30:00+00:00"}) == {
        "value": dt.datetime(2026, 3, 1, 9, 30, tzinfo=dt.timezone.utc)
    }
    assert failure(aware, "2026-03-01T09:30:00") == ["expected a timezone-aware timestamp"]
    assert single(DateTime()).load({"value": "2026-03-01T09:30:00"}) == {
        "value": dt.datetime(2026, 3, 1, 9, 30)
    }
    assert failure(aware, "yesterday") == ["expected an ISO-8601 timestamp, got 'yesterday'"]


def test_uuid_round_trip(single):
    schema = single(UUID())
    raw = "5f0a1a3c-1f7e-4b9a-9d5e-0e6f0a2b7c11"
    loaded = schema.load({"value": raw})["value"]
    assert loaded == uuid.UUID(raw)
    assert schema.dump({"value": loaded}) == {"value": raw}
    assert failure(schema, "nope") == ["expected a UUID, got 'nope'"]


# -- Enum -----------------------------------------------------------------


def test_enum_by_value_and_name(single):
    by_value = single(Enum(Status))
    assert by_value.load({"value": "active"}) == {"value": Status.ACTIVE}
    assert by_value.dump({"value": Status.PAID_OFF}) == {"value": "paid_off"}
    assert failure(by_value, "ACTIVE") == ["expected one of ['active', 'paid_off'], got 'ACTIVE'"]

    by_name = single(Enum(Status, by_name=True))
    assert by_name.load({"value": "ACTIVE"}) == {"value": Status.ACTIVE}


def test_enum_requires_an_enum_class():
    with pytest.raises(TypeError):
        Enum(str)  # type: ignore[arg-type]


# -- List / Dict / Any ----------------------------------------------------


def test_list_validates_items_and_reports_indexes(single):
    schema = single(List(Str(min_length=1)))
    assert schema.load({"value": ["a", "b"]}) == {"value": ["a", "b"]}
    with pytest.raises(ValidationError) as excinfo:
        schema.load({"value": ["a", 2]})
    assert excinfo.value.messages == {"value": {1: ["expected a string, got int"]}}


def test_list_item_count_and_type(single):
    assert failure(single(List(Str(), min_items=2)), ["a"]) == ["length must be at least 2"]
    assert failure(single(List(Str(), max_items=1)), ["a", "b"]) == ["length must be at most 1"]
    assert failure(single(List(Str())), "nope") == ["expected a list, got str"]


def test_dict_validates_keys_and_values(single):
    schema = single(Dict(keys=Str(), values=Int()))
    assert schema.load({"value": {"a": 1}}) == {"value": {"a": 1}}
    with pytest.raises(ValidationError) as excinfo:
        schema.load({"value": {"a": "b"}})
    assert excinfo.value.messages == {"value": {"a": ["expected an integer, got str"]}}


def test_any_is_passthrough(single):
    payload = {"anything": [1, 2, 3]}
    assert single(Any()).load({"value": payload}) == {"value": payload}
    assert single(Any()).dump({"value": payload}) == {"value": payload}


# -- custom validators ----------------------------------------------------


def test_custom_validators_aggregate(single):
    def even(value):
        return True if value % 2 == 0 else "must be even"

    def positive(value):
        if value <= 0:
            raise ValueError("must be positive")

    schema = single(Int(validate=[even, positive]))
    assert failure(schema, -3) == ["must be even", "must be positive"]
    assert schema.load({"value": 4}) == {"value": 4}


def test_custom_validator_returning_false(single):
    schema = single(Str(validate=lambda value: value.startswith("LN-")))
    assert failure(schema, "AB-1") == ["invalid value"]


def test_validate_rejects_non_callables():
    with pytest.raises(TypeError):
        Int(validate=[1])  # type: ignore[list-item]


# -- field configuration --------------------------------------------------


def test_field_configuration_guards():
    with pytest.raises(ValueError):
        Str(required=True, default="x")
    with pytest.raises(ValueError):
        Str(default=None)
    with pytest.raises(ValueError):
        Str(load_only=True, dump_only=True)
    with pytest.raises(ValueError):
        Str(default="x", default_factory=lambda: "y")
    with pytest.raises(TypeError):
        Str(default_factory="not callable")  # type: ignore[arg-type]
