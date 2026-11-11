"""Schema behaviour: loading, dumping, errors, nesting and JSON handling."""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal as PyDecimal

import pytest

from projectx import (
    UUID,
    Date,
    Decimal,
    Dict,
    Int,
    List,
    Nested,
    Schema,
    Str,
    ValidationError,
    iter_errors,
)

APPLICATION_ID = "5f0a1a3c-1f7e-4b9a-9d5e-0e6f0a2b7c11"
BORROWER_ID = "c2b0f6c8-3a58-4a2e-8f24-5b1c9a0f7e21"


class Address(Schema):
    line1 = Str(min_length=1, max_length=120)
    city = Str(min_length=1, max_length=80)
    state = Str(pattern=r"^[A-Z]{2}$")
    postal_code = Str(pattern=r"^\d{5}(-\d{4})?$")


class Borrower(Schema):
    borrower_id = UUID(required=True)
    full_name = Str(min_length=1, max_length=200, required=True)
    date_of_birth = Date(required=True)
    annual_income = Decimal(ge=0, decimal_places=2, required=True)


class Application(Schema):
    application_id = UUID(required=True)
    principal = Decimal(gt=0, decimal_places=2, required=True)
    borrower = Nested(Borrower, required=True)
    properties = List(Nested(Address), min_items=1, required=True)
    notes = Str(max_length=500, allow_none=True)
    source = Str(max_length=64, load_only=True)
    total_exposure = Decimal(dump_only=True, default=PyDecimal("0.00"))


def payload(**overrides):
    data = {
        "application_id": APPLICATION_ID,
        "principal": "425000.00",
        "borrower": {
            "borrower_id": BORROWER_ID,
            "full_name": "Ada Lovelace",
            "date_of_birth": "1985-12-10",
            "annual_income": "182000.00",
        },
        "properties": [
            {
                "line1": "1 Analytical Way",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
            }
        ],
        "notes": None,
        "source": "partner-api",
    }
    data.update(overrides)
    return data


# -- happy path -----------------------------------------------------------


def test_load_returns_typed_values():
    result = Application().load(payload())
    assert result["application_id"] == uuid.UUID(APPLICATION_ID)
    assert result["principal"] == PyDecimal("425000.00")
    assert result["properties"][0]["city"] == "Austin"
    assert result["notes"] is None
    assert result["source"] == "partner-api"


def test_dump_produces_json_ready_values():
    schema = Application()
    loaded = schema.load(payload())
    dumped = schema.dump(loaded)
    assert dumped["application_id"] == APPLICATION_ID
    assert dumped["principal"] == "425000.00"
    assert dumped["borrower"]["date_of_birth"] == "1985-12-10"
    assert "source" not in dumped  # load_only
    assert "total_exposure" not in dumped  # dump_only, absent from input
    json.dumps(dumped)  # must not raise


def test_json_round_trip():
    schema = Application()
    text = schema.dumps(payload(), sort_keys=True)
    assert schema.loads(text)["principal"] == PyDecimal("425000.00")


# -- missing, null and unknown keys ---------------------------------------


def test_missing_required_fields_are_all_reported():
    with pytest.raises(ValidationError) as excinfo:
        Application().load({})
    assert excinfo.value.messages == {
        "application_id": ["missing required field"],
        "principal": ["missing required field"],
        "borrower": ["missing required field"],
        "properties": ["missing required field"],
    }


def test_null_is_only_allowed_when_declared():
    with pytest.raises(ValidationError) as excinfo:
        Application().load(payload(principal=None))
    assert excinfo.value.messages == {"principal": ["field may not be null"]}
    assert Application().load(payload(notes=None))["notes"] is None


def test_unknown_keys_are_ignored_by_default():
    assert "mystery" not in Application().load(payload(mystery=1))


def test_unknown_keys_can_be_rejected():
    with pytest.raises(ValidationError) as excinfo:
        Application(unknown="raise").load(payload(mystery=1))
    assert excinfo.value.messages == {"mystery": ["unknown field"]}


def test_invalid_unknown_option():
    with pytest.raises(ValueError):
        Application(unknown="explode")


# -- partial loading ------------------------------------------------------


def test_partial_true_skips_required_checks():
    result = Application(partial=True).load({"notes": "draft"})
    assert result == {"notes": "draft"}


def test_partial_by_field_name():
    schema = Application(partial=("borrower", "properties", "application_id", "principal"))
    assert schema.load({}) == {}
    with pytest.raises(ValidationError) as excinfo:
        schema.load({"borrower": {"borrower_id": BORROWER_ID}})
    assert excinfo.value.messages == {
        "borrower": {
            "full_name": ["missing required field"],
            "date_of_birth": ["missing required field"],
            "annual_income": ["missing required field"],
        }
    }


def test_partial_rejects_strings():
    with pytest.raises(TypeError):
        Application().load({}, partial="borrower")  # type: ignore[arg-type]


# -- many ----------------------------------------------------------------


def test_many_reports_errors_by_index():
    schema = Application(many=True)
    rows = [payload(), payload(principal="0.00"), payload(properties=[])]
    with pytest.raises(ValidationError) as excinfo:
        schema.load(rows)
    assert excinfo.value.messages == {
        1: {"principal": ["must be greater than 0"]},
        2: {"properties": ["length must be at least 1"]},
    }
    assert "[2].properties" in str(excinfo.value)


def test_many_requires_a_list():
    with pytest.raises(ValidationError) as excinfo:
        Application(many=True).load(payload())
    assert excinfo.value.messages == {"_schema": ["expected a list of objects, got dict"]}


def test_many_dump():
    schema = Application(many=True)
    rows = schema.load([payload(), payload()])
    assert [row["application_id"] for row in schema.dump(rows)] == [APPLICATION_ID] * 2


