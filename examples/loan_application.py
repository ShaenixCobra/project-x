"""End-to-end example: validate, serialize, and reject a loan application.

Run from the repository root::

    PYTHONPATH=src python examples/loan_application.py
"""

from __future__ import annotations

import json

from projectx import (
    UUID,
    Date,
    Decimal,
    Int,
    List,
    Nested,
    Schema,
    Str,
    ValidationError,
)


class Address(Schema):
    line1 = Str(min_length=1, max_length=120)
    city = Str(min_length=1, max_length=80)
    state = Str(pattern=r"^[A-Z]{2}$")
    postal_code = Str(pattern=r"^\d{5}(-\d{4})?$")


class LoanApplication(Schema):
    loan_id = UUID(required=True)
    principal = Decimal(gt=0, decimal_places=2, required=True)
    rate = Decimal(ge=0, le="0.25", decimal_places=6, required=True)
    term_months = Int(ge=12, le=600, required=True)
    originated_on = Date(required=True)
    property = Nested(Address, required=True)
    co_borrowers = List(Str(min_length=1), default_factory=list)


APPLICATION = {
    "loan_id": "5f0a1a3c-1f7e-4b9a-9d5e-0e6f0a2b7c11",
    "principal": "425000.00",
    "rate": "0.057500",
    "term_months": 360,
    "originated_on": "2026-03-01",
    "property": {
        "line1": "1 Analytical Way",
        "city": "Austin",
        "state": "TX",
        "postal_code": "78701",
    },
    "co_borrowers": ["Grace Hopper"],
}

BROKEN_APPLICATION = {
    "loan_id": "not-a-uuid",
    "principal": "0.00",
    "rate": 1.2,
    "term_months": "360",
    "originated_on": "03/01/2026",
    "property": {
        "line1": "",
        "city": "Austin",
        "state": "Texas",
        "postal_code": "7870",
    },
}


def main() -> None:
    schema = LoanApplication()

    loan = schema.load(APPLICATION)
    print("loaded principal:", repr(loan["principal"]))
    print("loaded property city:", loan["property"]["city"])
    print("serialized:")
    print(json.dumps(schema.dump(loan), indent=2))

    try:
        schema.load(BROKEN_APPLICATION)
    except ValidationError as exc:
        print("\nmessages:")
        print(json.dumps(exc.messages, indent=2))
        print("\nrendered:", exc)


if __name__ == "__main__":
    main()
