"""Fixtures for the orbit tests.

The tests read their inputs from `tests/orbit/data/`: the 510 km, 10:30 LTAN
sun-synchronous TLE, and Orekit's eclipse times for it. Both are copies of files
in `tests/power/data/` and `sample/scenario/data/`, kept here so that each test
folder owns its fixtures. The directory is resolved from this file, so the suite
passes wherever pytest is invoked from.

Two CCSDS OEM files sit there too: the example of figure 5-1 of CCSDS
502.0-B-2, and an abbreviated ephemeris of SELENE that JAXA wrote as an ODM
version 2 test case.
"""

from pathlib import Path

import numpy as np
import pytest
from astropy.coordinates import CartesianDifferential, CartesianRepresentation, SkyCoord

from quicksat import u
from quicksat.orbit.tle import Tle, read_tle_file


def vectors(state: SkyCoord) -> tuple[np.ndarray, np.ndarray]:
    """The positions [mm] and the velocities [mm/s] of a state, shape (3, n)."""
    cartesian = state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    return cartesian.xyz.to_value(u.mm), velocity.d_xyz.to_value(u.mm / u.s)


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
