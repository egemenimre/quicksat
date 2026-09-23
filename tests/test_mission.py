# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the shared mission model.

The reference case is the sample satellite: a 500 km circular orbit flown for seven
years, for which r = 6878.137 km, T = 5677 s, v = 7.6126 km/s and 15.219 orbits fit
in a day.
"""

import math

import pytest
from pint.testing import assert_allclose

from quicksat import MU_EARTH, Q_, R_EARTH
from quicksat.utils.mission import Mission

SAMPLE = "altitude: 500 km\ninclination: 97.4 deg\nduration: 7 yr\n"


@pytest.fixture
def mission():
    return Mission.from_yaml_text(SAMPLE)


def test_radius_is_altitude_above_the_equatorial_radius(mission):
    assert_allclose(mission.radius, Q_(6878.137, "km"))


def test_period_matches_keplers_third_law(mission):
    expected = (2 * math.pi * (mission.radius**3 / MU_EARTH) ** 0.5).to("s")
    assert_allclose(mission.period, expected)
    assert_allclose(mission.period, Q_(5677.0, "s"), atol=0.5)


def test_orbits_per_day_is_a_day_over_the_period(mission):
    assert_allclose(mission.orbits_per_day, Q_(15.219, "dimensionless"), atol=1e-3)
    assert_allclose(mission.orbits_per_day * mission.period, Q_(1.0, "day"))


def test_circular_velocity(mission):
    assert_allclose(mission.velocity, Q_(7.6126, "km/s"), atol=1e-4)


def test_ground_track_speed_is_scaled_by_the_radius_ratio(mission):
    """Slower than the orbital velocity, by exactly R_earth / r."""
    assert_allclose(
        mission.ground_track_speed, mission.velocity * R_EARTH / mission.radius
    )
    assert mission.ground_track_speed < mission.velocity


def test_a_higher_orbit_is_slower_and_longer():
    low = Mission.from_yaml_text("altitude: 400 km\ninclination: 0 deg\nduration: 7 yr")
    high = Mission.from_yaml_text(
        "altitude: 800 km\ninclination: 0 deg\nduration: 7 yr"
    )
    assert high.period > low.period
    assert high.velocity < low.velocity
    assert high.orbits_per_day < low.orbits_per_day


def test_units_are_converted_on_load():
    """The file may use any length unit; the derived figures are unaffected."""
    metres = Mission.from_yaml_text(
        "altitude: 500000 m\ninclination: 97.4 deg\nduration: 7 yr"
    )
    km = Mission.from_yaml_text(SAMPLE)
    assert_allclose(metres.period, km.period)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "altitude: 500 kg\ninclination: 97.4 deg\nduration: 7 yr",
            "length dimensions",
        ),
        (
            "altitude: -500 km\ninclination: 97.4 deg\nduration: 7 yr",
            "must not be negative",
        ),
        ("altitude: 500 km\ninclination: 97.4 km\nduration: 7 yr", "angle dimensions"),
        ("altitude: 500 km\ninclination: 97.4 deg\nduration: 7 km", "time dimensions"),
        (
            "altitude: 500 km\ninclination: 97.4 deg\nduration: -7 yr",
            "must not be negative",
        ),
        ("inclination: 97.4 deg\nduration: 7 yr", "altitude"),
        ("altitude: 500 km\ninclination: 97.4 deg", "duration"),
    ],
)
def test_validation_failures(text, expected):
    with pytest.raises(ValueError, match=expected):
        Mission.from_yaml_text(text)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        Mission.from_yaml_file("no/such/mission.yaml")


def test_input_file_loads(data_dir):
    mission = Mission.from_yaml_file(data_dir / "mission.yaml")
    assert_allclose(mission.altitude, Q_(500.0, "km"))
    assert_allclose(mission.period, Q_(5677.0, "s"), atol=0.5)
    assert_allclose(mission.duration, Q_(7.0, "year"))


def test_inclination_is_carried_but_unused():
    """
    Nothing derives from inclination.

    The delta-V budget's plane-change calculation takes the angle to change by as
    the manoeuvre's own value, not the plane it starts in, so the inclination is
    carried through load and validation and no further.
    """
    mission = Mission.from_yaml_text(SAMPLE)
    assert_allclose(mission.inclination, Q_(97.4, "deg"))
