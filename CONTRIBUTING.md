# Contributing

Thanks for helping improve project-x. The library sits on the critical path of
lending and property systems, so the bar for backwards compatibility and test
coverage is intentionally high.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
```

Python 3.9 through 3.13 are supported. Anything older is not.

## What a pull request should contain

- A focused change with tests that fail without it.
- No new runtime dependencies. project-x deliberately ships with a standard
  library only footprint; optional extras must be justified in the PR.
- For behavioural changes: a `CHANGELOG.md` entry under `## [Unreleased]`.
- No loosening of validation defaults (coercion, non-finite numbers, null
  handling) without a clear rationale in the PR description.

## Benchmarks

If a change touches the loading or dumping hot path, run the benchmark before
and after and include both numbers:

```bash
python benchmarks/bench_validate.py
```

## Compatibility policy

- Public API (documented names in `projectx.__all__`) follows semantic
  versioning. Breaking changes require a major release and a deprecation
  period of at least one minor release.
- Error message wording is *not* part of the stable API — clients should assert
  on paths and error codes rather than exact prose. Structure (nested keys) is
  stable.
- Fields accept a superset of what they emit, never the other way around.

## Reporting security issues

Please do not open a public issue. See [SECURITY.md](SECURITY.md).
