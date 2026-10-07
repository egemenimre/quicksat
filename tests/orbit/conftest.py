"""Fixtures for the orbit tests.

The tests read their inputs from `tests/orbit/data/`: the 510 km, 10:30 LTAN
sun-synchronous TLE, and Orekit's eclipse times for it. Both are copies of files
in `tests/power/data/` and `sample/scenario/data/`, kept here so that each test
folder owns its fixtures. The directory is resolved from this file, so the suite
passes wherever pytest is invoked from.
"""

from pathlib import Path

import pytest

from quicksat.orbit.tle import Tle, read_tle_file


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The directory holding the orbit test data.

    Returns
    -------
    Path
        Absolute path to `tests/orbit/data`, independent of the working directory.
    """
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def tle(data_dir) -> Tle:
    """The 510 km, 10:30 LTAN sun-synchronous TLE, with its epoch at 2026-10-01.

    Returns
    -------
    Tle
        The element set
    """
    return read_tle_file(data_dir / "sso_510km.tle")
