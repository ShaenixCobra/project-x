# project-x

[![CI](https://github.com/ShaenixCobra/project-x/actions/workflows/ci.yml/badge.svg)](https://github.com/ShaenixCobra/project-x/actions/workflows/ci.yml)

Strict, fast data validation and serialization for the values home-finance and
real-estate systems move around: loan applications, property records, payment
schedules, valuations, and the APIs between them.

```python
class LoanApplication(Schema):
    loan_id = UUID(required=True)
    principal = Decimal(gt=0, decimal_places=2, required=True)
    rate = Decimal(ge=0, le="0.25", decimal_places=6, required=True)
    term_months = Int(ge=12, le=600, required=True)
    property = Nested(Address, required=True)
```

- **Strict by default.** No `"360"` quietly becoming `360`, no binary float
  becoming a balance, no `nan` reaching a ledger.
- **Every problem at once.** A failing request returns one nested mapping keyed
  like the input, so an API can hand it straight back to the client.
- **JSON in, JSON out.** `load()` produces typed Python values; `dump()` always
  produces JSON-safe primitives (`Decimal` as a string, dates as ISO-8601).
- **No runtime dependencies.** Python 3.9+ and the standard library only.
- **Compiled per class.** Field plans are built once when a schema class is
  created, not on every request.

Status: `0.1.0`, pre-1.0. The public API in `projectx.__all__` is documented;
error-message *wording* may still change, error *structure* will not.

## Install

There is no PyPI release yet; install from a checkout:

```bash
git clone https://github.com/ShaenixCobra/project-x.git
cd project-x
python -m pip install -e ".[dev]"
```

## Quick start

```python
from projectx import Schema, Str, Decimal, Int, Date, UUID, List, Nested


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


schema = LoanApplication()
loan = schema.load(
    {
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
)

loan["principal"]          # Decimal('425000.00') — exact, not a float
schema.dumps(loan, indent=2)
```

`examples/loan_application.py` is a complete, runnable version of this:

```console
$ PYTHONPATH=src python examples/loan_application.py
loaded principal: Decimal('425000.00')
loaded property city: Austin
serialized:
{
  "loan_id": "5f0a1a3c-1f7e-4b9a-9d5e-0e6f0a2b7c11",
  "principal": "425000.00",
  "rate": "0.057500",
  "term_months": 360,
  "originated_on": "2026-03-01",
  "property": {
    "line1": "1 Analytical Way",
    "city": "Austin",
    "state": "TX",
    "postal_code": "78701"
  },
  "co_borrowers": [
    "Grace Hopper"
  ]
}
```

## Errors

`load()` validates every field even after one fails, then raises a single
`ValidationError` whose `messages` mirror the input:

```python
>>> import json
>>> from projectx import ValidationError
>>> try:
...     schema.load({
...         "loan_id": "not-a-uuid",
...         "principal": "0.00",
...         "rate": 1.2,
...         "term_months": "360",
...         "originated_on": "03/01/2026",
...         "property": {
...             "line1": "", "city": "Austin", "state": "Texas", "postal_code": "7870",
...         },
...     })
... except ValidationError as exc:
...     print(json.dumps(exc.messages, indent=2))
{
    'loan_id': ["expected a UUID, got 'not-a-uuid'"],
    'principal': ['must be greater than 0'],
    'rate': ['expected a decimal string, integer or Decimal, got float'],
    'term_months': ['expected an integer, got str'],
    'originated_on': ["expected an ISO-8601 date, got '03/01/2026'"],
    'property': {
        'line1': ['length must be at least 1'],
        'state': ["must match pattern '^[A-Z]{2}$'"],
        'postal_code': ["must match pattern '^\\d{5}(-\\d{4})?$'"],
    },
}
```

`str(exc)` flattens the same information into a log line with dotted paths:

```text
loan_id: expected a UUID, got 'not-a-uuid'; principal: must be greater than 0; ...; property.postal_code: must match pattern '^\d{5}(-\d{4})?$'
```

`projectx.iter_errors(messages)` yields `(path, message)` pairs, and
`exc.to_dict()` returns the messages (JSON-serializable) for an HTTP 422 body.
Note that a list of objects reports errors by index:
`{"items": {2: {"principal": [...]}}}`.

## Field reference

| Field | Accepts on load | Emits on dump | Constraints |
| --- | --- | --- | --- |
| `Str()` | `str` | `str` | `min_length`, `max_length`, `pattern`, `strip` |
| `Int()` | `int` (not `bool`) | `int` | `ge`, `le`, `gt`, `lt`, `multiple_of` |
| `Float()` | `int`, `float` | `float` | `ge`, `le`, `gt`, `lt`, `allow_non_finite` |
| `Decimal()` | `str`, `int`, `Decimal` | plain decimal string | `ge`, `le`, `gt`, `lt`, `max_digits`, `decimal_places` |
| `Bool()` | `bool` | `bool` | — |
| `Date()` | `date`, ISO-8601 `str` | `"YYYY-MM-DD"` | — |
| `DateTime()` | `datetime`, ISO-8601 `str` | ISO-8601 string | `require_tz` |
| `UUID()` | `UUID`, canonical `str` | canonical string | — |
| `Enum(cls)` | member or value | member value | `by_name` |
| `List(inner)` | `list` / `tuple` | `list` | `min_items`, `max_items` |
| `Dict(keys, values)` | `dict` | `dict` | `min_items`, `max_items` |
| `Nested(schema)` | mapping or object | `dict` | `many` |
| `Any()` | anything | unchanged | — |

Every field also accepts the common options:

| Option | Meaning |
| --- | --- |
| `required=True` | Key must be present and non-null. |
| `default=...` | Value when the key is absent (mutables are deep-copied). |
| `default_factory=...` | Callable producing the value when the key is absent. |
| `allow_none=True` | Explicit `null` is accepted and preserved. |
| `load_only=True` | Accepted on input, never returned by `dump()`. |
| `dump_only=True` | Never read by `load()`; can be computed before dumping. |
| `validate=...` | Callable (or list) run on the loaded value: raise `ValueError`, return `False`, or return a message. |
| `description=...` | Documentation for schema introspection. |

### Why these conversions are strict

- `Decimal` is never built from a binary float: `1.1` and `Decimal("1.1")` are
  different numbers, and silently picking one is how reconciliation breaks.
  Send decimal strings (or integers) from JSON.
- `"360"` is not an `int`, `1` is not a `bool`, and `True` is not an `int`,
  even though Python allows all three.
- `Float` rejects `nan`/`inf` unless you explicitly opt in, because they are not
  valid JSON and poison sums.
- `null` is only accepted when a field says `allow_none=True`.

## Schema API

| Member | Behaviour |
| --- | --- |
| `load(data, *, many=None, partial=None, unknown=None)` | Validate, return typed dicts. |
| `dump(data, *, many=None)` | Serialize mappings or objects with attributes. |
| `loads(json_text, ...)` / `dumps(data, ...)` | JSON helpers; `dumps` passes kwargs to `json.dumps`. |
| `validate(data, ...)` | Return the error mapping, or `{}` when valid. |
| `field_names()` | Field names in declaration order. |
| `fields` | A copy of `{name: field}`. |

Constructor and per-call options:

- `many=True` — input/output is a list of objects; errors are keyed by index.
- `partial=True` — skip all `required` checks (draft/PATCH payloads);
  `partial=("field", ...)` skips just those fields.
- `unknown="raise"` — report keys that are not fields as `unknown field`
  instead of dropping them.

Schemas inherit and override fields like normal Python classes:

```python
class RetailLoan(LoanApplication):
    principal = Decimal(gt=0, le="750000.00", decimal_places=2, required=True)
```

### Nesting, lists and recursion

`Nested` accepts a schema class, or its name as a string for self-referencing
structures:

```python
class Node(Schema):
    name = Str(required=True)
    children = List(Nested("Node"), default_factory=list)
```

## Performance

Measured with `python benchmarks/bench_validate.py` on this repository's 2-vCPU
Linux sandbox (CPython 3.12.3), best of 5 repeats × 20,000 iterations. The
payload has 9 top-level fields, a nested address object and a two-item list —
15 field validations per load. The comparison is a hand-written function that
performs the same checks, allocates no error structures, and raises on the
first problem (numbers move by a few percent between runs):

| Scenario | project-x | hand-written |
| --- | --- | --- |
| Valid payload | 88,701 loads/s (11.3 µs) | 179,775 loads/s (5.6 µs) |
| Invalid payload with 5 problems | 37,754 validations/s | 435,993 fail-fast/s |

project-x costs about 2× a hand-written validator on valid input. That
difference buys schema objects, per-field constraints declared as data,
aggregated errors with paths, nested/recursive support, introspection and JSON
round-tripping. The invalid-input row is not a like-for-like comparison: the
hand-written version returns after the first problem, while project-x collects
all five and builds the message tree.

If you need a different payload, edit `PAYLOAD` in the benchmark and rerun it;
the numbers above are a starting point, not a guarantee.

## Development

```bash
python -m pip install -e ".[dev]"
pytest                       # test suite
ruff check .                 # lint
python benchmarks/bench_validate.py
python examples/loan_application.py
```

CI runs the tests on CPython 3.9 through 3.13 and builds the sdist and wheel.

- Bug reports and pull requests: see [CONTRIBUTING.md](CONTRIBUTING.md).
- Security issues: see [SECURITY.md](SECURITY.md).
- Release notes: [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
