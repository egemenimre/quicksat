# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for building a sun-synchronous TLE.

Each check reads the built element set back through SGP4, as a run would: the
node rate against the mean sun, the altitude averaged over one orbit, and the
local mean time at the first ascending node.
"""

from typing import cast

import numpy as np
import pytest
from astropy.coordinates import CartesianRepresentation
from astropy.tests.helper import assert_quantity_allclose
from astropy.time import Time

from quicksat import Q_, R_EARTH, u
from quicksat.orbit.geometry import geodetic
from quicksat.orbit.sso import MEAN_SUN_RATE, sso_tle
from quicksat.orbit.tle import tle_states
from quicksat.utils.intervals import TimeArray

EPOCH = Time("2026-10-01T06:00:00", scale="utc")
ALTITUDE = Q_(510, "km")


@pytest.fixture(scope="module")
def tle():
    """A 510 km sun-synchronous orbit at 13:30 LTAN."""
    return sso_tle(EPOCH, ALTITUDE, Q_(13.5, "h"), name="test")


def test_the_node_turns_with_the_mean_sun(tle):
    node_rate = Q_(tle.satrec.nodedot, "rad / min")
    assert_quantity_allclose(node_rate, MEAN_SUN_RATE, rtol=1e-9)


def test_the_altitude_averaged_over_one_orbit_is_the_one_asked_for(tle):
    times = tle.epoch + np.linspace(0, 1, 720, endpoint=False) * tle.nodal_period
    state = tle_states(tle, times, with_velocity=False)
    radius = cast(CartesianRepresentation, state.cartesian).norm()
    assert_quantity_allclose(radius.mean() - R_EARTH, ALTITUDE, atol=Q_(1, "cm"))


def test_the_epoch_is_the_one_asked_for_and_the_name_is_kept(tle):
    assert abs(float((tle.epoch - EPOCH).to_value(u.ms))) < 1e-3
    assert tle.name == "test"


@pytest.mark.parametrize("ltan", [10.5, 13.5, 18.0])
def test_the_first_ascending_node_is_at_the_local_time_asked_for(ltan):
    tle = sso_tle(EPOCH, ALTITUDE, Q_(ltan, "h"))
    # the satellite starts at the node of the mean orbit, so it crosses the
    # equator within seconds of the epoch. The crossing is found between two
    # samples 1 s apart, by linear interpolation.
    times: TimeArray = EPOCH + np.linspace(-60, 60, 121) * u.s
    latitude, longitude = geodetic(tle_states(tle, times, with_velocity=False))
    north = np.asarray(latitude.to_value(u.deg))
    east = np.asarray(longitude.to_value(u.deg))
    local_times = ((times.ut1.mjd % 1) * 24 + east / 15) % 24
    node = np.flatnonzero((north[:-1] < 0) & (north[1:] >= 0))[0]
    fraction = -north[node] / (north[node + 1] - north[node])
    local_time = local_times[node] + fraction * np.diff(local_times)[node]
    assert local_time == pytest.approx(ltan, abs=1 / 3600)


def test_the_altitude_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        sso_tle(EPOCH, Q_(0, "km"), Q_(10.5, "h"))


def test_an_orbit_too_high_to_be_sun_synchronous_is_refused():
    with pytest.raises(ValueError):
        sso_tle(EPOCH, Q_(6000, "km"), Q_(10.5, "h"))
