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

from quicksat import MU_EARTH, R_EARTH
from quicksat.utils.orbit import Orbit

SAMPLE = "altitude: 500 km\ninclination: 97.4 deg\n"


@pytest.fixture
def orbit():
    return Orbit.from_yaml_text(SAMPLE)


def test_radius_is_altitude_above_the_equatorial_radius(orbit):
    assert orbit.radius.to("km").magnitude == pytest.approx(6878.137)


def test_period_matches_keplers_third_law(orbit):
    expected = (
        2
        * math.pi
        * math.sqrt(
            orbit.radius.to("km").magnitude ** 3 / MU_EARTH.to("km**3/s**2").magnitude
        )
    )
    assert orbit.period.to("s").magnitude == pytest.approx(expected)
    assert orbit.period.to("s").magnitude == pytest.approx(5677.0, abs=0.5)


def test_orbits_per_day_is_a_day_over_the_period(orbit):
    assert orbit.orbits_per_day.magnitude == pytest.approx(15.219, abs=1e-3)
    assert (orbit.orbits_per_day * orbit.period).to("day").magnitude == pytest.approx(
        1.0
    )


def test_circular_velocity(orbit):
    assert orbit.velocity.to("km/s").magnitude == pytest.approx(7.6126, abs=1e-4)


def test_ground_track_speed_is_scaled_by_the_radius_ratio(orbit):
    """Slower than the orbital velocity, by exactly R_earth / r."""
    ratio = (R_EARTH / orbit.radius).to("dimensionless").magnitude
    assert orbit.ground_track_speed / orbit.velocity == pytest.approx(ratio)
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
    assert metres.period.to("s").magnitude == pytest.approx(km.period.to("s").magnitude)


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
    assert orbit.altitude.to("km").magnitude == pytest.approx(500.0)
    assert orbit.period.to("s").magnitude == pytest.approx(5677.0, abs=0.5)


def test_inclination_is_carried_but_unused():
    """
    Nothing derives from inclination yet.

    It is read by the plane-change calculations in the delta-V budget, which do not
    exist, so it is carried through load and validation and no further.
    """
    orbit = Orbit.from_yaml_text(SAMPLE)
    assert orbit.inclination.to("deg").magnitude == pytest.approx(97.4)
