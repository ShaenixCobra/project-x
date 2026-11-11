"""projectx — strict, fast data validation and serialization.

Built for the numbers that move money: mortgage applications, loan books,
property valuations and payment records. Loading is strict (no string-to-int
coercion, no float-to-Decimal guessing), errors are aggregated into a nested
mapping keyed like the input, and serialization always emits JSON-safe values.

Quick start::

    from projectx import Schema, Str, Decimal, Int, Date, Enum

    class Loan(Schema):
        loan_id = Str(min_length=1, max_length=64, required=True)
        principal = Decimal(gt=0, decimal_places=2, required=True)
        rate = Decimal(ge=0, le=1, decimal_places=6, required=True)
        term_months = Int(ge=1, le=600, required=True)
        originated_on = Date(required=True)

    loan = Loan().load(
        {
            "loan_id": "LN-0001",
            "principal": "425000.00",
            "rate": "0.0575",
            "term_months": 360,
            "originated_on": "2026-03-01",
        }
    )
"""

from .errors import ProjectXError, ValidationError, iter_errors
from .fields import (
    MISSING,
    UUID,
    Any,
    Bool,
    Date,
    DateTime,
    Decimal,
    Dict,
    Enum,
    Field,
    Float,
    Int,
    List,
    Nested,
    Str,
)
from .schema import Schema

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ProjectXError",
    "ValidationError",
    "iter_errors",
    "Schema",
    "Field",
    "MISSING",
    "Any",
    "Bool",
    "Date",
    "DateTime",
    "Decimal",
    "Dict",
    "Enum",
    "Float",
    "Int",
    "List",
    "Nested",
    "Str",
    "UUID",
]
