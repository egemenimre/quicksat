"""Fixtures for the power tests.

The power tests read their inputs and reference results from
`tests/power/data/`. The directory is resolved from this file, so the suite
passes wherever pytest is invoked from.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The directory holding the power test data.

    Returns
    -------
    Path
        Absolute path to `tests/power/data`, independent of the working directory.
    """
    return Path(__file__).parent / "data"
