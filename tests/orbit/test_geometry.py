# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the beta angle.

The satellite sits on the x axis and moves along y, so the orbit normal is +z.
The sun is placed by hand, so the expected angle follows from the geometry alone.
"""

import numpy as np
import pytest
from astropy.coordinates import (
    GCRS,
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.tests.helper import assert_quantity_allclose
from astropy.time import Time

from quicksat import Q_, u
from quicksat.orbit.geometry import beta_angle


@pytest.fixture
def state():
    position = CartesianRepresentation([6878.0, 0.0, 0.0], unit=u.km)
    velocity = CartesianDifferential([0.0, 7.6, 0.0], unit=u.km / u.s)
    obstime = Time("2026-01-01T00:00:00", scale="utc")
    return SkyCoord(position.with_differentials(velocity), frame=GCRS(obstime=obstime))


def sun_at(elevation_deg):
    """The sun 1 au away, at this angle above the orbit plane, toward +x."""
    angle = np.radians(elevation_deg)
    return CartesianRepresentation([np.cos(angle), 0.0, np.sin(angle)], unit=u.au)


@pytest.mark.parametrize("elevation", [90.0, 45.0, 0.0, -30.0, -90.0])
def test_beta_is_the_sun_elevation_above_the_orbit_plane(state, elevation):
    assert_quantity_allclose(
        beta_angle(state, sun_at(elevation)), Q_(elevation, "deg"), atol=Q_(1e-9, "deg")
    )


def test_beta_ignores_where_the_sun_is_along_the_plane(state):
    # Rotating the sun about the orbit normal does not change beta
    sun = CartesianRepresentation([0.0, -np.cos(0.5), np.sin(0.5)], unit=u.au)
    assert_quantity_allclose(
        beta_angle(state, sun), Q_(0.5, "rad"), atol=Q_(1e-9, "deg")
    )


def test_beta_flips_sign_with_the_direction_of_motion(state):
    reverse = CartesianDifferential([0.0, -7.6, 0.0], unit=u.km / u.s)
    retrograde = SkyCoord(
        state.cartesian.without_differentials().with_differentials(reverse),
        frame=state.frame.replicate_without_data(),
    )
    assert_quantity_allclose(
        beta_angle(retrograde, sun_at(45.0)), Q_(-45.0, "deg"), atol=Q_(1e-9, "deg")
    )