# -- nested error structure ----------------------------------------------


def test_nested_error_paths_are_flattened_in_messages():
    data = payload()
    data["borrower"]["date_of_birth"] = "10/12/1985"
    data["properties"][0]["postal_code"] = "7870"
    with pytest.raises(ValidationError) as excinfo:
        Application().load(data)
    messages = excinfo.value.messages
    assert messages["borrower"] == {
        "date_of_birth": ["expected an ISO-8601 date, got '10/12/1985'"]
    }
    assert set(messages["properties"][0]) == {"postal_code"}
    rendered = str(excinfo.value)
    assert "borrower.date_of_birth" in rendered
    assert "properties[0].postal_code" in rendered


def test_iter_errors_walks_the_tree():
    messages = {"a": ["bad"], "b": {"c": ["worse"]}, "d": {0: {"e": ["worst"]}}}
    assert dict(iter_errors(messages)) == {
        "a": "bad",
        "b.c": "worse",
        "d[0].e": "worst",
    }


class Node(Schema):
    """Self-referencing schema; ``Nested`` resolves the name lazily."""

    name = Str(required=True)
    children = List(Nested("Node"), default_factory=list)


def test_nested_many_and_forward_reference():
    tree = {"name": "root", "children": [{"name": "child"}]}
    loaded = Node().load(tree)
    assert loaded["children"][0]["name"] == "child"
    # defaults are applied on load, so the empty child list is part of the data
    assert Node().dump(loaded) == {
        "name": "root",
        "children": [{"name": "child", "children": []}],
    }


def test_nested_many_field():
    class Portfolio(Schema):
        properties = Nested(Address, many=True)

    data = {"properties": payload()["properties"]}
    assert Portfolio().load(data)["properties"][0]["state"] == "TX"


def test_unresolvable_forward_reference_is_reported():
    class Broken(Schema):
        child = Nested("DoesNotExist")

    with pytest.raises(TypeError):
        Broken().load({"child": {}})


# -- defaults -------------------------------------------------------------


def test_defaults_and_factories_are_independent_per_call():
    class Draft(Schema):
        status = Str(default="draft")
        tags = List(Str(), default_factory=list)
        history = List(Str(), default=[])

    schema = Draft()
    first = schema.load({})
    first["tags"].append("x")
    first["history"].append("y")
    second = schema.load({})
    assert second == {"status": "draft", "tags": [], "history": []}


# -- inheritance ----------------------------------------------------------


def test_inheritance_and_overrides():
    class Base(Schema):
        name = Str(required=True)
        score = Int(ge=0)

    class Extended(Base):
        score = Int(ge=0, le=100)
        segment = Str(default="retail")

    schema = Extended()
    assert schema.load({"name": "a", "score": 100}) == {
        "name": "a",
        "score": 100,
        "segment": "retail",
    }
    with pytest.raises(ValidationError) as excinfo:
        schema.load({"name": "a", "score": 101})
    assert excinfo.value.messages == {"score": ["must be less than or equal to 100"]}
    assert Base.field_names() == ("name", "score")


def test_field_names_may_not_start_with_underscore():
    with pytest.raises(TypeError):

        class Bad(Schema):
            _hidden = Str()

    with pytest.raises(TypeError):

        class AlsoBad(Schema):
            load = Str()


# -- dumping objects and bad input ---------------------------------------


def test_dump_reads_attributes_from_objects():
    @dataclasses.dataclass
    class LoanRecord:
        loan_id: str
        principal: PyDecimal
        state: str

    class Loan(Schema):
        loan_id = Str(required=True)
        principal = Decimal(required=True)
        state = Str(min_length=2, max_length=2)

    record = LoanRecord("LN-1", PyDecimal("10.50"), "TX")
    assert Loan().dump(record) == {
        "loan_id": "LN-1",
        "principal": "10.50",
        "state": "TX",
    }


def test_dump_rejects_scalars():
    with pytest.raises(ValidationError) as excinfo:
        Application().dump("not an object")
    assert excinfo.value.messages == {
        "_schema": ["cannot dump str: expected an object or a mapping"]
    }


def test_dump_reports_invalid_values():
    with pytest.raises(ValidationError) as excinfo:
        Application().dump({"principal": PyDecimal("1.00"), "application_id": "nope"})
    assert excinfo.value.messages == {"application_id": ["expected a UUID, got 'nope'"]}


def test_dump_of_missing_keys_is_partial():
    assert Application().dump({}) == {}


# -- introspection and validate ------------------------------------------


def test_validate_returns_messages():
    schema = Application()
    assert schema.validate(payload()) == {}
    messages = schema.validate({})
    assert list(messages) == ["application_id", "principal", "borrower", "properties"]


def test_repr_and_fields():
    schema = Application(many=True, partial=True, unknown="raise")
    assert "Application" in repr(schema)
    assert "many=True" in repr(schema)
    assert Application.field_names()[0] == "application_id"
    fields = Application().fields
    assert fields["principal"].__class__.__name__ == "Decimal"
    fields.clear()  # returned mapping is a copy
    assert "principal" in Application().fields


def test_data_model_must_be_a_mapping():
    with pytest.raises(ValidationError) as excinfo:
        Application().load(["not", "an", "object"])
    assert excinfo.value.messages == {"_schema": ["expected an object, got list"]}


def test_empty_schema():
    class Empty(Schema):
        pass

    assert Empty().load({}) == {}
    assert Empty().dump({}) == {}
    assert Empty().load({"extra": 1}) == {}


def test_dict_field_inside_schema():
    class Labels(Schema):
        values = Dict(keys=Str(min_length=1), values=Str())

    assert Labels().load({"values": {"kind": "bridge"}}) == {"values": {"kind": "bridge"}}
