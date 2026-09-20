"""Fixtures shared across the test suite.

The tests that load a complete input file read it from `tests/data/` rather
than from `sample/`. The two trees hold copies of the same files, but they
answer to different owners: `sample/` is documentation and is free to change
with the notebooks, while `tests/data/` is a fixture and changes only when a
test is meant to change with it. Editing one no longer breaks the other.

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
        Absolute path to `tests/data`, independent of the working directory.
    """
    return Path(__file__).parent / "data"
