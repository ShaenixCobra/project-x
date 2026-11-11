# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-10

### Added

- `Schema` base class with declarative `Field` attributes, compiled field plans
  per class, `load` / `dump` / `loads` / `dumps` / `validate`.
- Field types: `Str`, `Int`, `Float`, `Decimal`, `Bool`, `Date`, `DateTime`,
  `UUID`, `Enum`, `List`, `Dict`, `Nested` (including self-referencing schemas),
  `Any`.
- Strict loading: no string-to-number coercion, no float-to-`Decimal`
  conversion, `bool` rejected where numbers are expected, non-finite floats
  rejected by default.
- Aggregated validation errors as a nested mapping keyed like the input, with
  dotted/bracketed paths via `iter_errors` and `ValidationError.to_dict`.
- Schema options: `many`, `partial` (bool or field names), `unknown`
  (`"ignore"` / `"raise"`), plus `load_only` / `dump_only` fields and
  `default` / `default_factory`.
- Serializable dumps: `Decimal` to plain decimal strings, dates/timestamps to
  ISO-8601, UUIDs to canonical strings, enums to their values.
- Test suite and a benchmark comparing schema loads against a hand-written
  validator.

[Unreleased]: https://github.com/ShaenixCobra/project-x/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ShaenixCobra/project-x/releases/tag/v0.1.0
