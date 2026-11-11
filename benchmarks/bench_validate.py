#!/usr/bin/env python3
"""Benchmark projectx against an equivalent hand-written validator.

Both implementations perform the same checks on the same payload; the
hand-written one accumulates no error messages and raises ``ValueError`` on the
first problem, so it is the faster, less useful baseline.

Usage::

    python benchmarks/bench_validate.py [iterations]
"""

from __future__ import annotations

import datetime as dt
import enum
import sys
import timeit
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import projectx as px  # noqa: E402


class LoanType(enum.Enum):
    PURCHASE = "purchase"
    REFINANCE = "refinance"
    HELOC = "heloc"


class AddressSchema(px.Schema):
    line1 = px.Str(min_length=1, max_length=120)
    city = px.Str(min_length=1, max_length=80)
    state = px.Str(pattern=r"^[A-Z]{2}$")
    postal_code = px.Str(pattern=r"^\d{5}(-\d{4})?$")


class ApplicationSchema(px.Schema):
    application_id = px.UUID(required=True)
    loan_type = px.Enum(LoanType, required=True)
    principal = px.Decimal(gt=0, decimal_places=2, required=True)
    rate = px.Decimal(ge=0, le="0.25", decimal_places=6, required=True)
    term_months = px.Int(ge=12, le=600, required=True)
    credit_score = px.Int(ge=300, le=850, required=True)
    ltv = px.Float(ge=0, le=100, required=True)
    property = px.Nested(AddressSchema, required=True)
    co_borrowers = px.List(px.Str(min_length=1), default_factory=list)


PAYLOAD = {
    "application_id": "5f0a1a3c-1f7e-4b9a-9d5e-0e6f0a2b7c11",
    "loan_type": "purchase",
    "principal": "425000.00",
    "rate": "0.057500",
    "term_months": 360,
    "credit_score": 781,
    "ltv": 80.0,
    "property": {
        "line1": "1 Analytical Way",
        "city": "Austin",
        "state": "TX",
        "postal_code": "78701",
    },
    "co_borrowers": ["Grace Hopper", "Alan Turing"],
}


def baseline_load(data):
    """Equivalent validation, written by hand, raising on the first error."""
    out = {}
    raw = data.get("application_id")
    if not isinstance(raw, str):
        raise ValueError("application_id")
    out["application_id"] = uuid.UUID(raw)

    raw = data.get("loan_type")
    if not isinstance(raw, str):
        raise ValueError("loan_type")
    out["loan_type"] = LoanType(raw)

    raw = data.get("principal")
    if not isinstance(raw, str):
        raise ValueError("principal")
    principal = Decimal(raw)
    if principal <= 0 or -principal.as_tuple().exponent > 2:
        raise ValueError("principal")
    out["principal"] = principal

    raw = data.get("rate")
    if not isinstance(raw, str):
        raise ValueError("rate")
    rate = Decimal(raw)
    if not 0 <= rate <= Decimal("0.25") or -rate.as_tuple().exponent > 6:
        raise ValueError("rate")
    out["rate"] = rate

    for name, low, high in (("term_months", 12, 600), ("credit_score", 300, 850)):
        raw = data.get(name)
        if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
            raise ValueError(name)
        out[name] = raw

    raw = data.get("ltv")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 100:
        raise ValueError("ltv")
    out["ltv"] = float(raw)

    raw = data.get("property")
    if not isinstance(raw, dict):
        raise ValueError("property")
    address = {}
    for name, limit in (("line1", 120), ("city", 80)):
        value = raw.get(name)
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise ValueError(f"property.{name}")
        address[name] = value
    state = raw.get("state")
    if not isinstance(state, str) or len(state) != 2 or not state.isupper():
        raise ValueError("property.state")
    address["state"] = state
    postal = raw.get("postal_code")
    if not isinstance(postal, str) or len(postal) not in (5, 10) or not postal[:5].isdigit():
        raise ValueError("property.postal_code")
    address["postal_code"] = postal
    out["property"] = address

    raw = data.get("co_borrowers", [])
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise ValueError("co_borrowers")
    out["co_borrowers"] = list(raw)
    return out


BAD = dict(PAYLOAD)
BAD.update(
    {
        "principal": "-1.00",
        "rate": "0.900000",
        "credit_score": 900,
        "ltv": 120.0,
        "property": dict(PAYLOAD["property"], postal_code="nope"),
    }
)


def throughput(run, iterations):
    best = min(timeit.repeat(run, number=iterations, repeat=5))
    return iterations / best


def main():
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    schema = ApplicationSchema()
    schema.load(PAYLOAD)  # compile field plans outside the measurement
    baseline_load(PAYLOAD)

    ours = throughput(lambda: schema.load(PAYLOAD), iterations)
    base = throughput(lambda: baseline_load(PAYLOAD), iterations)

    def baseline_failure():
        try:
            baseline_load(BAD)
        except ValueError:
            pass

    ours_bad = throughput(lambda: schema.validate(BAD), iterations)
    base_bad = throughput(baseline_failure, iterations)

    print(f"payload fields: {len(schema.field_names())} (+ nested address, list)")
    print(f"iterations per repeat: {iterations:,} (best of 5)")
    print(f"valid input (projectx load):        {ours:>12,.0f}/s  {1e6 / ours:6.2f} us")
    print(f"valid input (hand-written):         {base:>12,.0f}/s  {1e6 / base:6.2f} us")
    print(f"  projectx / hand-written: {ours / base:.2f}x")
    print(f"invalid input, 5 problems (projectx validate): {ours_bad:>9,.0f}/s")
    print(f"invalid input (hand-written, raises on first): {base_bad:>9,.0f}/s")
    print(f"  projectx / hand-written: {ours_bad / base_bad:.2f}x")
    print(f"python {sys.version.split()[0]}, date {dt.date.today().isoformat()}")



if __name__ == "__main__":
    main()
