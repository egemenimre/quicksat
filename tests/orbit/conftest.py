"""
Fixtures for the orbit tests, from `tests/orbit/data/`.

The 510 km, 10:30 LTAN sun-synchronous TLE is a copy of the power tests', with Orekit's
eclipse times for it from their Orekit case, `tests/power/data/README.md`. The two OEM
files are figure 5-1 of CCSDS 502.0-B-2, and JAXA's SELENE ephemeris, an ODM version 2
test case.
"""

from pathlib import Path

import numpy as np
import pytest
from astropy.coordinates import CartesianDifferential, CartesianRepresentation, SkyCoord

from quicksat import u
from quicksat.orbit.tle import Tle, read_tle_file


def vectors(state: SkyCoord) -> tuple[np.ndarray, np.ndarray]:
    """A state's positions in mm and velocities in mm/s, shape (3, n)."""
    cartesian = state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    return cartesian.xyz.to_value(u.mm), velocity.d_xyz.to_value(u.mm / u.s)


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """The orbit test data's folder, from this file."""
    return Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def tle(data_dir) -> Tle:
    """The 510 km, 10:30 LTAN sun-synchronous TLE, with its epoch at 2026-10-01."""
    return read_tle_file(data_dir / "sso_510km.tle")
