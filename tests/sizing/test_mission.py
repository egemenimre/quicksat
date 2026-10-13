# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the shared mission model.

The reference case is the sample satellite: a 500 km circular orbit flown for seven
years, for which r = 6878.1 km, T = 5677 s, v = 7.6126 km/s and 15.219 orbits fit
in a day.
"""

import pytest
from astropy.tests.helper import assert_quantity_allclose

from quicksat import Q_, u
from quicksat.utils.mission import Mission

SAMPLE = "altitude: 500 km\ninclination: 97.4 deg\nduration: 7 yr\n"


@pytest.fixture
def mission():
    return Mission.from_yaml_text(SAMPLE)


def test_radius_is_altitude_above_the_equatorial_radius(mission):
    assert_quantity_allclose(mission.radius, Q_(6878.1, "km"))


def test_period(mission):
    assert_quantity_allclose(mission.period, Q_(5677.0, "s"), atol=Q_(0.5, "s"))


def test_orbits_per_day(mission):
    assert_quantity_allclose(
        mission.orbits_per_day,
        Q_(15.219, u.dimensionless_unscaled),
        atol=Q_(1e-3, u.dimensionless_unscaled),
    )


def test_circular_velocity(mission):
    assert_quantity_allclose(
        mission.velocity, Q_(7.6126, "km/s"), atol=Q_(1e-4, "km/s")
    )


def test_ground_track_speed(mission):
    """The orbital velocity times R_earth / r: 7.6126 * 6378.1 / 6878.1 km/s."""
    assert_quantity_allclose(
        mission.ground_track_speed, Q_(7.0592, "km/s"), atol=Q_(1e-4, "km/s")
    )


def test_units_are_converted_on_load():
    """The file may use any length unit, and the derived figures do not change."""
    metres = Mission.from_yaml_text(
        "altitude: 500000 m\ninclination: 97.4 deg\nduration: 7 yr"
    )
    km = Mission.from_yaml_text(SAMPLE)
    assert_quantity_allclose(metres.period, km.period)


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
        # a bare number is not an angle: degrees or radians has to be said
        ("altitude: 500 km\ninclination: 97.4\nduration: 7 yr", "angle dimensions"),
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
    assert_quantity_allclose(mission.altitude, Q_(500.0, "km"))
    assert_quantity_allclose(mission.inclination, Q_(97.4, "deg"))
    assert_quantity_allclose(mission.period, Q_(5677.0, "s"), atol=Q_(0.5, "s"))
    assert_quantity_allclose(mission.duration, Q_(7.0, "year"))
