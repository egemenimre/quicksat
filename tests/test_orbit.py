# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the shared orbit model.

The reference case is the sample satellite: a 500 km circular orbit, for which
r = 6878.137 km, T = 5677 s, v = 7.6126 km/s and 15.219 orbits fit in a day.
"""

import math

import pytest
from pint.testing import assert_allclose

from quicksat import MU_EARTH, Q_, R_EARTH
from quicksat.utils.orbit import Orbit

SAMPLE = "altitude: 500 km\ninclination: 97.4 deg\n"


@pytest.fixture
def orbit():
    return Orbit.from_yaml_text(SAMPLE)


def test_radius_is_altitude_above_the_equatorial_radius(orbit):
    assert_allclose(orbit.radius, Q_(6878.137, "km"))


def test_period_matches_keplers_third_law(orbit):
    expected = (2 * math.pi * (orbit.radius**3 / MU_EARTH) ** 0.5).to("s")
    assert_allclose(orbit.period, expected)
    assert_allclose(orbit.period, Q_(5677.0, "s"), atol=0.5)


def test_orbits_per_day_is_a_day_over_the_period(orbit):
    assert_allclose(orbit.orbits_per_day, Q_(15.219, "dimensionless"), atol=1e-3)
    assert_allclose(orbit.orbits_per_day * orbit.period, Q_(1.0, "day"))


def test_circular_velocity(orbit):
    assert_allclose(orbit.velocity, Q_(7.6126, "km/s"), atol=1e-4)


def test_ground_track_speed_is_scaled_by_the_radius_ratio(orbit):
    """Slower than the orbital velocity, by exactly R_earth / r."""
    assert_allclose(orbit.ground_track_speed, orbit.velocity * R_EARTH / orbit.radius)
    assert orbit.ground_track_speed < orbit.velocity


def test_a_higher_orbit_is_slower_and_longer():
    low = Orbit.from_yaml_text("altitude: 400 km\ninclination: 0 deg")
    high = Orbit.from_yaml_text("altitude: 800 km\ninclination: 0 deg")
    assert high.period > low.period
    assert high.velocity < low.velocity
    assert high.orbits_per_day < low.orbits_per_day


def test_units_are_converted_on_load():
    """The file may use any length unit; the derived figures are unaffected."""
    metres = Orbit.from_yaml_text("altitude: 500000 m\ninclination: 97.4 deg")
    km = Orbit.from_yaml_text(SAMPLE)
    assert_allclose(metres.period, km.period)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("altitude: 500 kg\ninclination: 97.4 deg", "length dimensions"),
        ("altitude: -500 km\ninclination: 97.4 deg", "must not be negative"),
        ("altitude: 500 km\ninclination: 97.4 km", "angle dimensions"),
        ("inclination: 97.4 deg", "altitude"),
    ],
)
def test_validation_failures(text, expected):
    with pytest.raises(ValueError, match=expected):
        Orbit.from_yaml_text(text)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        Orbit.from_yaml_file("no/such/orbit.yaml")


def test_sample_file_loads():
    orbit = Orbit.from_yaml_file("sample/data/orbit.yaml")
    assert_allclose(orbit.altitude, Q_(500.0, "km"))
    assert_allclose(orbit.period, Q_(5677.0, "s"), atol=0.5)


def test_inclination_is_carried_but_unused():
    """
    Nothing derives from inclination yet.

    It is read by the plane-change calculations in the delta-V budget, which do not
    exist, so it is carried through load and validation and no further.
    """
    orbit = Orbit.from_yaml_text(SAMPLE)
    assert_allclose(orbit.inclination, Q_(97.4, "deg"))
