"""Shared test helpers."""

from __future__ import annotations

import pytest

from projectx import Schema


@pytest.fixture
def single():
    """Wrap one field in a throw-away schema and return the schema instance."""

    def _single(field):
        return type("Single", (Schema,), {"value": field})()

    return _single
