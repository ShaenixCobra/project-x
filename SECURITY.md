# Security policy

project-x parses untrusted input for financial systems. Validation bypasses and
denial-of-service issues in the loading path are treated as security bugs.

## Supported versions

The latest minor release receives security fixes. Older minors are supported on
a best-effort basis; fixes are usually backported one minor version.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**). Do not open a public issue.

Include, where possible:

- the field/schema declaration involved,
- the input that triggers the problem,
- the observed and expected behaviour,
- the project-x version and Python version.

You can expect an acknowledgement within three working days. Once a fix is
ready, a patched release is published and the advisory is opened with credit
unless you prefer to stay anonymous.

## Scope

- Loader behaviour on adversarial input (deeply nested structures, very large
  strings or lists, pathological regular expressions supplied by callers).
- Serialization of values that violate the declared field contract.
- Any code path that silently accepts data it should reject.

Out of scope: vulnerabilities in applications that use project-x, and
caller-supplied `validate=` callables or `pattern=` regular expressions, which
run with your process's privileges.
