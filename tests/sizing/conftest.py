"""
Fixtures for the sizing tests.

A test that reads a whole input file reads it from `tests/sizing/data/`, not from
`sample/sizing/data/`, which changes with the notebooks.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The sizing test data's folder, from this file."""
    return Path(__file__).parent / "data"
