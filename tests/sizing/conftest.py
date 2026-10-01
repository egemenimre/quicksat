"""Fixtures for the sizing tests.

The tests that load a complete input file read it from `tests/sizing/data/`,
not from `sample/sizing/data/`. The two folders hold copies of the same files,
but they serve different purposes. `sample/` is documentation and changes with
the notebooks. `tests/sizing/data/` is a fixture and changes only when a test
is meant to change with it. So editing one does not break the other.

The directory is resolved from this file rather than from a relative path, so
the suite passes wherever pytest is invoked from -- an IDE or a subdirectory,
not only the repository root.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The directory holding the test input files.

    Returns
    -------
    Path
        Absolute path to `tests/sizing/data`, independent of the working directory.
    """
    return Path(__file__).parent / "data"
